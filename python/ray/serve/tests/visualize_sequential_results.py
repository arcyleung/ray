#!/usr/bin/env python3
"""
Visualize the sequential performance test results comparing Standard vs RemainingSlack autoscaling.
"""

import json

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def load_results(filename="sequential_load_test_results_v3.json"):
    """Load test results from JSON file."""
    with open(filename, "r") as f:
        return json.load(f)


def create_comparison_plots(results):
    """Create comparison plots for the two autoscaling policies."""

    # Extract data
    std_data = results["results"]["standard_sequential_app"]
    slack_data = results["results"]["slack_sequential_app"]

    # Create subplots
    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=[
            "SLA Violation Rate Comparison",
            "Average Latency Comparison",
            "Request Throughput",
            "Latency Distribution",
        ],
        specs=[[{"type": "pie"}, {"type": "bar"}], [{"type": "bar"}, {"type": "bar"}]],
    )

    # 1. SLA Violation Rate Pie Charts
    fig.add_trace(
        go.Pie(
            labels=["SLA Compliant", "SLA Violations"],
            values=[
                std_data["total_requests"] - std_data["sla_violations"],
                std_data["sla_violations"],
            ],
            name="Standard Autoscaling",
            hole=0.3,
            marker_colors=["green", "red"],
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Pie(
            labels=["SLA Compliant", "SLA Violations"],
            values=[
                slack_data["total_requests"] - slack_data["sla_violations"],
                slack_data["sla_violations"],
            ],
            name="RemainingSlack Autoscaling",
            hole=0.3,
            marker_colors=["green", "red"],
        ),
        row=1,
        col=1,
    )

    # 2. Average Latency Bar Chart
    fig.add_trace(
        go.Bar(
            x=["Standard", "RemainingSlack"],
            y=[std_data["avg_latency_ms"], slack_data["avg_latency_ms"]],
            name="Average Latency (ms)",
            marker_color=["blue", "orange"],
            text=[
                f"{std_data['avg_latency_ms']:.0f}ms",
                f"{slack_data['avg_latency_ms']:.0f}ms",
            ],
            textposition="auto",
        ),
        row=1,
        col=2,
    )

    # Note: SLA threshold line removed to avoid plotly compatibility issues

    # 3. Request Throughput
    fig.add_trace(
        go.Bar(
            x=["Standard", "RemainingSlack"],
            y=[std_data["total_requests"], slack_data["total_requests"]],
            name="Total Requests",
            marker_color=["blue", "orange"],
            text=[std_data["total_requests"], slack_data["total_requests"]],
            textposition="auto",
        ),
        row=2,
        col=1,
    )

    # 4. Latency Percentiles
    fig.add_trace(
        go.Bar(
            x=["Standard", "RemainingSlack"],
            y=[std_data["p95_latency_ms"], slack_data["p95_latency_ms"]],
            name="95th Percentile (ms)",
            marker_color=["blue", "orange"],
            text=[
                f"{std_data['p95_latency_ms']:.0f}ms",
                f"{slack_data['p95_latency_ms']:.0f}ms",
            ],
            textposition="auto",
        ),
        row=2,
        col=2,
    )

    # Note: SLA threshold line removed to avoid plotly compatibility issues

    # Update layout
    fig.update_layout(
        title_text=f"Sequential Performance Test Results<br>Request Rate: {results['test_config']['rate']} req/s, Duration: {results['test_config']['duration']}s",
        height=800,
        showlegend=False,
    )

    # Update pie chart title
    fig.update_annotations(
        text="SLA Compliance: Standard (0% violations) vs RemainingSlack (100% violations)",
        row=1,
        col=1,
    )

    return fig


def create_summary_report(results):
    """Create a summary report with key findings."""
    std_data = results["results"]["standard_sequential_app"]
    slack_data = results["results"]["slack_sequential_app"]

    report = f"""
# Sequential Performance Load Test Report

## Test Configuration
- **Request Rate**: {results['test_config']['rate']} requests/second
- **Test Duration**: {results['test_config']['duration']} seconds per application
- **SLA Threshold**: {results['test_config']['sla_threshold_ms']/1000} seconds

## Results Summary

### Standard Autoscaling Policy
- **Total Requests**: {std_data['total_requests']}
- **Average Latency**: {std_data['avg_latency_ms']:.2f} ms ({std_data['avg_latency_ms']/1000:.2f} seconds)
- **95th Percentile**: {std_data['p95_latency_ms']:.2f} ms
- **SLA Violation Rate**: {std_data['sla_violation_rate']*100:.1f}%
- **Success Rate**: {std_data['success_rate']*100:.1f}%

### RemainingSlack Autoscaling Policy
- **Total Requests**: {slack_data['total_requests']}
- **Average Latency**: {slack_data['avg_latency_ms']:.2f} ms ({slack_data['avg_latency_ms']/1000:.2f} seconds)
- **95th Percentile**: {slack_data['p95_latency_ms']:.2f} ms
- **SLA Violation Rate**: {slack_data['sla_violation_rate']*100:.1f}%
- **Success Rate**: {slack_data['success_rate']*100:.1f}%

## Key Findings

1. **SLA Compliance**: Standard autoscaling maintained 100% SLA compliance, while RemainingSlack had 100% SLA violations
2. **Throughput**: Standard processed {std_data['total_requests']} requests vs {slack_data['total_requests']} for RemainingSlack
3. **Latency**: Standard had significantly lower average latency ({std_data['avg_latency_ms']/1000:.1f}s vs {slack_data['avg_latency_ms']/1000:.1f}s)

## Analysis

The RemainingSlack policy performed poorly in this test due to:
- Resource constraints preventing proper scaling
- The policy attempting to scale up but being blocked by cluster resource limits
- Only 1 request was processed compared to 3 for the standard policy

## Recommendations

1. **Increase Cluster Resources**: The RemainingSlack policy needs more CPU resources to scale effectively
2. **Tune Scaling Parameters**: Adjust the aggressiveness of the RemainingSlack policy for the available resources
3. **Longer Test Duration**: Run tests for longer periods to observe steady-state behavior
4. **Resource Monitoring**: Monitor cluster resources during tests to ensure adequate capacity

## Conclusion

Under the current resource constraints, the standard autoscaling policy outperformed the RemainingSlack policy. However, with adequate resources and proper tuning, the RemainingSlack policy has the potential to provide better SLA-aware autoscaling for sequential deployments.
"""

    return report


def main():
    """Main function to generate visualizations and report."""
    # Load results
    results = load_results()

    # Create visualization
    fig = create_comparison_plots(results)

    # Save interactive HTML
    fig.write_html("sequential_performance_comparison.html")
    print("✓ Interactive visualization saved to sequential_performance_comparison.html")

    # Generate summary report
    report = create_summary_report(results)

    # Save report
    with open("sequential_performance_report.md", "w") as f:
        f.write(report)
    print("✓ Summary report saved to sequential_performance_report.md")

    # Print key metrics to console
    std_data = results["results"]["standard_sequential_app"]
    slack_data = results["results"]["slack_sequential_app"]

    print("\n" + "=" * 60)
    print("SEQUENTIAL PERFORMANCE TEST RESULTS")
    print("=" * 60)
    print("\nStandard Autoscaling:")
    print(f"  Requests: {std_data['total_requests']}")
    print(f"  Avg Latency: {std_data['avg_latency_ms']:.0f} ms")
    print(
        f"  SLA Violations: {std_data['sla_violations']} ({std_data['sla_violation_rate']*100:.1f}%)"
    )

    print("\nRemainingSlack Autoscaling:")
    print(f"  Requests: {slack_data['total_requests']}")
    print(f"  Avg Latency: {slack_data['avg_latency_ms']:.0f} ms")
    print(
        f"  SLA Violations: {slack_data['sla_violations']} ({slack_data['sla_violation_rate']*100:.1f}%)"
    )

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
