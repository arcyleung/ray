# SLA-Aware Autoscaling for ML Pipelines: How Ray's Custom Autoscaling API Enables Flexibility for Clients Demanding High Performance

## Introduction

Latency unpredictability is a constant challenge in serving Large Language Models (LLMs) and Foundation Models (FMs), where processing times vary dramatically based on input size, model complexity, and resource contention. In sequential pipelines, these challenges amplify - a slowdown in one stage cascades through the entire pipeline, causing SLA violations.

Traditional autoscaling approaches that rely on queue length metrics react to performance degradation rather than anticipating it, leading to delayed scaling decisions and poor SLA compliance.

[Ray v2.51.0](https://github.com/ray-project/ray/releases/tag/ray-2.51.0) introduces a new custom autoscaling API that enables SLA-aware autoscaling policies like "RemainingSlack", which improves performance for sequential deployments with unpredictable latency patterns.

## The Challenge: Serving Workflows with Unpredictable Latency

### Understanding the Problem

Customers of Huawei Cloud's Inference service use DNNs and Foundation Models (FMs) in complex workflows - sequences of model requests with conditionals, branching, and various tasks (OCR, Vision Language Models, Semantic Segmentation). Each model is provisioned as an independent Ray Serve deployment, with the goal of serving all customers efficiently while adhering to application SLAs in this multi-tenant environment.

```bash
# Example of a sequential Image Processing workflow
Request → Model 1 (OCR) → Model 2 (DNN inference) → Post-processing → Response
```

In reality the workload may involve heterogeneous processors, using an assortment of Large Language Models/ Vision Language Models, or simply be data storage/ retrieval operations with in RAG systems (such as a vector database).
For a simple example, consider a sequential chain of deployments, each with different latency characteristics:
- **Model 1**: Fast preprocessing (300ms base latency)
- **Model 2**: Heavy model inference (500ms base latency)
- **Model 3**: Post-processing/ data storage (400ms base latency)

Suppose the customer desires an end-to-end latency SLA of 2 seconds for each request. Several factors determine how well the SLA can be met:
- **High variability**: Processing times can spike 2-3x due to accelerator utilization
- **Load fluctuations**: Request rates vary from 5 to 30+ requests/second based on realtime demand
- **Resource contention**: Multiple models competing for memory bandwidth as they are loaded/ unloaded

Traditional autoscaling struggles under these circumstances as it only sees local queue conditions without understanding global SLA constraints.

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

| Pros | Cons |
|------|------|
| Simple to implement and debug | Reactive, not proactive: Scales only after queues build up |
| Works out of the box | Local optimization: Each deployment scales independently |
| Resource-efficient for deterministic workloads | No SLA awareness: Doesn't consider end-to-end latency requirements |
| Default approach with proven reliability | Delayed response: Built-in delays cause slow reactions to load changes |

In long-running unpredictable pipelines, these drawbacks are critical. By the time Model 2 (the bottleneck) detects a high queue length and scales up, Models 1 and 3 may have already processed requests that will wait at Model 2, causing SLA violations.

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

Each deployment computes "remaining slack" as the difference between allocated time and expected processing time. A variability factor can be used to model each deployment's average latency.

```python
processing_time_with_variability = base_processing_time * (1 + variability)
remaining_slack = time_allocation - processing_time_with_variability
```

#### 3. Intelligent Scaling Decisions

The scaling logic follows two key principles:

- Negative slack → aggressive scale-up
- Positive slack → load-based conservative scaling

## Ray Serve's Custom Autoscaling API: The Enabler

Ray Serve's flexible custom autoscaling API allows developers to implement any scaling logic:

### Autoscaling Policy Definition

The custom policy is defined as a function that takes autoscaling contexts across all deployments and outputs scaling decisions:

```python
def app_level_sequential_remaining_slack_autoscaling_policy(
    ctxs: Dict[DeploymentID, AutoscalingContext]
) -> Tuple[Dict[DeploymentID, int], Dict]:
```

### Rich Context Information

Each `AutoscalingContext` provides comprehensive metrics including replica counts, queue lengths, custom metrics, and historical performance data.

### Application-Level Configuration

The policy is applied declaratively in the Ray Serve application YAML:

<details>

<summary>Ray Serve Application Definition for sequential deployments</summary>

```yaml
applications:
  - name: slack_sequential_app
    autoscaling_policy:
      policy_function: ray.serve.tests.sequential_performance_load_test_demo:app_level_sequential_remaining_slack_autoscaling_policy
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
      - name: slack_model2
        autoscaling_config:
          min_replicas: 1
          max_replicas: 10
          upscale_delay_s: 1
          downscale_delay_s: 4
          metrics_interval_s: 0.5
          look_back_period_s: 2
        ray_actor_options:
          num_cpus: 0.01
      - name: slack_model3
        autoscaling_config:
          min_replicas: 1
          max_replicas: 10
          upscale_delay_s: 1
          downscale_delay_s: 4
          metrics_interval_s: 0.5
          look_back_period_s: 2
        ray_actor_options:
          num_cpus: 0.01
      - name: slack_chain
        autoscaling_config:
          min_replicas: 1
          max_replicas: 10
          upscale_delay_s: 1
          downscale_delay_s: 4
          metrics_interval_s: 0.5
          look_back_period_s: 2
        ray_actor_options:
          num_cpus: 0.01
```

</details>

#### Autoscaling Policies Comparison

| Request Rate | Policy | Avg Latency (ms) | P95 Latency (ms) | SLA Violation (%) |
|--------------|--------|------------------|------------------|-------------------|
| 5.0 req/s | Standard Autoscaling | 1566.43 ± 22.84 | 2186.56 ± 13.33 | 10.26 ± 0.69 |
| 5.0 req/s | Slack Autoscaling | 1566.95 ± 57.12 | 2091.23 ± 92.09 | 8.70 ± 3.28 |
| 10.0 req/s | Standard Autoscaling | 1765.98 ± 46.94 | 3295.95 ± 388.61 | 18.68 ± 0.91 |
| 10.0 req/s | Slack Autoscaling | 1535.17 ± 11.71 | 2053.52 ± 27.06 | 6.94 ± 0.69 |
| 15.0 req/s | Standard Autoscaling | 1764.48 ± 16.68 | 3299.93 ± 340.60 | 16.62 ± 0.85 |
| 15.0 req/s | Slack Autoscaling | 1560.06 ± 36.29 | 2111.80 ± 30.85 | 9.09 ± 1.47 |
| 20.0 req/s | Standard Autoscaling | 1714.25 ± 23.19 | 2720.10 ± 220.01 | 13.28 ± 1.12 |
| 20.0 req/s | Slack Autoscaling | 1534.42 ± 24.57 | 2073.32 ± 22.00 | 7.16 ± 0.91 |

![SLA Violation Comparison](sla_violation_comparison.png)

![Average Latency Comparison](avg_latency_comparison.png)

![P95 Latency Comparison](p95_latency_comparison.png)

### Observations

With the SLA-aware policy, we observe a consistently low SLA violation rate below 10% across all request rates benchmarked.

At low request loads (5 req/s), the queue length based scaling behaves similarly to the SLA-aware custom autoscaling policy. This is because a single replica of each deployment is able to serve all the incoming requests within the latency deadline.

As load increases beyond 10 req/s, the default policy's reactive nature causes significant delays in scaling, the SLA-aware policy's proactive approach prevents long queues from forming. Even as spikes in deployment processing time are introduced, the application's end-to-end latency remains stable using this custom autoscaling policy.

### Why These Improvements Matter

These SLA improvements directly translate to business value:
- **Customer Experience**: Fewer SLA violations mean more consistent service delivery
- **Resource Efficiency**: Better scaling decisions reduce over-provisioning costs
- **System Reliability**: More predictable performance under varying loads
- **Competitive Advantage**: Ability to handle complex workflows with guaranteed performance

### Consistency and Stability

Unlike per-deployment autoscaling, the Slack policy makes coordinated decisions across the entire pipeline, understanding that scaling Model 1 without scaling Model 2 would be counterproductive.
The Slack policy maintains more consistent performance across different load levels, with less variance in both latency and SLA compliance. This predictability is crucial for production systems.

## Real-World Applications

### Large Language Model (LLM) Serving Chains

For LLM applications with unpredictable outputs (tokenization → embedding → generation → post-processing), custom autoscaling policies can dramatically reduce tail latencies and improve SLA compliance.

### Multi-Modal Inference Pipelines

Computer vision systems often use sequential models (preprocessing → feature extraction → classification → post-processing). Custom autoscaling policies can be tailored to different data modalities, such that each processing stage gets appropriate resources based on its complexity and variability.

### Data Processing Workflows

ETL and data processing pipelines with variable processing times benefit from the proactive scaling approach, preventing bottlenecks from cascading through the pipeline.

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

The `RemainingSlack` autoscaling policy is one example of many custom policies that are now possible through Ray Serve's custom autoscaling API. It is an advancement from the reactive, individual queue-based scaling to proactive, end-to-end SLA-awareness across deployments of the application. We show that it effectively improves the following serving performance metrics, at various loading conditions:

- **30-62% reduction in SLA violation rate**
- **6-20% improvement in average latency**
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