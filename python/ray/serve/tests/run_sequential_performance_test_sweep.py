#!/usr/bin/env python3
"""
Run the sequential performance load test comparing Standard vs RemainingSlack policies.
This version sweeps a range of request rates and records SLA violation comparisons.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from typing import Dict, List, Tuple

import numpy as np

# Add the ray directory to the path to avoid circular imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import ray
from ray import serve

SLA_MS = 15000

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
    """Run load test against a specific application handle with concurrent requests."""
    results = {
        "latencies": [],
        "successes": 0,
        "failures": 0,
        "sla_violations": 0,
        "start_time": time.time(),
        "request_timestamps": [],  # Track actual request times
    }

    # Calculate request interval
    interval = 1.0 / rate if rate > 0 else 0
    print(f"DEBUG: Target rate: {rate} req/s, Target interval: {interval:.3f}s")

    end_time = time.time() + duration
    pending_requests = []  # Store pending request futures

    try:
        while time.time() < end_time:
            # Record when we start sending this request
            request_start_time = time.time()
            results["request_timestamps"].append(request_start_time)

            # Send request asynchronously without waiting
            request_future = asyncio.create_task(send_request(handle))
            pending_requests.append((request_start_time, request_future))

            # Wait for the interval before sending the next request
            if interval > 0:
                await asyncio.sleep(interval)

        # Wait for all pending requests to complete
        print(f"DEBUG: Waiting for {len(pending_requests)} pending requests to complete...")
        for request_start_time, request_future in pending_requests:
            try:
                latency, success = await request_future

                if success:
                    results["latencies"].append(latency)
                    results["successes"] += 1

                    # Check SLA violation (2 seconds for sequential pipeline)
                    if latency > SLA_MS:
                        results["sla_violations"] += 1
                else:
                    results["failures"] += 1

            except Exception as e:
                print(f"Request failed with exception: {e}")
                results["failures"] += 1

    except Exception as e:
        print(f"Error in load test: {e}")

    results["end_time"] = time.time()

    # Calculate actual achieved rate
    if len(results["request_timestamps"]) > 1:
        total_time = results["request_timestamps"][-1] - results["request_timestamps"][0]
        actual_rate = (len(results["request_timestamps"]) - 1) / total_time if total_time > 0 else 0
        print(f"DEBUG: Target rate: {rate} req/s, Actual rate: {actual_rate:.2f} req/s")
        print(f"DEBUG: Total requests sent: {len(results['request_timestamps'])}")
        print(f"DEBUG: Successful requests: {results['successes']}, Failed requests: {results['failures']}")

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


async def run_sweep_test(
    standard_handle,
    slack_handle,
    rates: List[float],
    duration: float
) -> Dict:
    """Run load test sweep across multiple request rates."""

    all_results = {}

    print(f"Running sweep test with rates: {rates}")
    print(f"Duration per rate: {duration} seconds")
    print(f"Total estimated time: {len(rates) * 2 * duration / 60:.1f} minutes")
    print("-" * 70)

    for rate in rates:
        print(f"\n{'='*50}")
        print(f"TESTING RATE: {rate} requests/second")
        print(f"{'='*50}")

        rate_results = {}

        # Test both applications at this rate
        apps = [
            (standard_handle, "standard_sequential_app", "Standard Autoscaling"),
            (slack_handle, "slack_sequential_app", "RemainingSlack Autoscaling"),
        ]

        for handle, app_name, description in apps:
            print(f"\nTesting {description} at {rate} req/s...")
            print("-" * 40)

            results = await run_load_test(handle, rate, duration)
            metrics = calculate_metrics(results)
            rate_results[app_name] = metrics

            print(f"  Total Requests: {metrics['total_requests']}")
            print(f"  Successful Requests: {metrics['successes']}")
            print(f"  Failed Requests: {metrics['failures']}")
            print(f"  Average Latency: {metrics['avg_latency_ms']:.2f} ms")
            print(f"  95th Percentile: {metrics['p95_latency_ms']:.2f} ms")
            print(f"  99th Percentile: {metrics['p99_latency_ms']:.2f} ms")
            print(f"  SLA Violation Rate: {metrics['sla_violation_rate']*100:.2f}%")
            print(f"  SLA Violations: {metrics['sla_violations']}")
            print(f"  Success Rate: {metrics['success_rate']*100:.2f}%")

        # Store results for this rate
        all_results[str(rate)] = rate_results

        # Calculate and display comparison for this rate
        std_metrics = rate_results["standard_sequential_app"]
        slack_metrics = rate_results["slack_sequential_app"]

        print(f"\n{'='*50}")
        print(f"COMPARISON AT {rate} req/s")
        print(f"{'='*50}")

        print(f"\nStandard Autoscaling:")
        print(f"  Requests: {std_metrics['total_requests']}")
        print(f"  Avg Latency: {std_metrics['avg_latency_ms']:.2f} ms")
        print(f"  95th Percentile: {std_metrics['p95_latency_ms']:.2f} ms")
        print(f"  SLA Violations: {std_metrics['sla_violations']} ({std_metrics['sla_violation_rate']*100:.2f}%)")

        print(f"\nRemainingSlack Autoscaling:")
        print(f"  Requests: {slack_metrics['total_requests']}")
        print(f"  Avg Latency: {slack_metrics['avg_latency_ms']:.2f} ms")
        print(f"  95th Percentile: {slack_metrics['p95_latency_ms']:.2f} ms")
        print(f"  SLA Violations: {slack_metrics['sla_violations']} ({slack_metrics['sla_violation_rate']*100:.2f}%)")

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
            print(f"Average Latency Improvement: {latency_improvement:.2f}%")

        # Brief pause between rates to let the system stabilize
        if rate != rates[-1]:  # Don't pause after the last rate
            print(f"\nPausing for 5 seconds before next rate...")
            await asyncio.sleep(5)

    return all_results


def generate_summary_report(all_results: Dict, duration: float) -> Dict:
    """Generate a summary report comparing performance across all rates."""

    print(f"\n{'='*70}")
    print("SUMMARY REPORT ACROSS ALL RATES")
    print(f"{'='*70}")

    summary = {
        "test_duration_per_rate": duration,
        "rates_tested": list(all_results.keys()),
        "rate_comparisons": {},
        "overall_best_policy": None,
        "sla_violation_trends": {
            "standard": [],
            "slack": []
        },
        "latency_trends": {
            "standard": [],
            "slack": []
        }
    }

    # Collect data for each rate
    for rate, rate_data in all_results.items():
        std_metrics = rate_data["standard_sequential_app"]
        slack_metrics = rate_data["slack_sequential_app"]

        # Store trends
        summary["sla_violation_trends"]["standard"].append({
            "rate": float(rate),
            "sla_violation_rate": std_metrics["sla_violation_rate"],
            "sla_violations": std_metrics["sla_violations"]
        })

        summary["sla_violation_trends"]["slack"].append({
            "rate": float(rate),
            "sla_violation_rate": slack_metrics["sla_violation_rate"],
            "sla_violations": slack_metrics["sla_violations"]
        })

        summary["latency_trends"]["standard"].append({
            "rate": float(rate),
            "avg_latency_ms": std_metrics["avg_latency_ms"],
            "p95_latency_ms": std_metrics["p95_latency_ms"]
        })

        summary["latency_trends"]["slack"].append({
            "rate": float(rate),
            "avg_latency_ms": slack_metrics["avg_latency_ms"],
            "p95_latency_ms": slack_metrics["p95_latency_ms"]
        })

        # Calculate comparison for this rate
        rate_comparison = {
            "standard_sla_violation_rate": std_metrics["sla_violation_rate"],
            "slack_sla_violation_rate": slack_metrics["sla_violation_rate"],
            "standard_avg_latency": std_metrics["avg_latency_ms"],
            "slack_avg_latency": slack_metrics["avg_latency_ms"],
            "sla_improvement_percent": 0,
            "latency_improvement_percent": 0,
            "winner": "tie"
        }

        if std_metrics["sla_violation_rate"] > 0:
            rate_comparison["sla_improvement_percent"] = (
                (std_metrics["sla_violation_rate"] - slack_metrics["sla_violation_rate"])
                / std_metrics["sla_violation_rate"]
                * 100
            )

        if std_metrics["avg_latency_ms"] > 0:
            rate_comparison["latency_improvement_percent"] = (
                (std_metrics["avg_latency_ms"] - slack_metrics["avg_latency_ms"])
                / std_metrics["avg_latency_ms"]
                * 100
            )

        # Determine winner for this rate
        if slack_metrics["sla_violation_rate"] < std_metrics["sla_violation_rate"]:
            rate_comparison["winner"] = "slack"
        elif std_metrics["sla_violation_rate"] < slack_metrics["sla_violation_rate"]:
            rate_comparison["winner"] = "standard"
        else:
            # If SLA violation rates are equal, compare latency
            if slack_metrics["avg_latency_ms"] < std_metrics["avg_latency_ms"]:
                rate_comparison["winner"] = "slack"
            elif std_metrics["avg_latency_ms"] < slack_metrics["avg_latency_ms"]:
                rate_comparison["winner"] = "standard"

        summary["rate_comparisons"][rate] = rate_comparison

    # Print summary table
    print(f"\n{'Rate':<8} {'Std SLA%':<10} {'Slack SLA%':<11} {'Improvement':<12} {'Winner':<10}")
    print("-" * 60)

    slack_wins = 0
    standard_wins = 0
    ties = 0

    for rate in sorted(all_results.keys(), key=float):
        comparison = summary["rate_comparisons"][rate]
        std_sla = comparison["standard_sla_violation_rate"] * 100
        slack_sla = comparison["slack_sla_violation_rate"] * 100
        improvement = comparison["sla_improvement_percent"]
        winner = comparison["winner"]

        print(f"{rate:<8} {std_sla:<10.2f} {slack_sla:<11.2f} {improvement:<12.2f} {winner:<10}")

        if winner == "slack":
            slack_wins += 1
        elif winner == "standard":
            standard_wins += 1
        else:
            ties += 1

    print("-" * 60)
    print(f"Overall: Slack wins {slack_wins}, Standard wins {standard_wins}, Ties {ties}")

    if slack_wins > standard_wins:
        summary["overall_best_policy"] = "slack"
        print("Overall winner: RemainingSlack Autoscaling")
    elif standard_wins > slack_wins:
        summary["overall_best_policy"] = "standard"
        print("Overall winner: Standard Autoscaling")
    else:
        summary["overall_best_policy"] = "tie"
        print("Overall result: Tie")

    return summary


async def main():
    parser = argparse.ArgumentParser(description="Run sequential performance load test sweep")
    parser.add_argument(
        "--min-rate", type=float, default=10.0, help="Minimum request rate (default: 10.0)"
    )
    parser.add_argument(
        "--max-rate", type=float, default=30.0, help="Maximum request rate (default: 30.0)"
    )
    parser.add_argument(
        "--rate-step", type=float, default=5.0, help="Request rate increment (default: 5.0)"
    )
    parser.add_argument(
        "--duration", type=float, default=60.0, help="Test duration per rate in seconds (default: 60.0)"
    )
    parser.add_argument(
        "--rates", type=str, help="Comma-separated list of specific rates to test (overrides min/max/step)"
    )

    args = parser.parse_args()

    # Determine rates to test
    if args.rates:
        try:
            rates = [float(r.strip()) for r in args.rates.split(",")]
        except ValueError:
            print("Error: Invalid format for --rates. Use comma-separated values like '10,15,20,25,30'")
            return
    else:
        rates = []
        current_rate = args.min_rate
        while current_rate <= args.max_rate:
            rates.append(current_rate)
            current_rate += args.rate_step

    print("=" * 70)
    print("SEQUENTIAL PERFORMANCE LOAD TEST SWEEP")
    print("=" * 70)
    print(f"Rates to test: {rates}")
    print(f"Test duration per rate: {args.duration} seconds")
    print("Application SLA: 20 seconds end-to-end")
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

    # Run the sweep test
    start_time = time.time()
    all_results = await run_sweep_test(standard_handle, slack_handle, rates, args.duration)
    total_time = time.time() - start_time

    # Generate summary report
    summary = generate_summary_report(all_results, args.duration)

    # Save results
    output = {
        "timestamp": time.time(),
        "test_config": {
            "rates": rates,
            "duration": args.duration,
            "sla_threshold_ms": SLA_MS,
            "total_test_time_seconds": total_time,
        },
        "summary": summary,
        "detailed_results": all_results,
    }

    filename = f"sequential_load_test_sweep_results_{int(time.time())}.json"
    with open(filename, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults saved to {filename}")
    print(f"Total test time: {total_time/60:.1f} minutes")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())