#!/usr/bin/env python3
"""
Run the sequential performance load test comparing Standard vs RemainingSlack policies.
This version uses Ray Serve handles directly instead of HTTP requests.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from typing import Dict, Tuple

import numpy as np

# Add the ray directory to the path to avoid circular imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import ray
from ray import serve


async def send_request(handle) -> Tuple[float, bool]:
    """Send a single request and measure end-to-end latency."""
    start_time = time.time()
    try:
        request_data = {"request_id": 1}
        result = await handle.remote(request_data)
        latency = result.get("end_to_end_latency_ms", (time.time() - start_time) * 1000)
        return latency, True
    except Exception as e:
        # Only print error for debugging first few times
        if not hasattr(send_request, "error_count"):
            send_request.error_count = 0
        if send_request.error_count < 3:
            print(f"Request failed: {e}")
            send_request.error_count += 1
        return (time.time() - start_time) * 1000, False


async def run_load_test(handle, rate: float, duration: float) -> Dict:
    """Run load test against a specific application handle."""
    results = {
        "latencies": [],
        "successes": 0,
        "failures": 0,
        "sla_violations": 0,
        "start_time": time.time(),
    }

    # Calculate request interval
    interval = 1.0 / rate if rate > 0 else 0

    end_time = time.time() + duration

    while time.time() < end_time:
        # Send request
        latency, success = await send_request(handle)

        if success:
            results["latencies"].append(latency)
            results["successes"] += 1

            # Check SLA violation (2 seconds)
            if latency > 2000:
                results["sla_violations"] += 1
        else:
            results["failures"] += 1

        # Wait for next request interval
        if interval > 0:
            await asyncio.sleep(interval)

    results["end_time"] = time.time()
    return results


def calculate_metrics(results: Dict) -> Dict:
    """Calculate performance metrics from test results."""
    latencies = results["latencies"]
    successes = results.get("successes", 0)
    failures = results.get("failures", 0)

    if not latencies:
        return {
            "total_requests": successes + failures,
            "avg_latency_ms": 0,
            "p50_latency_ms": 0,
            "p95_latency_ms": 0,
            "p99_latency_ms": 0,
            "sla_violation_rate": 0,
            "sla_violations": 0,
            "successes": successes,
            "failures": failures,
            "success_rate": 0,
        }

    total_requests = successes + failures
    sla_violation_rate = (
        results["sla_violations"] / total_requests if total_requests > 0 else 0
    )
    success_rate = successes / total_requests if total_requests > 0 else 0

    return {
        "total_requests": total_requests,
        "avg_latency_ms": statistics.mean(latencies),
        "p50_latency_ms": statistics.median(latencies),
        "p95_latency_ms": np.percentile(latencies, 95),
        "p99_latency_ms": np.percentile(latencies, 99),
        "sla_violation_rate": sla_violation_rate,
        "sla_violations": results["sla_violations"],
        "successes": successes,
        "failures": failures,
        "success_rate": success_rate,
    }


async def main():
    parser = argparse.ArgumentParser(description="Run sequential performance load test")
    parser.add_argument("--rate", type=float, default=5.0, help="Requests per second")
    parser.add_argument(
        "--duration", type=float, default=30.0, help="Test duration in seconds"
    )
    args = parser.parse_args()

    print("=" * 70)
    print("SEQUENTIAL PERFORMANCE LOAD TEST")
    print("=" * 70)
    print(f"Request rate: {args.rate} requests/second")
    print(f"Test duration: {args.duration} seconds per application")
    print("Application SLA: 2 seconds end-to-end")
    print("-" * 70)

    # Connect to existing Ray and Serve
    ray.init()

    # Get handles to both applications
    try:
        standard_handle = serve.get_deployment_handle(
            "standard_chain", app_name="standard_sequential_app"
        )
        slack_handle = serve.get_deployment_handle(
            "slack_chain", app_name="slack_sequential_app"
        )
    except Exception as e:
        print(f"Error getting deployment handles: {e}")
        print("Make sure the applications are deployed with:")
        print(
            "  serve deploy python/ray/serve/tests/sequential_performance_load_test_config.yaml"
        )
        return

    # Test both applications separately
    apps = [
        (standard_handle, "standard_sequential_app", "Standard Autoscaling"),
        (slack_handle, "slack_sequential_app", "RemainingSlack Autoscaling"),
    ]

    all_results = {}

    for handle, app_name, description in apps:
        print(f"\nTesting {description} ({app_name})...")
        print("-" * 40)
        results = await run_load_test(handle, args.rate, args.duration)
        metrics = calculate_metrics(results)
        all_results[app_name] = metrics

        print(f"  Total Requests: {metrics['total_requests']}")
        print(f"  Successful Requests: {metrics['successes']}")
        print(f"  Failed Requests: {metrics['failures']}")
        print(f"  Average Latency: {metrics['avg_latency_ms']:.2f} ms")
        print(f"  50th Percentile: {metrics['p50_latency_ms']:.2f} ms")
        print(f"  95th Percentile: {metrics['p95_latency_ms']:.2f} ms")
        print(f"  99th Percentile: {metrics['p99_latency_ms']:.2f} ms")
        print(f"  SLA Violation Rate: {metrics['sla_violation_rate']*100:.2f}%")
        print(f"  SLA Violations: {metrics['sla_violations']}")
        print(f"  Success Rate: {metrics['success_rate']*100:.2f}%")

    # Save results
    output = {
        "timestamp": time.time(),
        "test_config": {
            "rate": args.rate,
            "duration": args.duration,
            "sla_threshold_ms": 2000,
        },
        "results": all_results,
    }

    with open("sequential_load_test_results_v3.json", "w") as f:
        json.dump(output, f, indent=2)

    print("\n" + "=" * 70)
    print("COMPARISON SUMMARY")
    print("=" * 70)

    std_metrics = all_results["standard_sequential_app"]
    slack_metrics = all_results["slack_sequential_app"]

    print("\nStandard Autoscaling:")
    print(f"  Requests: {std_metrics['total_requests']}")
    print(f"  Avg Latency: {std_metrics['avg_latency_ms']:.2f} ms")
    print(f"  95th Percentile: {std_metrics['p95_latency_ms']:.2f} ms")
    print(
        f"  SLA Violations: {std_metrics['sla_violations']} ({std_metrics['sla_violation_rate']*100:.2f}%)"
    )

    print("\nRemainingSlack Autoscaling:")
    print(f"  Requests: {slack_metrics['total_requests']}")
    print(f"  Avg Latency: {slack_metrics['avg_latency_ms']:.2f} ms")
    print(f"  95th Percentile: {slack_metrics['p95_latency_ms']:.2f} ms")
    print(
        f"  SLA Violations: {slack_metrics['sla_violations']} ({slack_metrics['sla_violation_rate']*100:.2f}%)"
    )

    # Calculate improvement
    if std_metrics["sla_violation_rate"] > 0:
        improvement = (
            (std_metrics["sla_violation_rate"] - slack_metrics["sla_violation_rate"])
            / std_metrics["sla_violation_rate"]
            * 100
        )
        print(f"\nSLA Violation Rate Improvement: {improvement:.2f}%")
    elif (
        slack_metrics["sla_violation_rate"] == 0
        and std_metrics["sla_violation_rate"] == 0
    ):
        print("\nBoth policies maintained 100% SLA compliance")
    else:
        print(
            f"\nRemainingSlack achieved {slack_metrics['sla_violation_rate']*100:.2f}% SLA violation rate vs {std_metrics['sla_violation_rate']*100:.2f}% for Standard"
        )

    # Latency comparison
    if std_metrics["avg_latency_ms"] > 0:
        latency_improvement = (
            (std_metrics["avg_latency_ms"] - slack_metrics["avg_latency_ms"])
            / std_metrics["avg_latency_ms"]
            * 100
        )
        print(f"\nAverage Latency Improvement: {latency_improvement:.2f}%")

    print("\nResults saved to sequential_load_test_results_v3.json")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
