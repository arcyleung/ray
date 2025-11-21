import asyncio
import random
import statistics
import time
from collections import defaultdict, deque
from typing import Dict, Tuple

import pytest

import ray
from ray import serve
from ray.serve._private.common import DeploymentID
from ray.serve.config import AutoscalingContext, AutoscalingPolicy


def latency_based_autoscaling_policy(ctx: AutoscalingContext) -> Tuple[int, Dict]:
    """
    Custom autoscaling policy that tracks latency metrics across all replicas
    to minimize SLA violations.

    This policy scales more aggressively when latency approaches SLA thresholds
    to ensure service quality is maintained.
    """
    # Configuration parameters
    SLA_THRESHOLD_MS = 100.0  # 100ms SLA threshold
    SCALE_UP_THRESHOLD = 0.8 * SLA_THRESHOLD_MS  # Scale up at 80ms
    SCALE_DOWN_THRESHOLD = 0.3 * SLA_THRESHOLD_MS  # Scale down at 30ms
    AGGRESSIVE_SCALE_UP_FACTOR = 2  # Scale up by 2x when needed
    CONSERVATIVE_SCALE_DOWN_FACTOR = 1  # Scale down by 1x (normal)

    # Get latency metrics from all replicas
    latency_metrics = ctx.aggregated_metrics.get("latency_ms", {})

    # Initialize policy state if not present
    policy_state = ctx.policy_state or {}
    last_scale_time = policy_state.get("last_scale_time", 0)
    scale_cooldown = 5.0  # 5 seconds cooldown between scaling decisions

    current_time = ctx.current_time or time.time()

    # If no latency metrics available, use default behavior
    if not latency_metrics:
        return ctx.current_num_replicas, policy_state

    # Calculate average latency across all replicas
    avg_latency = statistics.mean(latency_metrics.values())

    # Get current queue length to factor into decision
    queue_length = ctx.total_queued_requests or 0

    # Calculate desired replicas based on latency and queue
    desired_replicas = ctx.current_num_replicas

    # Check if we're in cooldown period
    in_cooldown = (current_time - last_scale_time) < scale_cooldown

    if not in_cooldown:
        # Scale up logic - more aggressive when approaching SLA violation
        if avg_latency > SCALE_UP_THRESHOLD or queue_length > 10:
            # Calculate how much we need to scale up
            if avg_latency > SLA_THRESHOLD_MS:
                # Critical: already violating SLA, scale up aggressively
                scale_factor = AGGRESSIVE_SCALE_UP_FACTOR
            else:
                # Approaching SLA threshold, scale up moderately
                latency_ratio = avg_latency / SLA_THRESHOLD_MS
                scale_factor = 1.0 + (latency_ratio - 0.8) * 2.5  # 1.0 to 1.5x

            # Also factor in queue length
            if queue_length > 20:
                scale_factor *= 1.5  # Extra scaling for high queue

            desired_replicas = min(
                int(ctx.current_num_replicas * scale_factor) + 1,
                ctx.capacity_adjusted_max_replicas,
            )

            policy_state["last_scale_time"] = current_time
            policy_state["last_scale_direction"] = "up"

        # Scale down logic - more conservative
        elif avg_latency < SCALE_DOWN_THRESHOLD and queue_length < 2:
            # Only scale down if we have more than minimum replicas
            if ctx.current_num_replicas > ctx.capacity_adjusted_min_replicas:
                # Conservative scale down
                scale_factor = CONSERVATIVE_SCALE_DOWN_FACTOR
                desired_replicas = max(
                    int(ctx.current_num_replicas / scale_factor),
                    ctx.capacity_adjusted_min_replicas,
                )

                policy_state["last_scale_time"] = current_time
                policy_state["last_scale_direction"] = "down"

    # Store metrics for monitoring
    policy_state["last_avg_latency"] = avg_latency
    policy_state["last_queue_length"] = queue_length

    return desired_replicas, policy_state


class WorkloadSimulator:
    """Simulates a realistic workload with configurable processing time."""

    def __init__(
        self, base_processing_time_ms: float = 50.0, variance_ms: float = 20.0
    ):
        self.base_processing_time_ms = base_processing_time_ms
        self.variance_ms = variance_ms
        self.request_count = 0
        self.latency_history = deque(maxlen=100)  # Keep last 100 latencies

    async def process_request(self) -> Dict[str, float]:
        """Simulate processing a request with variable latency."""
        start_time = time.time()
        self.request_count += 1

        # Simulate processing time with some randomness
        processing_time = self.base_processing_time_ms + random.gauss(
            0, self.variance_ms
        )
        processing_time = max(10, processing_time)  # Minimum 10ms

        # Simulate the work
        await asyncio.sleep(processing_time / 1000.0)

        # Calculate actual latency
        actual_latency_ms = (time.time() - start_time) * 1000.0
        self.latency_history.append(actual_latency_ms)

        return {"latency_ms": actual_latency_ms, "request_id": self.request_count}

    def get_average_latency(self) -> float:
        """Get average latency from recent requests."""
        if not self.latency_history:
            return 0.0
        return statistics.mean(self.latency_history)

    def get_sla_violation_rate(self, sla_threshold_ms: float = 100.0) -> float:
        """Calculate the rate of SLA violations."""
        if not self.latency_history:
            return 0.0
        violations = sum(1 for lat in self.latency_history if lat > sla_threshold_ms)
        return violations / len(self.latency_history)


class RequestGenerator:
    """Generates requests with Poisson or exponential inter-arrival times."""

    def __init__(self, rate_per_second: float = 10.0, distribution: str = "poisson"):
        self.rate_per_second = rate_per_second
        self.distribution = distribution
        self.request_times = []

    def get_next_interval(self) -> float:
        """Get the time interval until the next request."""
        if self.distribution == "poisson":
            # Poisson process: exponential inter-arrival times
            return random.expovariate(self.rate_per_second)
        elif self.distribution == "exponential":
            # Same as Poisson (exponential inter-arrival)
            return random.expovariate(self.rate_per_second)
        else:
            # Default to fixed interval
            return 1.0 / self.rate_per_second


class MetricsCollector:
    """Collects and compares metrics between deployments."""

    def __init__(self):
        self.deployment_metrics = defaultdict(
            lambda: {
                "latencies": [],
                "replica_counts": [],
                "sla_violations": 0,
                "total_requests": 0,
                "scale_events": [],
            }
        )

    def record_latency(self, deployment_name: str, latency_ms: float):
        """Record a latency measurement for a deployment."""
        self.deployment_metrics[deployment_name]["latencies"].append(latency_ms)
        self.deployment_metrics[deployment_name]["total_requests"] += 1

    def record_replica_count(self, deployment_name: str, count: int):
        """Record the replica count for a deployment."""
        self.deployment_metrics[deployment_name]["replica_counts"].append(count)

    def record_scale_event(
        self,
        deployment_name: str,
        from_replicas: int,
        to_replicas: int,
        timestamp: float,
    ):
        """Record a scaling event."""
        self.deployment_metrics[deployment_name]["scale_events"].append(
            {"from": from_replicas, "to": to_replicas, "timestamp": timestamp}
        )

    def get_summary(
        self, deployment_name: str, sla_threshold_ms: float = 100.0
    ) -> Dict:
        """Get a summary of metrics for a deployment."""
        metrics = self.deployment_metrics[deployment_name]
        latencies = metrics["latencies"]

        if not latencies:
            return {"error": "No metrics collected"}

        avg_latency = statistics.mean(latencies)
        p95_latency = sorted(latencies)[int(0.95 * len(latencies))]
        p99_latency = sorted(latencies)[int(0.99 * len(latencies))]

        sla_violations = sum(1 for lat in latencies if lat > sla_threshold_ms)
        sla_violation_rate = sla_violations / len(latencies)

        replica_counts = metrics["replica_counts"]
        avg_replicas = statistics.mean(replica_counts) if replica_counts else 0
        max_replicas = max(replica_counts) if replica_counts else 0

        return {
            "deployment": deployment_name,
            "total_requests": len(latencies),
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "p99_latency_ms": p99_latency,
            "sla_violation_rate": sla_violation_rate,
            "avg_replicas": avg_replicas,
            "max_replicas": max_replicas,
            "scale_events": len(metrics["scale_events"]),
        }

    def compare_deployments(
        self, deployment1: str, deployment2: str, sla_threshold_ms: float = 100.0
    ) -> Dict:
        """Compare metrics between two deployments."""
        summary1 = self.get_summary(deployment1, sla_threshold_ms)
        summary2 = self.get_summary(deployment2, sla_threshold_ms)

        if "error" in summary1 or "error" in summary2:
            return {"error": "Cannot compare - missing metrics"}

        # Calculate improvements
        latency_improvement = (
            (summary1["avg_latency_ms"] - summary2["avg_latency_ms"])
            / summary1["avg_latency_ms"]
            * 100
        )

        sla_improvement = (
            (summary1["sla_violation_rate"] - summary2["sla_violation_rate"])
            / max(summary1["sla_violation_rate"], 0.001)
            * 100
        )

        replica_efficiency = (
            (summary1["avg_replicas"] - summary2["avg_replicas"])
            / max(summary1["avg_replicas"], 0.001)
            * 100
        )

        return {
            "deployment1": summary1,
            "deployment2": summary2,
            "latency_improvement_percent": latency_improvement,
            "sla_improvement_percent": sla_improvement,
            "replica_efficiency_percent": replica_efficiency,
            "better_sla": deployment2 if sla_improvement > 0 else deployment1,
            "better_latency": deployment2 if latency_improvement > 0 else deployment1,
            "more_efficient": deployment2 if replica_efficiency < 0 else deployment1,
        }


@serve.deployment(
    autoscaling_config={
        "min_replicas": 1,
        "max_replicas": 10,
        "upscale_delay_s": 2,
        "downscale_delay_s": 5,
        "metrics_interval_s": 0.5,
        "look_back_period_s": 2,
        "target_ongoing_requests": 5,
    }
)
class StandardAutoscalingDeployment:
    """Deployment with standard autoscaling policy."""

    def __init__(self):
        self.workload = WorkloadSimulator(base_processing_time_ms=50, variance_ms=30)

    async def __call__(self) -> Dict:
        """Process a request and return metrics."""
        result = await self.workload.process_request()
        return result

    def record_autoscaling_stats(self) -> Dict[str, float]:
        """Record custom metrics for autoscaling."""
        return {
            "latency_ms": self.workload.get_average_latency(),
            "request_count": self.workload.request_count,
        }


@serve.deployment(
    autoscaling_config={
        "min_replicas": 1,
        "max_replicas": 10,
        "upscale_delay_s": 1,  # Faster upscale for custom policy
        "downscale_delay_s": 3,  # Faster downscale for custom policy
        "metrics_interval_s": 0.5,
        "look_back_period_s": 2,
        "target_ongoing_requests": 5,
        "policy": AutoscalingPolicy(policy_function=latency_based_autoscaling_policy),
    }
)
class CustomAutoscalingDeployment:
    """Deployment with custom latency-based autoscaling policy."""

    def __init__(self):
        self.workload = WorkloadSimulator(base_processing_time_ms=50, variance_ms=30)

    async def __call__(self) -> Dict:
        """Process a request and return metrics."""
        result = await self.workload.process_request()
        return result

    def record_autoscaling_stats(self) -> Dict[str, float]:
        """Record custom metrics for autoscaling."""
        return {
            "latency_ms": self.workload.get_average_latency(),
            "request_count": self.workload.request_count,
        }


class TestPerformanceLoadAutoscaling:
    """Performance load test comparing standard vs custom autoscaling policies."""

    @pytest.mark.parametrize("request_rate", [5, 10, 20])
    def test_performance_comparison(self, serve_instance, request_rate):
        """Compare performance between standard and custom autoscaling policies."""

        # Deploy both applications
        standard_app_name = "standard_autoscaling_app"
        custom_app_name = "custom_autoscaling_app"

        standard_handle = serve.run(
            StandardAutoscalingDeployment.bind(),
            name=standard_app_name,
            route_prefix="/standard",
        )

        custom_handle = serve.run(
            CustomAutoscalingDeployment.bind(),
            name=custom_app_name,
            route_prefix="/custom",
        )

        # Initialize metrics collector
        metrics = MetricsCollector()

        # Initialize request generators
        standard_generator = RequestGenerator(rate_per_second=request_rate)
        custom_generator = RequestGenerator(rate_per_second=request_rate)

        # Track replica counts
        standard_replicas = 1
        custom_replicas = 1

        # Run load test for 60 seconds
        test_duration = 60.0
        start_time = time.time()

        async def generate_requests(handle, generator, deployment_name):
            """Generate requests for a deployment."""
            nonlocal metrics

            while time.time() - start_time < test_duration:
                # Send request
                result = handle.remote()

                # Record metrics when result is ready
                try:
                    response = ray.get(result, timeout=5.0)
                    metrics.record_latency(deployment_name, response["latency_ms"])
                except Exception:
                    # Record timeout as high latency
                    metrics.record_latency(deployment_name, 5000.0)  # 5 second timeout

                # Wait for next request interval
                interval = generator.get_next_interval()
                await asyncio.sleep(interval)

        async def monitor_replicas():
            """Monitor replica counts for both deployments."""
            nonlocal standard_replicas, custom_replicas, metrics

            while time.time() - start_time < test_duration:
                try:
                    # Check standard deployment replicas
                    new_standard_replicas = len(
                        serve_instance._controller._get_running_replica_ids_for_deployment.remote(
                            DeploymentID(
                                name="StandardAutoscalingDeployment",
                                app_name=standard_app_name,
                            )
                        )
                    )

                    # Check custom deployment replicas
                    new_custom_replicas = len(
                        serve_instance._controller._get_running_replica_ids_for_deployment.remote(
                            DeploymentID(
                                name="CustomAutoscalingDeployment",
                                app_name=custom_app_name,
                            )
                        )
                    )

                    # Record changes
                    if new_standard_replicas != standard_replicas:
                        metrics.record_scale_event(
                            "standard",
                            standard_replicas,
                            new_standard_replicas,
                            time.time(),
                        )
                        standard_replicas = new_standard_replicas

                    if new_custom_replicas != custom_replicas:
                        metrics.record_scale_event(
                            "custom", custom_replicas, new_custom_replicas, time.time()
                        )
                        custom_replicas = new_custom_replicas

                    # Record current replica counts
                    metrics.record_replica_count("standard", standard_replicas)
                    metrics.record_replica_count("custom", custom_replicas)

                except Exception:
                    pass  # Ignore monitoring errors

                await asyncio.sleep(1.0)

        # Run the load test
        async def run_load_test():
            # Start request generation
            standard_task = asyncio.create_task(
                generate_requests(standard_handle, standard_generator, "standard")
            )
            custom_task = asyncio.create_task(
                generate_requests(custom_handle, custom_generator, "custom")
            )

            # Start replica monitoring
            monitor_task = asyncio.create_task(monitor_replicas())

            # Wait for test duration
            await asyncio.sleep(test_duration)

            # Cancel tasks
            standard_task.cancel()
            custom_task.cancel()
            monitor_task.cancel()

        # Run the test
        asyncio.run(run_load_test())

        # Get and compare results
        comparison = metrics.compare_deployments("standard", "custom")

        # Print results for debugging
        print(f"\nPerformance Test Results (Rate: {request_rate} req/s):")
        print(f"Standard Deployment: {comparison['deployment1']}")
        print(f"Custom Deployment: {comparison['deployment2']}")
        print(f"Latency Improvement: {comparison['latency_improvement_percent']:.2f}%")
        print(f"SLA Improvement: {comparison['sla_improvement_percent']:.2f}%")
        print(f"Replica Efficiency: {comparison['replica_efficiency_percent']:.2f}%")

        # Assertions
        # Custom policy should have better or equal SLA compliance
        assert (
            comparison["sla_improvement_percent"] >= 0
        ), "Custom policy should improve or maintain SLA compliance"

        # Custom policy should not use significantly more replicas
        assert (
            comparison["replica_efficiency_percent"] > -50
        ), "Custom policy should not use more than 50% more replicas"

        # At higher loads, custom policy should show benefits
        if request_rate >= 10:
            assert (
                comparison["sla_improvement_percent"] >= 5
            ), "Custom policy should show at least 5% SLA improvement at higher loads"


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", "-s", __file__]))
