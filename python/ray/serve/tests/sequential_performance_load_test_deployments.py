"""
Deployment classes for the sequential performance load test.
This module is imported by the config template for app-level policy deployment.
"""

import asyncio
import random
import statistics
import time
from collections import deque
from typing import Dict

from ray import serve
from ray.serve.handle import DeploymentHandle


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


# Model 1 Deployment (No custom policy - will use app-level policy)
@serve.deployment
class SlackModel1Deployment:
    """First model deployment that will use app-level RemainingSlack policy."""

    def __init__(self):
        self.workload = WorkloadSimulator(
            base_processing_time_ms=3000,  # 3 seconds base time
            variance_ms=2000,  # 2 seconds variance
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
@serve.deployment
class SlackModel2Deployment:
    """Second model deployment that will use app-level RemainingSlack policy."""

    def __init__(self):
        self.workload = WorkloadSimulator(
            base_processing_time_ms=5000,  # 5 seconds base time
            variance_ms=3000,  # 3 seconds variance
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
@serve.deployment
class SlackModel3Deployment:
    """Third model deployment that will use app-level RemainingSlack policy."""

    def __init__(self):
        self.workload = WorkloadSimulator(
            base_processing_time_ms=4000,  # 4 seconds base time
            variance_ms=2500,  # 2.5 seconds variance
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
@serve.deployment
class SlackChainDeployment:
    """Chain deployment that orchestrates sequential calls to all three models."""

    def __init__(self):
        # Get handles to the model deployments
        self.model1: DeploymentHandle = serve.get_deployment_handle("slack_model1")
        self.model2: DeploymentHandle = serve.get_deployment_handle("slack_model2")
        self.model3: DeploymentHandle = serve.get_deployment_handle("slack_model3")

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


# Create the application binding
app = SlackChainDeployment.bind()
