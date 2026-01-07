# SLA-Aware Autoscaling for ML Pipelines with Ray's Custom Autoscaling API

## Introduction

Serving Deep Learning (DL) and Foundation Models (FMs) faces unpredictable latency due to varying input sizes, model complexity, and resource contention. In sequential pipelines, slowdowns cascade through stages, causing SLA violations. Traditional queue-based autoscaling reacts to problems rather than preventing them.

[Ray v2.51.0](https://github.com/ray-project/ray/releases/tag/ray-2.51.0) introduces a new custom autoscaling API that enables SLA-aware autoscaling policies like "RemainingSlack", which improves performance for sequential deployments with unpredictable latency patterns.

## The Challenge: Serving Workflows with Unpredictable Latency

### Understanding the Problem

Customers of Huawei Cloud's Inference service use DNNs and Foundation Models (FMs) in complex workflows. These workflows comprise of sequences of model requests with conditionals, branching, for various tasks (OCR, Object Detection, Semantic Segmentation). Each model is provisioned as an independent Ray Serve deployment, with the goal of serving all customers efficiently while adhering to application SLAs in this multi-tenant environment.

```bash
# Example of a simple sequential Image Processing workflow
Request → Model 1 (OCR) → Model 2 (DNN Object Detection) → Model 3 (Post-processing) → Response
```

Real workloads may involve heterogeneous processors: LLMs, Vision Language Models, or storage operations like vector database queries in RAG systems.
For a simple example, consider a sequential chain of deployments, each with different latency characteristics:
- **Model 1**: Fast preprocessing (300ms base latency)
- **Model 2**: Heavy model inference (500ms base latency)
- **Model 3**: Post-processing/ data storage (400ms base latency)

Suppose the customer desires an end-to-end latency SLA of 2 seconds for each request. SLA compliance challenges include processing time spikes (2-3x), fluctuating request rates (5-30+ req/s), and memory bandwidth contention from model loading. Traditional autoscaling struggles as it only sees local queue conditions without understanding global SLA constraints.

### The Benchmark Setup

The performance comparison used [`run_sequential_performance_test_sweep.py`](./python/ray/serve/tests/run_sequential_performance_test_sweep.py) to test both policies across request rates (5-20 req/s) with realistic workload simulation, with a 25-30% processing time variation in each stage, spike generation, and sequential pipeline orchestration.

Results captured in [`sequential_load_test_sweep_results_1763763808.json`](sequential_load_test_sweep_results_1763763808.json:1) show key metrics: `avg_latency_ms`, `p95_latency_ms`, and `sla_violation_rate`.

## Traditional Autoscaling: The Queue Length Approach

### How It Works

Default Ray Serve autoscaling uses a reactive approach with `target_ongoing_requests`. It scales up deployments when the average queue length exceeds this value, and scales down at idle times when deployments have empty queues.

```python
# Default autoscaling configuration
autoscaling_config = {
    "min_replicas": 1,
    "max_replicas": 10,
    "target_ongoing_requests": 5,  # Scale when queue > 5
    "upscale_delay_s": 1,          # Wait 1s before scaling up
    "downscale_delay_s": 4,        # Wait 4s before scaling down
}
```

### Limitations

Queue-based autoscaling has critical drawbacks for unpredictable pipelines:
- **Reactive**: Scales only after requests build up in the queue of each deployment
- **Local optimization**: Each deployment scales independently
- **No SLA awareness**: Unaware of end-to-end application latency requirements
- **Delayed response**: Built-in delays slow reactions to load changes

By the time Model 2 (the bottleneck) detects a high queue length and scales up, Models 1 and 3 may have already processed requests that will wait at Model 2, causing SLA violations.

## The RemainingSlack Policy: SLA-Aware Autoscaling

### Core Concept

The RemainingSlack policy, implemented in [`app_level_sequential_remaining_slack_autoscaling_policy()`](python/ray/serve/tests/sequential_performance_load_test_demo.py:34), takes a fundamentally different approach. Instead of reacting to queue lengths, it proactively manages resources based on **remaining time budget** (i.e., "slack") at each deployment, relative to application-level SLA requirements.

### How It Works

#### 1. Time Budget Allocation

At a high level, the autoscaling policy allocates time budgets to each deployment based on their characteristics, ensuring that sequential execution time meets end-to-end SLA constraints:

```python
# Weight-based allocation based on processing complexity
model1_weight = 0.25  # 25% of time budget
model2_weight = 0.45  # 45% of time budget
model3_weight = 0.30  # 30% of time budget

time_allocation = (total_sla_ms * weight)
```

#### 2. Slack Calculation

Each deployment computes "remaining slack" as the difference between allocated time and expected processing time, with a variability factor to model average latency:

```python
processing_time_with_variability = base_processing_time * (1 + variability)
remaining_slack = time_allocation - processing_time_with_variability
```

The scaling logic follows two key principles: negative slack triggers aggressive scale-up, while positive slack enables load-based conservative scaling.

## Ray Serve's Custom Autoscaling API: The Enabler

Ray Serve's [flexible custom autoscaling API](https://docs.ray.io/en/latest/serve/advanced-guides/advanced-autoscaling.html#custom-metrics) allows developers to implement any scaling logic, with i) a custom record_autoscaling_stats method and ii) a custom policy.

### i) record_autoscaling_stats Function
This method is invoked periodically in the deployment to report customized autoscaling signals to the serve controller. In this example application made of sequential model deployments, we have record_autoscaling_stats reporting each deployment's processing latency for use in the slack calculation in the controller's custom autoscaling policy:

```python
@serve.deployment
class MyModel:
    """First model deployment that will use app-level RemainingSlack policy."""

    def __init__(self):
        self.latency_history = deque(maxlen=100)  # Keep last 100 latencies
        self.workload = DNNModel(
            model="YOLOv9",  # 3 seconds base time
            # ...
        )

    async def __call__(self, request_data: Dict) -> Dict:
        """Process a request and return metrics."""
        start_time = time.time()
        # Do work ...
        result = await self.workload.process_request()
        # Calculate actual latency
        actual_latency_ms = (time.time() - start_time) * 1000.0
        self.latency_history.append(actual_latency_ms)
        return {**result}

    def record_autoscaling_stats(self) -> Dict[str, float]:
        """Record custom metrics for autoscaling."""
        return {
            "latency_ms": self.get_average_latency(),
            "request_count": self.request_count,
        }

    def get_average_latency(self) -> float:
      """Get average latency from recent requests."""
      if not self.latency_history:
          return 0.0
      return statistics.mean(self.latency_history)
```

### ii) Autoscaling Policy Definition
The custom policy is defined as a function that takes autoscaling contexts across all deployments and outputs scaling decisions. In this example, the policy computes `remaining_slack` and whether to increment/decrement the number of current_replicas for each deployment. The next state of the autoscaler is updated by assigning and returning `decisions[deployment_id] = desired_replicas` from this policy method.

```python
def app_level_sequential_remaining_slack_autoscaling_policy(
    ctxs: Dict[DeploymentID, AutoscalingContext]
) -> Tuple[Dict[DeploymentID, int], Dict]:
  for deployment_id, ctx in ctxs.items():
    ...
    # Aggregate latency metrics across all replicas of this deployment
    latency_metrics = ctx.aggregated_metrics.get("latency_ms", {})
    avg_latency = statistics.mean(latency_metrics.values())

    # Allow some buffer time due to variability
    remaining_slack = deployment_allotted_time - avg_latency

    # If we have negative slack, we need to scale up aggressively
    if remaining_slack < 0:
        # Scale up to reduce processing time
        desired_replicas = min(max_replicas, current_replicas) + 1
    else:
      utilization = ctx.total_running_requests / max(current_replicas, 1)
        # Low utilization, scale down
        if utilization < 0.3 and current_replicas > min_replicas:
            desired_replicas = max(min_replicas, current_replicas - 1)
        else:
            # Maintain current replicas
            desired_replicas = current_replicas

    # Store the decision
    decisions[deployment_id] = desired_replicas

  return decisions, debug_info
  ```

Each `AutoscalingContext` provides metrics including replica counts, queue lengths, custom metrics, and historical performance data.

### Application-Level Configuration

The policy is applied declaratively in the Ray Serve application YAML, at deployment time.

<details>

<summary>Ray Serve Application Definition for sequential deployments</summary>

```yaml
applications:
  - name: slack_sequential_app
    autoscaling_policy:
      policy_function: ray.serve.tests...:app_level_sequential_remaining_slack_autoscaling_policy
    deployments:
      - name: slack_model1
        autoscaling_config:
          min_replicas: 1
          max_replicas: 10
          upscale_delay_s: 1
          downscale_delay_s: 4
          metrics_interval_s: 0.5
          look_back_period_s: 2
        ray_actor_options:
          num_cpus: 0.01
      # ... additional deployments (slack_model2, slack_model3, slack_chain)
```

</details>

#### Autoscaling Policies Comparison

| Request Rate | Metric | Standard Autoscaling | Slack Autoscaling | Improvement (Mean) |
|--------------|--------|---------------------|-------------------|------------------------------|
| **5.0 req/s** | Avg Latency (ms) | 1566.43 ± 22.84 | 1566.95 ± 57.12 | -0.03% |
| | P95 Latency (ms) | 2186.56 ± 13.33 | 2091.23 ± 92.09 | 4.36% |
| | SLA Violation (%) | 10.26 ± 0.69 | 8.70 ± 3.28 | 15.21% |
| **10.0 req/s** | Avg Latency (ms) | 1765.98 ± 46.94 | 1535.17 ± 11.71 | 13.07% |
| | P95 Latency (ms) | 3295.95 ± 388.61 | 2053.52 ± 27.06 | 37.71% |
| | SLA Violation (%) | 18.68 ± 0.91 | 6.94 ± 0.69 | 62.85% |
| **15.0 req/s** | Avg Latency (ms) | 1764.48 ± 16.68 | 1560.06 ± 36.29 | 11.59% |
| | P95 Latency (ms) | 3299.93 ± 340.60 | 2111.80 ± 30.85 | 36.00% |
| | SLA Violation (%) | 16.62 ± 0.85 | 9.09 ± 1.47 | 45.31% |
| **20.0 req/s** | Avg Latency (ms) | 1714.25 ± 23.19 | 1534.42 ± 24.57 | 10.49% |
| | P95 Latency (ms) | 2720.10 ± 220.01 | 2073.32 ± 22.00 | 23.78% |
| | SLA Violation (%) | 13.28 ± 1.12 | 7.16 ± 0.91 | 46.08% |


![SLA Violation Comparison](sla_violation_comparison.png)

![Average Latency Comparison](avg_latency_comparison.png)

![P95 Latency Comparison](p95_latency_comparison.png)

### Observations

With the SLA-aware policy, we observe a consistently low SLA violation rate below 10% across all request rates benchmarked.

At low request loads (5 req/s), the queue length based scaling behaves similarly to the SLA-aware custom autoscaling policy. This is because a single replica of each deployment is able to serve all the incoming requests within the latency deadline.

As load increases beyond 10 req/s, the default policy's reactive nature causes significant delays in scaling, while the SLA-aware policy's proactive approach prevents long queues from forming. Even as spikes in deployment processing time are introduced, the application's end-to-end latency remains stable using this custom autoscaling policy.

These improvements directly improve customer experience through consistent service delivery and resource efficiency through better scaling decisions. The Slack policy makes coordinated decisions across the entire pipeline and maintains more consistent performance across different load levels, with less variance in both latency and SLA compliance.

## Real-World Applications

Custom autoscaling policies apply to:
- **LLM serving chains**: Tokenization → embedding → generation → post-processing with unpredictable outputs
- **Multi-modal pipelines**: Preprocessing → feature extraction → classification with resources tailored to each stage's complexity
- **Data workflows**: ETL pipelines with variable processing times where proactive scaling prevents bottlenecks

## Implementation Guide

### Step 1: Define Your Custom Policy

```python
def your_custom_policy(ctxs: Dict[DeploymentID, AutoscalingContext]) -> Tuple[Dict[DeploymentID, int], Dict]:
    decisions = {}
    debug_info = {}

    for deployment_id, ctx in ctxs.items():
        # Your custom logic here
        decisions[deployment_id] = desired_replicas
        debug_info[deployment_id] = {...}

    return decisions, debug_info
```

### Step 2: Configure in YAML

```yaml
applications:
  - name: your_app
    autoscaling_policy:
      policy_function: your_module:your_custom_policy
    deployments:
      # Your deployments
```

### Step 3: Deploy and Monitor

```bash
serve deploy your_config.yaml
```

Monitor the debug information returned by your policy to fine-tune the scaling logic.

## Conclusion

The RemainingSlack policy demonstrates Ray Serve's custom autoscaling API capabilities, achieving:

- **15-63% reduction in SLA violation rate**
- **Up to 13% improvement in average latency**
- **Consistent, stable performance across all request load levels**

When used with the metrics aggregation API, it gives Ray developers the ultimate flexibility to tune performance to their domain specific use cases and customer requirements.

## Future Directions

The RemainingSlack policy demonstrates the power of Ray Serve's custom autoscaling API. Future enhancements could include:

1. **Integration with third-party APIs**: [External monitoring and metrics sources](https://github.com/ray-project/ray/issues/41135#issue-1993639174) can drive scaling decisions
2. **Cost-Aware Scaling**: Factor in cloud costs alongside SLA requirements, such as resource bidding by time-of-day
3. **Multi-Application Coordination**: Coordinate scaling across multiple applications sharing resources
4. **Dynamic SLA Adjustment**: Adapt SLA targets based changing business priorities and system conditions

---

**References:**
- [Benchmark Script](python/ray/serve/tests/run_sequential_performance_test_sweep.py:1)
- [Test Results](sequential_load_test_sweep_results_1763763808.json:1)
- [RemainingSlack Policy Implementation](python/ray/serve/tests/sequential_performance_load_test_demo.py:34)
- [Configuration Example](python/ray/serve/tests/sequential_performance_load_test_config.yaml:1)
- [REP](https://github.com/ray-project/enhancements/pull/56#issuecomment-2493932035)
- [Cloudwatch API integration](https://github.com/ray-project/ray/issues/41135#issue-1993639174)