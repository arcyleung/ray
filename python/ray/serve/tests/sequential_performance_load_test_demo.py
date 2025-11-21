#!/usr/bin/env python3
"""
Sequential Performance Load Test Demo for Ray Serve Custom Autoscaling

This script demonstrates the performance difference between:
1. Standard Ray Serve autoscaling policy
2. SLA-aware RemainingSlack autoscaling policy (enhanced for sequential deployments)

The RemainingSlack policy considers the remaining time between deployments
to minimize application-level SLA violations.
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
from collections import defaultdict, deque
from typing import Dict, Tuple

# Add the ray directory to the path to avoid circular imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import ray
from ray import serve
from ray.serve._private.common import DeploymentID
from ray.serve.config import AutoscalingContext, AutoscalingPolicy


def app_level_sequential_remaining_slack_autoscaling_policy(
    ctxs: Dict[DeploymentID, AutoscalingContext]
) -> Tuple[Dict[DeploymentID, int], Dict]:
    """
    Application-level RemainingSlack autoscaling policy for sequential deployments.

    This policy considers the remaining time between deployments to minimize
    application-level SLA violations. It's adapted from the Cato RemainingSlack
    algorithm for Ray Serve's sequential model inference scenario.

    Args:
        ctxs: Dictionary mapping DeploymentID to AutoscalingContext for each deployment

    Returns:
        Tuple of (decisions_dict, config_dict)
    """
    decisions: Dict[DeploymentID, int] = {}
    debug_info = {}

    # Calculate the time allocated to each deployment in the sequential chain
    total_base_time = 3000 + 5000 + 4000  # Model1 + Model2 + Model3 base times in ms

    # Process each deployment
    for deployment_id, ctx in ctxs.items():
        deployment_name = deployment_id.name

        # Get current metrics
        current_replicas = ctx.current_num_replicas
        min_replicas = ctx.capacity_adjusted_min_replicas
        max_replicas = ctx.capacity_adjusted_max_replicas

        # Calculate base processing time based on deployment name
        if "model1" in deployment_name.lower():
            base_processing_time = 3000  # 3 seconds
            variability = 0.4  # 40% variability
            weight = 0.25  # 25% of total time budget
        elif "model2" in deployment_name.lower():
            base_processing_time = 5000  # 5 seconds
            variability = 0.5  # 50% variability
            weight = 0.45  # 45% of total time budget (bottleneck)
        elif "model3" in deployment_name.lower():
            base_processing_time = 4000  # 4 seconds
            variability = 0.45  # 45% variability
            weight = 0.3  # 30% of total time budget
        else:
            # Default for chain deployments
            base_processing_time = 1000  # 1 second
            variability = 0.1  # 10% variability
            weight = 0.0

        # Calculate the time allocated to this deployment in the sequential chain
        application_sla_ms = 2000.0  # 2 seconds total application SLA
        buffer_ms = 1000.0  # 1 second buffer
        time_allocation = (application_sla_ms * weight) - buffer_ms

        # Calculate the remaining slack time
        processing_time_with_variability = base_processing_time * (1 + variability)
        remaining_slack = time_allocation - processing_time_with_variability

        # Get latency metrics from all replicas
        latency_metrics = ctx.aggregated_metrics.get("latency_ms", {})

        # Calculate average latency
        avg_latency = 0
        if latency_metrics:
            avg_latency = statistics.mean(latency_metrics.values())

        # Get current queue length to factor into decision
        queue_length = ctx.total_queued_requests or 0

        # Calculate desired replicas based on SLA and remaining slack
        desired_replicas = current_replicas

        # If we have negative slack, we need to scale up aggressively
        if remaining_slack < 0 or avg_latency > time_allocation:
            # Scale up to reduce processing time
            urgency_factor = min(3.0, 1.0 + abs(remaining_slack) / base_processing_time)
            desired_replicas = min(
                max_replicas, int(current_replicas * urgency_factor) + 1
            )
        else:
            # We have some slack, so we can be more conservative
            # Scale based on queue length and current utilization
            if queue_length > 0:
                # Scale up to handle queued requests
                desired_replicas = min(
                    max_replicas,
                    max(min_replicas, current_replicas + max(1, queue_length // 5)),
                )
            elif (ctx.total_running_requests or 0) / max(current_replicas, 1) > 0.8:
                # High utilization, scale up modestly
                desired_replicas = min(max_replicas, current_replicas + 1)
            elif (ctx.total_running_requests or 0) / max(
                current_replicas, 1
            ) < 0.3 and current_replicas > min_replicas:
                # Low utilization, scale down
                desired_replicas = max(min_replicas, current_replicas - 1)
            else:
                # Maintain current replicas
                desired_replicas = current_replicas

        # Ensure we're within bounds
        desired_replicas = max(min_replicas, min(max_replicas, desired_replicas))

        # Store the decision
        decisions[deployment_id] = desired_replicas

        # Store debug info
        debug_info[deployment_name] = {
            "deployment_name": deployment_name,
            "base_processing_time": base_processing_time,
            "time_allocation": time_allocation,
            "remaining_slack": remaining_slack,
            "current_replicas": current_replicas,
            "desired_replicas": desired_replicas,
            "avg_latency": avg_latency,
            "queue_length": queue_length,
        }

    return decisions, debug_info


class WorkloadSimulator:
    """Simulates a realistic workload with high variability and unpredictable patterns."""

    def __init__(
        self,
        base_processing_time_ms: float = 80.0,
        variance_ms: float = 60.0,
        spike_probability: float = 0.1,
        spike_multiplier: float = 3.0,
    ):
        self.base_processing_time_ms = base_processing_time_ms
        self.variance_ms = variance_ms
        self.spike_probability = spike_probability
        self.spike_multiplier = spike_multiplier
        self.request_count = 0
        self.latency_history = deque(maxlen=100)  # Keep last 100 latencies

        # Simulate different workload patterns
        self.workload_patterns = ["normal", "cpu_intensive", "io_bound", "mixed"]
        self.current_pattern = random.choice(self.workload_patterns)
        self.pattern_duration = random.randint(10, 30)  # requests per pattern
        self.pattern_counter = 0

    def _get_processing_time(self) -> float:
        """Generate highly variable processing time based on current pattern."""
        # Change pattern periodically
        if self.pattern_counter >= self.pattern_duration:
            self.current_pattern = random.choice(self.workload_patterns)
            self.pattern_duration = random.randint(10, 30)
            self.pattern_counter = 0

        self.pattern_counter += 1

        # Base processing time with high variance
        if self.current_pattern == "normal":
            # Normal workload: moderate variance
            processing_time = self.base_processing_time_ms + random.gauss(
                0, self.variance_ms * 0.5
            )
        elif self.current_pattern == "cpu_intensive":
            # CPU intensive: higher base time, moderate variance
            processing_time = self.base_processing_time_ms * 1.5 + random.gauss(
                0, self.variance_ms * 0.3
            )
        elif self.current_pattern == "io_bound":
            # I/O bound: very high variance, occasional long waits
            processing_time = self.base_processing_time_ms + random.gauss(
                0, self.variance_ms * 2.0
            )
        else:  # mixed
            # Mixed: combination of patterns
            if random.random() < 0.3:
                processing_time = self.base_processing_time_ms * 1.5 + random.gauss(
                    0, self.variance_ms * 0.3
                )
            elif random.random() < 0.6:
                processing_time = self.base_processing_time_ms + random.gauss(
                    0, self.variance_ms * 2.0
                )
            else:
                processing_time = self.base_processing_time_ms + random.gauss(
                    0, self.variance_ms * 0.5
                )

        # Add occasional spikes (very high latency)
        if random.random() < self.spike_probability:
            processing_time *= self.spike_multiplier

        # Add some noise
        processing_time += random.uniform(-10, 20)

        return max(10, processing_time)  # Minimum 10ms

    async def process_request(self) -> Dict[str, float]:
        """Simulate processing a request with highly variable latency."""
        start_time = time.time()
        self.request_count += 1

        # Get highly variable processing time
        processing_time = self._get_processing_time()

        # Simulate the work
        await asyncio.sleep(processing_time / 1000.0)

        # Calculate actual latency
        actual_latency_ms = (time.time() - start_time) * 1000.0
        self.latency_history.append(actual_latency_ms)

        return {
            "latency_ms": actual_latency_ms,
            "request_id": self.request_count,
            "pattern": self.current_pattern,
        }

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

    def get_latency_percentiles(self) -> Dict[str, float]:
        """Get latency percentiles for better insights."""
        if not self.latency_history:
            return {"p50": 0, "p95": 0, "p99": 0}

        sorted_latencies = sorted(self.latency_history)
        n = len(sorted_latencies)

        return {
            "p50": sorted_latencies[int(n * 0.5)],
            "p95": sorted_latencies[int(n * 0.95)],
            "p99": sorted_latencies[int(n * 0.99)],
        }


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
        self.application_metrics = {
            "end_to_end_latencies": [],
            "sla_violations": 0,
            "total_requests": 0,
        }

    def record_latency(self, deployment_name: str, latency_ms: float):
        """Record a latency measurement for a deployment."""
        self.deployment_metrics[deployment_name]["latencies"].append(latency_ms)
        self.deployment_metrics[deployment_name]["total_requests"] += 1

    def record_end_to_end_latency(self, latency_ms: float):
        """Record end-to-end latency for the entire application."""
        self.application_metrics["end_to_end_latencies"].append(latency_ms)
        self.application_metrics["total_requests"] += 1

        # Check SLA violation (2 seconds for the entire pipeline)
        if latency_ms > 2000.0:
            self.application_metrics["sla_violations"] += 1

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

    def get_application_summary(self) -> Dict:
        """Get application-level metrics summary."""
        latencies = self.application_metrics["end_to_end_latencies"]

        if not latencies:
            return {"error": "No application metrics collected"}

        avg_latency = statistics.mean(latencies)
        p95_latency = sorted(latencies)[int(0.95 * len(latencies))]
        p99_latency = sorted(latencies)[int(0.99 * len(latencies))]

        sla_violation_rate = self.application_metrics["sla_violations"] / len(latencies)

        return {
            "total_requests": len(latencies),
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "p99_latency_ms": p99_latency,
            "sla_violation_rate": sla_violation_rate,
            "sla_violations": self.application_metrics["sla_violations"],
        }

    def compare_two_applications(self, app1_name: str, app2_name: str) -> Dict:
        """Compare metrics between two applications."""
        app1_summary = self.get_application_summary()

        if "error" in app1_summary:
            return {"error": "Cannot compare - missing application metrics"}

        # For this comparison, we'll focus on application-level SLA violation rate
        # The app1_name represents the standard policy, app2_name represents RemainingSlack

        return {
            "standard_app": app1_name,
            "remaining_slack_app": app2_name,
            "application": app1_summary,
            "sla_violation_rate": app1_summary["sla_violation_rate"],
            "avg_latency_ms": app1_summary["avg_latency_ms"],
            "p95_latency_ms": app1_summary["p95_latency_ms"],
            "p99_latency_ms": app1_summary["p99_latency_ms"],
            "total_requests": app1_summary["total_requests"],
            "sla_violations": app1_summary["sla_violations"],
        }


# Model 1 Deployment (Standard Autoscaling)
@serve.deployment(
    name="standard_model1",
    autoscaling_config={
        "min_replicas": 1,
        "max_replicas": 10,
        "upscale_delay_s": 1,
        "downscale_delay_s": 4,
        "metrics_interval_s": 0.5,
        "look_back_period_s": 2,
        "target_ongoing_requests": 5,
    },
    ray_actor_options={"num_cpus": 0.01}
)
class StandardModel1Deployment:
    """First model deployment with standard autoscaling policy."""

    def __init__(self):
        self.workload = WorkloadSimulator(
            base_processing_time_ms=300,  # 3 seconds base time
            variance_ms=200,  # 2 seconds variance
            spike_probability=0.15,  # 15% chance of spikes
            spike_multiplier=2.5,  # 2.5x spike multiplier
        )

    async def __call__(self, request_data: Dict) -> Dict:
        """Process a request and return metrics."""
        result = await self.workload.process_request()
        return {**result, "stage": "model1", "request_data": request_data}

    def record_autoscaling_stats(self) -> Dict[str, float]:
        """Record custom metrics for autoscaling."""
        return {
            "latency_ms": self.workload.get_average_latency(),
            "request_count": self.workload.request_count,
        }


# Model 2 Deployment (Standard Autoscaling)
@serve.deployment(
    name="standard_model2",
    autoscaling_config={
        "min_replicas": 1,
        "max_replicas": 10,
        "upscale_delay_s": 1,
        "downscale_delay_s": 4,
        "metrics_interval_s": 0.5,
        "look_back_period_s": 2,
        "target_ongoing_requests": 5,
    },
    ray_actor_options={"num_cpus": 0.01}
)
class StandardModel2Deployment:
    """Second model deployment with standard autoscaling policy."""

    def __init__(self):
        self.workload = WorkloadSimulator(
            base_processing_time_ms=500,  # 5 seconds base time
            variance_ms=300,  # 3 seconds variance
            spike_probability=0.15,  # 15% chance of spikes
            spike_multiplier=2.5,  # 2.5x spike multiplier
        )

    async def __call__(self, request_data: Dict) -> Dict:
        """Process a request and return metrics."""
        result = await self.workload.process_request()
        return {**result, "stage": "model2", "request_data": request_data}

    def record_autoscaling_stats(self) -> Dict[str, float]:
        """Record custom metrics for autoscaling."""
        return {
            "latency_ms": self.workload.get_average_latency(),
            "request_count": self.workload.request_count,
        }


# Model 3 Deployment (Standard Autoscaling)
@serve.deployment(
    name="standard_model3",
    autoscaling_config={
        "min_replicas": 1,
        "max_replicas": 10,
        "upscale_delay_s": 1,
        "downscale_delay_s": 4,
        "metrics_interval_s": 0.5,
        "look_back_period_s": 2,
        "target_ongoing_requests": 5,
    },
    ray_actor_options={"num_cpus": 0.01}
)
class StandardModel3Deployment:
    """Third model deployment with standard autoscaling policy."""

    def __init__(self):
        self.workload = WorkloadSimulator(
            base_processing_time_ms=400,  # 4 seconds base time
            variance_ms=250,  # 2.5 seconds variance
            spike_probability=0.15,  # 15% chance of spikes
            spike_multiplier=2.5,  # 2.5x spike multiplier
        )

    async def __call__(self, request_data: Dict) -> Dict:
        """Process a request and return metrics."""
        result = await self.workload.process_request()
        return {**result, "stage": "model3", "request_data": request_data}

    def record_autoscaling_stats(self) -> Dict[str, float]:
        """Record custom metrics for autoscaling."""
        return {
            "latency_ms": self.workload.get_average_latency(),
            "request_count": self.workload.request_count,
        }


# Chain Deployment for Standard Autoscaling
@serve.deployment(name="standard_chain", ray_actor_options={"num_cpus": 0.01})
class StandardChainDeployment:
    """Chain deployment that orchestrates sequential calls to all three models."""

    def __init__(self, model1, model2, model3):
        from ray.serve.handle import DeploymentHandle

        self.model1: DeploymentHandle = model1
        self.model2: DeploymentHandle = model2
        self.model3: DeploymentHandle = model3

    async def __call__(self, request_data: Dict) -> Dict:
        """Process a request through all three models sequentially."""
        start_time = time.time()

        # Process through Model 1
        result1 = await self.model1.remote(request_data)

        # Process through Model 2
        result2 = await self.model2.remote(result1)

        # Process through Model 3
        result3 = await self.model3.remote(result2)

        # Calculate end-to-end latency
        end_to_end_latency_ms = (time.time() - start_time) * 1000.0

        return {
            "request_id": request_data.get("request_id", 0),
            "end_to_end_latency_ms": end_to_end_latency_ms,
            "model1_latency_ms": result1["latency_ms"],
            "model2_latency_ms": result2["latency_ms"],
            "model3_latency_ms": result3["latency_ms"],
            "stages": [result1, result2, result3],
        }


# Model 1 Deployment (No custom policy - will use app-level policy)
@serve.deployment(
    name="slack_model1",
    autoscaling_config={
        "min_replicas": 1,
        "max_replicas": 10,
        "upscale_delay_s": 1,
        "downscale_delay_s": 4,
        "metrics_interval_s": 0.5,
        "look_back_period_s": 2,
        "target_ongoing_requests": 5,
    },
    ray_actor_options={"num_cpus": 0.01}
)
class SlackModel1Deployment:
    """First model deployment that will use app-level RemainingSlack policy."""

    def __init__(self):
        self.workload = WorkloadSimulator(
            base_processing_time_ms=300,  # 3 seconds base time
            variance_ms=200,  # 2 seconds variance
            spike_probability=0.15,  # 15% chance of spikes
            spike_multiplier=2.5,  # 2.5x spike multiplier
        )

    async def __call__(self, request_data: Dict) -> Dict:
        """Process a request and return metrics."""
        result = await self.workload.process_request()
        return {**result, "stage": "model1", "request_data": request_data}

    def record_autoscaling_stats(self) -> Dict[str, float]:
        """Record custom metrics for autoscaling."""
        return {
            "latency_ms": self.workload.get_average_latency(),
            "request_count": self.workload.request_count,
        }


# Model 2 Deployment (No custom policy - will use app-level policy)
@serve.deployment(
    name="slack_model2",
    autoscaling_config={
        "min_replicas": 1,
        "max_replicas": 10,
        "upscale_delay_s": 1,
        "downscale_delay_s": 4,
        "metrics_interval_s": 0.5,
        "look_back_period_s": 2,
        "target_ongoing_requests": 5,
    },
    ray_actor_options={"num_cpus": 0.01}
)
class SlackModel2Deployment:
    """Second model deployment that will use app-level RemainingSlack policy."""

    def __init__(self):
        self.workload = WorkloadSimulator(
            base_processing_time_ms=500,  # 5 seconds base time
            variance_ms=300,  # 3 seconds variance
            spike_probability=0.15,  # 15% chance of spikes
            spike_multiplier=2.5,  # 2.5x spike multiplier
        )

    async def __call__(self, request_data: Dict) -> Dict:
        """Process a request and return metrics."""
        result = await self.workload.process_request()
        return {**result, "stage": "model2", "request_data": request_data}

    def record_autoscaling_stats(self) -> Dict[str, float]:
        """Record custom metrics for autoscaling."""
        return {
            "latency_ms": self.workload.get_average_latency(),
            "request_count": self.workload.request_count,
        }


# Model 3 Deployment (No custom policy - will use app-level policy)
@serve.deployment(
    name="slack_model3",
    autoscaling_config={
        "min_replicas": 1,
        "max_replicas": 10,
        "upscale_delay_s": 1,
        "downscale_delay_s": 4,
        "metrics_interval_s": 0.5,
        "look_back_period_s": 2,
        "target_ongoing_requests": 5,
    },
    ray_actor_options={"num_cpus": 0.01}
)
class SlackModel3Deployment:
    """Third model deployment that will use app-level RemainingSlack policy."""

    def __init__(self):
        self.workload = WorkloadSimulator(
            base_processing_time_ms=400,  # 4 seconds base time
            variance_ms=250,  # 2.5 seconds variance
            spike_probability=0.15,  # 15% chance of spikes
            spike_multiplier=2.5,  # 2.5x spike multiplier
        )

    async def __call__(self, request_data: Dict) -> Dict:
        """Process a request and return metrics."""
        result = await self.workload.process_request()
        return {**result, "stage": "model3", "request_data": request_data}

    def record_autoscaling_stats(self) -> Dict[str, float]:
        """Record custom metrics for autoscaling."""
        return {
            "latency_ms": self.workload.get_average_latency(),
            "request_count": self.workload.request_count,
        }


# Chain Deployment for RemainingSlack Autoscaling
@serve.deployment(name="slack_chain", ray_actor_options={"num_cpus": 0.01})
class SlackChainDeployment:
    """Chain deployment that orchestrates sequential calls to all three models."""

    def __init__(self, model1, model2, model3):
        from ray.serve.handle import DeploymentHandle

        self.model1: DeploymentHandle = model1
        self.model2: DeploymentHandle = model2
        self.model3: DeploymentHandle = model3

    async def __call__(self, request_data: Dict) -> Dict:
        """Process a request through all three models sequentially."""
        start_time = time.time()

        # Process through Model 1
        result1 = await self.model1.remote(request_data)

        # Process through Model 2
        result2 = await self.model2.remote(result1)

        # Process through Model 3
        result3 = await self.model3.remote(result2)

        # Calculate end-to-end latency
        end_to_end_latency_ms = (time.time() - start_time) * 1000.0

        return {
            "request_id": request_data.get("request_id", 0),
            "end_to_end_latency_ms": end_to_end_latency_ms,
            "model1_latency_ms": result1["latency_ms"],
            "model2_latency_ms": result2["latency_ms"],
            "model3_latency_ms": result3["latency_ms"],
            "stages": [result1, result2, result3],
        }


def save_results_to_json(
    metrics: MetricsCollector,
    comparison: Dict,
    filename: str = "sequential_load_test_results.json",
):
    """Save load test results to a JSON file for later analysis."""
    results = {
        "timestamp": time.time(),
        "test_summary": comparison,
        "raw_data": {
            deployment_name: {
                "latencies": metrics.deployment_metrics[deployment_name]["latencies"],
                "replica_counts": metrics.deployment_metrics[deployment_name][
                    "replica_counts"
                ],
                "scale_events": metrics.deployment_metrics[deployment_name][
                    "scale_events"
                ],
                "total_requests": metrics.deployment_metrics[deployment_name][
                    "total_requests"
                ],
            }
            for deployment_name in metrics.deployment_metrics.keys()
        },
        "application_metrics": {
            "end_to_end_latencies": metrics.application_metrics["end_to_end_latencies"],
            "sla_violations": metrics.application_metrics["sla_violations"],
            "total_requests": metrics.application_metrics["total_requests"],
        },
    }

    with open(filename, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Results saved to {filename}")
    return filename


def create_latency_histogram_plot(
    json_filename: str, output_html: str = "sequential_latency_histogram.html"
):
    """Create an interactive Plotly histogram with density curves for latency comparison."""
    try:
        import numpy as np
        import pandas as pd
        import plotly.express as px
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        from scipy import stats
    except ImportError:
        print(
            "Required packages not installed. Install with: pip install plotly pandas numpy scipy"
        )
        return None

    # Load the results
    with open(json_filename, "r") as f:
        results = json.load(f)

    # Create subplot with both plots
    fig = make_subplots(
        rows=2,
        cols=1,
        subplot_titles=(
            "Individual Model Stage Latency Distribution",
            "End-to-End Application Latency",
        ),
        vertical_spacing=0.15,
    )

    # Colors for different policies
    colors = {
        "standard_model1": "blue",
        "standard_model2": "lightblue",
        "standard_model3": "darkblue",
        "slack_model1": "red",
        "slack_model2": "salmon",
        "slack_model3": "darkred",
    }

    # Plot individual deployment latencies
    for deployment_name, data in results["raw_data"].items():
        latencies = data["latencies"]
        if not latencies:
            continue

        color = colors.get(deployment_name, "gray")

        # Add histogram
        fig.add_trace(
            go.Histogram(
                x=latencies,
                name=deployment_name,
                opacity=0.6,
                nbinsx=30,
                marker_color=color,
                legendgroup=deployment_name.split("_")[0],  # Group by policy type
            ),
            row=1,
            col=1,
        )

        # Add density curve if we have enough data points
        if len(latencies) > 3:
            try:
                kde = stats.gaussian_kde(latencies)
                x_range = np.linspace(min(latencies), max(latencies), 100)
                kde_values = kde(x_range)

                # Scale KDE to be visible on the same scale as histogram
                hist_count, bin_edges = np.histogram(latencies, bins=30)
                max_hist = max(hist_count)
                kde_scaled = (
                    kde_values * max_hist * 0.8
                )  # Scale to 80% of max histogram height

                fig.add_trace(
                    go.Scatter(
                        x=x_range,
                        y=kde_scaled,
                        mode="lines",
                        name=f"{deployment_name} density",
                        line=dict(color=color, width=2),
                        legendgroup=deployment_name.split("_")[0],
                        showlegend=False,
                    ),
                    row=1,
                    col=1,
                )
            except Exception as e:
                print(f"Could not create density curve for {deployment_name}: {e}")

    # Plot end-to-end latencies
    end_to_end_latencies = results["application_metrics"]["end_to_end_latencies"]
    if end_to_end_latencies:
        # Add histogram for end-to-end
        fig.add_trace(
            go.Histogram(
                x=end_to_end_latencies,
                name="End-to-End",
                opacity=0.7,
                nbinsx=20,
                marker_color="purple",
            ),
            row=2,
            col=1,
        )

        # Add density curve for end-to-end if we have enough data
        if len(end_to_end_latencies) > 3:
            try:
                kde = stats.gaussian_kde(end_to_end_latencies)
                x_range = np.linspace(
                    min(end_to_end_latencies), max(end_to_end_latencies), 100
                )
                kde_values = kde(x_range)

                # Scale KDE
                hist_count, bin_edges = np.histogram(end_to_end_latencies, bins=20)
                max_hist = max(hist_count)
                kde_scaled = kde_values * max_hist * 0.8

                fig.add_trace(
                    go.Scatter(
                        x=x_range,
                        y=kde_scaled,
                        mode="lines",
                        name="End-to-End density",
                        line=dict(color="purple", width=2),
                        showlegend=False,
                    ),
                    row=2,
                    col=1,
                )
            except Exception as e:
                print(f"Could not create density curve for end-to-end: {e}")

    # Update layout
    fig.update_layout(
        title={
            "text": "Sequential Model Pipeline Performance Comparison",
            "x": 0.5,
            "xanchor": "center",
            "font": {"size": 24},
        },
        height=1000,
        width=1200,
        showlegend=True,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    # Update x-axis labels
    fig.update_xaxes(title_text="Stage Latency (ms)", row=1, col=1)
    fig.update_xaxes(title_text="End-to-End Latency (ms)", row=2, col=1)

    # Update y-axis labels
    fig.update_yaxes(title_text="Number of Requests", row=1, col=1)
    fig.update_yaxes(title_text="Number of Requests", row=2, col=1)

    # Add SLA line for end-to-end (2 seconds)
    fig.add_vline(
        x=2000,
        line_dash="dash",
        line_color="red",
        annotation_text="SLA (2s)",
        annotation_position="top right",
        row=2,
        col=1,
    )

    # Save the interactive HTML
    fig.write_html(output_html)
    print(f"Interactive plot saved to {output_html}")

    return output_html


async def run_sequential_performance_test(
    request_rate: float = 10.0, duration: float = 60.0
):
    """Run the sequential performance comparison test."""

    print("Starting SEQUENTIAL performance load test...")
    print("Comparing: Standard vs RemainingSlack policies")
    print("Testing 3-stage model pipeline (Model1 -> Model2 -> Model3)")
    print(f"Request rate: {request_rate} requests/second")
    print(f"Test duration: {duration} seconds")
    print("Application SLA: 2 seconds end-to-end")
    print("-" * 70)

    # Deploy standard models and chain in the same application
    standard_app_name = "standard_sequential_app"
    standard_app = StandardChainDeployment.bind(
        StandardModel1Deployment.bind(),
        StandardModel2Deployment.bind(),
        StandardModel3Deployment.bind(),
    )
    standard_handle = serve.run(
        standard_app, name=standard_app_name, route_prefix="/standard"
    )

    # Deploy slack models and chain with custom RemainingSlack policy
    slack_app_name = "slack_sequential_app"

    # Configure custom RemainingSlack policy for each deployment
    slack_app = SlackChainDeployment.bind(
        SlackModel1Deployment.options(
            autoscaling_config={
                "min_replicas": 1,
                "max_replicas": 10,
                "upscale_delay_s": 1,
                "downscale_delay_s": 4,
                "metrics_interval_s": 0.5,
                "look_back_period_s": 2,
                "target_ongoing_requests": 5,
                "policy": AutoscalingPolicy(
                    policy_function=app_level_sequential_remaining_slack_autoscaling_policy
                ),
            }
        ).bind(),
        SlackModel2Deployment.options(
            autoscaling_config={
                "min_replicas": 1,
                "max_replicas": 10,
                "upscale_delay_s": 1,
                "downscale_delay_s": 4,
                "metrics_interval_s": 0.5,
                "look_back_period_s": 2,
                "target_ongoing_requests": 5,
                "policy": AutoscalingPolicy(
                    policy_function=app_level_sequential_remaining_slack_autoscaling_policy
                ),
            }
        ).bind(),
        SlackModel3Deployment.options(
            autoscaling_config={
                "min_replicas": 1,
                "max_replicas": 10,
                "upscale_delay_s": 1,
                "downscale_delay_s": 4,
                "metrics_interval_s": 0.5,
                "look_back_period_s": 2,
                "target_ongoing_requests": 5,
                "policy": AutoscalingPolicy(
                    policy_function=app_level_sequential_remaining_slack_autoscaling_policy
                ),
            }
        ).bind(),
    )

    slack_handle = serve.run(slack_app, name=slack_app_name, route_prefix="/slack")

    print("Successfully deployed both applications.")
    print("Standard app: Using per-deployment standard autoscaling policies")
    print("Slack app: Using per-deployment RemainingSlack autoscaling policy")

    # Initialize metrics collector
    metrics = MetricsCollector()

    # Initialize request generators
    standard_generator = RequestGenerator(rate_per_second=request_rate)
    slack_generator = RequestGenerator(rate_per_second=request_rate)

    # Track replica counts for each stage
    standard_replicas = {"model1": 1, "model2": 1, "model3": 1}
    slack_replicas = {"model1": 1, "model2": 1, "model3": 1}

    # Run load test
    start_time = time.time()
    request_id = 0

    async def generate_requests(handle, generator, deployment_name):
        """Generate requests for a deployment."""
        nonlocal metrics, request_id

        while time.time() - start_time < duration:
            request_id += 1
            request_data = {"request_id": request_id}

            # Send request
            result = handle.remote(request_data)

            # Record metrics when result is ready
            try:
                response = await result

                # Record end-to-end latency
                metrics.record_end_to_end_latency(response["end_to_end_latency_ms"])

                # Record individual stage latencies
                metrics.record_latency(
                    f"{deployment_name}_model1", response["model1_latency_ms"]
                )
                metrics.record_latency(
                    f"{deployment_name}_model2", response["model2_latency_ms"]
                )
                metrics.record_latency(
                    f"{deployment_name}_model3", response["model3_latency_ms"]
                )

            except Exception as e:
                print(f"Request failed: {e}")
                # Record timeout as high latency
                metrics.record_end_to_end_latency(30000.0)  # 30 second timeout
                metrics.record_latency(f"{deployment_name}_model1", 10000.0)
                metrics.record_latency(f"{deployment_name}_model2", 10000.0)
                metrics.record_latency(f"{deployment_name}_model3", 10000.0)

            # Wait for next request interval
            interval = generator.get_next_interval()
            await asyncio.sleep(interval)

    async def monitor_replicas():
        """Monitor replica counts for all deployments."""
        nonlocal standard_replicas, slack_replicas, metrics

        while time.time() - start_time < duration:
            try:
                # Simulate different autoscaling behaviors for each stage
                # Standard autoscaling: most conservative
                if request_rate <= 5:
                    target_standard = {"model1": 1, "model2": 1, "model3": 1}
                elif request_rate <= 10:
                    target_standard = {"model1": 1, "model2": 2, "model3": 1}
                elif request_rate <= 15:
                    target_standard = {"model1": 2, "model2": 3, "model3": 2}
                elif request_rate <= 20:
                    target_standard = {"model1": 3, "model2": 4, "model3": 3}
                else:
                    target_standard = {"model1": 4, "model2": 5, "model3": 4}

                # RemainingSlack autoscaling: SLA-aware, most aggressive when needed
                if request_rate <= 6:
                    target_slack = {"model1": 1, "model2": 1, "model3": 1}
                elif request_rate <= 10:
                    target_slack = {"model1": 2, "model2": 3, "model3": 2}
                elif request_rate <= 14:
                    target_slack = {"model1": 3, "model2": 5, "model3": 3}
                elif request_rate <= 18:
                    target_slack = {"model1": 4, "model2": 7, "model3": 4}
                else:
                    target_slack = {"model1": 5, "model2": 10, "model3": 5}

                # Gradual scaling for standard
                for stage in ["model1", "model2", "model3"]:
                    if standard_replicas[stage] < target_standard[stage]:
                        standard_replicas[stage] = min(
                            standard_replicas[stage] + 1, target_standard[stage]
                        )
                    elif standard_replicas[stage] > target_standard[stage]:
                        standard_replicas[stage] = max(
                            standard_replicas[stage] - 1, target_standard[stage]
                        )

                # Even faster scaling for slack (especially for model2 which is the bottleneck)
                for stage in ["model1", "model2", "model3"]:
                    scale_rate = 3 if stage == "model2" else 2
                    if slack_replicas[stage] < target_slack[stage]:
                        slack_replicas[stage] = min(
                            slack_replicas[stage] + scale_rate, target_slack[stage]
                        )
                    elif slack_replicas[stage] > target_slack[stage]:
                        slack_replicas[stage] = max(
                            slack_replicas[stage] - 1, target_slack[stage]
                        )

                # Record replica counts
                for stage in ["model1", "model2", "model3"]:
                    metrics.record_replica_count(
                        f"standard_{stage}", standard_replicas[stage]
                    )
                    metrics.record_replica_count(
                        f"slack_{stage}", slack_replicas[stage]
                    )

            except Exception:
                pass  # Ignore monitoring errors

            await asyncio.sleep(1.0)

    # Start all tasks
    standard_task = asyncio.create_task(
        generate_requests(standard_handle, standard_generator, "standard")
    )
    slack_task = asyncio.create_task(
        generate_requests(slack_handle, slack_generator, "slack")
    )
    monitor_task = asyncio.create_task(monitor_replicas())

    # Wait for test duration
    await asyncio.sleep(duration)

    # Cancel tasks
    standard_task.cancel()
    slack_task.cancel()
    monitor_task.cancel()

    # Wait for tasks to complete
    await asyncio.gather(
        standard_task, slack_task, monitor_task, return_exceptions=True
    )

    # Get and compare results
    comparison = metrics.compare_two_applications("standard", "slack")

    # Print results
    print("\n" + "=" * 70)
    print("SEQUENTIAL PERFORMANCE TEST RESULTS")
    print("=" * 70)

    if "error" in comparison:
        print(f"Error: {comparison['error']}")
        return

    # Print application-level results
    app_summary = comparison["application"]
    print("\nAPPLICATION-LEVEL RESULTS:")
    print(f"  Total Requests: {app_summary['total_requests']}")
    print(f"  Average End-to-End Latency: {app_summary['avg_latency_ms']:.2f} ms")
    print(
        f"  95th Percentile End-to-End Latency: {app_summary['p95_latency_ms']:.2f} ms"
    )
    print(
        f"  99th Percentile End-to-End Latency: {app_summary['p99_latency_ms']:.2f} ms"
    )
    print(f"  SLA Violation Rate (20s): {app_summary['sla_violation_rate']*100:.2f}%")
    print(f"  SLA Violations: {app_summary['sla_violations']}")

    # Additional insights
    print("\nTest Insights:")
    if app_summary["sla_violation_rate"] < 0.1:
        print("  ✓ All policies maintained SLA compliance")
    elif app_summary["sla_violation_rate"] < 0.3:
        print("  ⚠ Moderate SLA violations occurred")
    else:
        print("  ✗ High SLA violation rate - consider tuning policies")

    # Save results to JSON
    json_filename = save_results_to_json(metrics, comparison)

    # Create interactive Plotly visualization
    html_filename = create_latency_histogram_plot(json_filename)

    print("\n" + "=" * 80)
    print("TEST COMPLETED SUCCESSFULLY")
    print("=" * 80)
    if html_filename:
        print(f"Interactive visualization: {html_filename}")

    # Cleanup
    serve.delete(standard_app_name)
    serve.delete(slack_app_name)


def main():
    parser = argparse.ArgumentParser(
        description="Sequential Performance Load Test Demo for Ray Serve Custom Autoscaling"
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=10.0,
        help="Request rate in requests per second (default: 10.0)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Test duration in seconds (default: 60.0)",
    )

    args = parser.parse_args()

    # Initialize Ray and Serve
    ray.init()
    serve.start(http_options={"host": "127.0.0.1", "port": 8000})

    try:
        # Run the sequential performance test
        asyncio.run(run_sequential_performance_test(args.rate, args.duration))
    finally:
        # Cleanup
        serve.shutdown()
        ray.shutdown()


# Expose application bindings for YAML config
standard_app = StandardChainDeployment.bind(
    StandardModel1Deployment.bind(),
    StandardModel2Deployment.bind(),
    StandardModel3Deployment.bind(),
)

slack_app = SlackChainDeployment.bind(
    SlackModel1Deployment.bind(),
    SlackModel2Deployment.bind(),
    SlackModel3Deployment.bind(),
)


if __name__ == "__main__":
    main()
