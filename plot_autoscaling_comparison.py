import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px

# Load the data
with open('sequential_load_test_sweep_results_1763763808.json', 'r') as f:
    data = json.load(f)

# Extract the relevant data
rates = data['test_config']['rates']
summary = data['summary']

# Extract latency trends
latency_trends = summary['latency_trends']
sla_violation_trends = summary['sla_violation_trends']

# Prepare data for plotting
standard_avg_latency = [item['avg_latency_ms'] for item in latency_trends['standard']]
slack_avg_latency = [item['avg_latency_ms'] for item in latency_trends['slack']]

standard_p95_latency = [item['p95_latency_ms'] for item in latency_trends['standard']]
slack_p95_latency = [item['p95_latency_ms'] for item in latency_trends['slack']]

standard_sla_violation = [item['sla_violation_rate'] for item in sla_violation_trends['standard']]
slack_sla_violation = [item['sla_violation_rate'] for item in sla_violation_trends['slack']]

# Create subplots
fig = make_subplots(
    rows=2, cols=2,
    subplot_titles=('Average Latency (ms)', 'P95 Latency (ms)', 'SLA Violation Rate', 'Improvement Percentages'),
    specs=[[{"secondary_y": False}, {"secondary_y": False}],
           [{"secondary_y": False}, {"type": "bar"}]]
)

# Plot Average Latency
fig.add_trace(
    go.Scatter(x=rates, y=standard_avg_latency, name='Standard (Queue Length)',
               line=dict(color='blue', width=3), marker=dict(size=8)),
    row=1, col=1
)
fig.add_trace(
    go.Scatter(x=rates, y=slack_avg_latency, name='Slack (SLA-aware)',
               line=dict(color='red', width=3), marker=dict(size=8)),
    row=1, col=1
)

# Plot P95 Latency
fig.add_trace(
    go.Scatter(x=rates, y=standard_p95_latency, name='Standard (Queue Length)',
               line=dict(color='blue', width=3), marker=dict(size=8), showlegend=False),
    row=1, col=2
)
fig.add_trace(
    go.Scatter(x=rates, y=slack_p95_latency, name='Slack (SLA-aware)',
               line=dict(color='red', width=3), marker=dict(size=8), showlegend=False),
    row=1, col=2
)

# Plot SLA Violation Rate
fig.add_trace(
    go.Scatter(x=rates, y=standard_sla_violation, name='Standard (Queue Length)',
               line=dict(color='blue', width=3), marker=dict(size=8), showlegend=False),
    row=2, col=1
)
fig.add_trace(
    go.Scatter(x=rates, y=slack_sla_violation, name='Slack (SLA-aware)',
               line=dict(color='red', width=3), marker=dict(size=8), showlegend=False),
    row=2, col=1
)

# Plot Improvement Percentages
rate_comparisons = summary['rate_comparisons']
improvement_rates = list(rate_comparisons.keys())
sla_improvements = [rate_comparisons[rate]['sla_improvement_percent'] for rate in improvement_rates]
latency_improvements = [rate_comparisons[rate]['latency_improvement_percent'] for rate in improvement_rates]

fig.add_trace(
    go.Bar(x=improvement_rates, y=sla_improvements, name='SLA Improvement %',
           marker_color='green', opacity=0.7),
    row=2, col=2
)
fig.add_trace(
    go.Bar(x=improvement_rates, y=latency_improvements, name='Latency Improvement %',
           marker_color='orange', opacity=0.7),
    row=2, col=2
)

# Update layout
fig.update_layout(
    title='Autoscaling Policy Comparison: Standard (Queue Length) vs Slack (SLA-aware)',
    height=800,
    showlegend=True,
    legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)')
)

# Update x and y axis labels
fig.update_xaxes(title_text="Request Rate (req/s)", row=1, col=1)
fig.update_xaxes(title_text="Request Rate (req/s)", row=1, col=2)
fig.update_xaxes(title_text="Request Rate (req/s)", row=2, col=1)
fig.update_xaxes(title_text="Request Rate (req/s)", row=2, col=2)

fig.update_yaxes(title_text="Latency (ms)", row=1, col=1)
fig.update_yaxes(title_text="Latency (ms)", row=1, col=2)
fig.update_yaxes(title_text="SLA Violation Rate", row=2, col=1)
fig.update_yaxes(title_text="Improvement (%)", row=2, col=2)

# Save the plot
fig.write_html("autoscaling_comparison.html")
fig.write_image("autoscaling_comparison.png", width=1200, height=800)

print("Plots saved as 'autoscaling_comparison.html' and 'autoscaling_comparison.png'")

# Create individual plots for better visibility
# 1. Average Latency Comparison
fig1 = go.Figure()
fig1.add_trace(go.Scatter(x=rates, y=standard_avg_latency, name='Standard (Queue Length)',
                         line=dict(color='blue', width=3), marker=dict(size=10)))
fig1.add_trace(go.Scatter(x=rates, y=slack_avg_latency, name='Slack (SLA-aware)',
                         line=dict(color='red', width=3), marker=dict(size=10)))
fig1.update_layout(title='Average Latency Comparison', xaxis_title='Request Rate (req/s)',
                  yaxis_title='Average Latency (ms)', height=500)
fig1.write_html("avg_latency_comparison.html")
fig1.write_image("avg_latency_comparison.png", width=800, height=500)

# 2. P95 Latency Comparison
fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=rates, y=standard_p95_latency, name='Standard (Queue Length)',
                         line=dict(color='blue', width=3), marker=dict(size=10)))
fig2.add_trace(go.Scatter(x=rates, y=slack_p95_latency, name='Slack (SLA-aware)',
                         line=dict(color='red', width=3), marker=dict(size=10)))
fig2.update_layout(title='P95 Latency Comparison', xaxis_title='Request Rate (req/s)',
                  yaxis_title='P95 Latency (ms)', height=500)
fig2.write_html("p95_latency_comparison.html")
fig2.write_image("p95_latency_comparison.png", width=800, height=500)

# 3. SLA Violation Rate Comparison
fig3 = go.Figure()
fig3.add_trace(go.Scatter(x=rates, y=standard_sla_violation, name='Standard (Queue Length)',
                         line=dict(color='blue', width=3), marker=dict(size=10)))
fig3.add_trace(go.Scatter(x=rates, y=slack_sla_violation, name='Slack (SLA-aware)',
                         line=dict(color='red', width=3), marker=dict(size=10)))
fig3.update_layout(title='SLA Violation Rate Comparison', xaxis_title='Request Rate (req/s)',
                  yaxis_title='SLA Violation Rate', height=500)
fig3.write_html("sla_violation_comparison.html")
fig3.write_image("sla_violation_comparison.png", width=800, height=500)

print("Individual plots saved:")
print("- avg_latency_comparison.html/png")
print("- p95_latency_comparison.html/png")
print("- sla_violation_comparison.html/png")