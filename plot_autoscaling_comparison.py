import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import glob
import numpy as np

# Load all result files from sweep_results directory
result_files = glob.glob('sweep_results/iteration_*.json')
if not result_files:
    # Fallback to current directory if sweep_results doesn't exist
    result_files = glob.glob('sequential_load_test_sweep_results_*.json')

if not result_files:
    raise FileNotFoundError("No result files found. Please run the sweep test first.")

print(f"Found {len(result_files)} result files:")
for f in result_files:
    print(f"  - {f}")

# Collect data from all iterations
all_data = []
for file_path in result_files:
    with open(file_path, 'r') as f:
        data = json.load(f)
        all_data.append(data)

# Extract the common rates (should be the same across all files)
rates = all_data[0]['test_config']['rates']

# Collect data for each metric by rate and policy
standard_avg_latency = {rate: [] for rate in rates}
standard_p95_latency = {rate: [] for rate in rates}
standard_sla_violation = {rate: [] for rate in rates}
slack_avg_latency = {rate: [] for rate in rates}
slack_p95_latency = {rate: [] for rate in rates}
slack_sla_violation = {rate: [] for rate in rates}

# Extract data from each iteration
for data in all_data:
    summary = data['summary']
    latency_trends = summary['latency_trends']
    sla_violation_trends = summary['sla_violation_trends']

    # Create dictionaries for quick lookups by rate
    std_latency_by_rate = {item['rate']: item for item in latency_trends['standard']}
    slack_latency_by_rate = {item['rate']: item for item in latency_trends['slack']}
    std_sla_by_rate = {item['rate']: item for item in sla_violation_trends['standard']}
    slack_sla_by_rate = {item['rate']: item for item in sla_violation_trends['slack']}

    # Extract data for each rate
    for rate in rates:
        std_latency = std_latency_by_rate.get(rate)
        slack_latency = slack_latency_by_rate.get(rate)
        std_sla = std_sla_by_rate.get(rate)
        slack_sla = slack_sla_by_rate.get(rate)

        if std_latency and std_sla:
            standard_avg_latency[rate].append(std_latency['avg_latency_ms'])
            standard_p95_latency[rate].append(std_latency['p95_latency_ms'])
            standard_sla_violation[rate].append(std_sla['sla_violation_rate'])

        if slack_latency and slack_sla:
            slack_avg_latency[rate].append(slack_latency['avg_latency_ms'])
            slack_p95_latency[rate].append(slack_latency['p95_latency_ms'])
            slack_sla_violation[rate].append(slack_sla['sla_violation_rate'])

print(f"\nData collected for {len(rates)} rates with {len(all_data)} iterations each")

# Create subplots
fig = make_subplots(
    rows=2, cols=2,
    subplot_titles=('Average Latency (ms)', 'P95 Latency (ms)', 'SLA Violation Rate', 'Improvement Percentages'),
    specs=[[{"secondary_y": False}, {"secondary_y": False}],
           [{"secondary_y": False}, {"type": "bar"}]]
)

# Create boxplot data for average latency
avg_latency_x_standard = []
avg_latency_y_standard = []
avg_latency_x_slack = []
avg_latency_y_slack = []

for rate in sorted(rates):
    # Standard data
    avg_latency_x_standard.extend([str(rate)] * len(standard_avg_latency[rate]))
    avg_latency_y_standard.extend(standard_avg_latency[rate])

    # Slack data
    avg_latency_x_slack.extend([str(rate)] * len(slack_avg_latency[rate]))
    avg_latency_y_slack.extend(slack_avg_latency[rate])

# Create grouped boxplot for average latency
fig.add_trace(
    go.Box(
        x=avg_latency_x_standard,
        y=avg_latency_y_standard,
        name='Standard (Queue Length)',
        marker_color='blue',
        boxpoints='outliers',
        jitter=0.3,
        pointpos=-1.8
    ),
    row=1, col=1
)

fig.add_trace(
    go.Box(
        x=avg_latency_x_slack,
        y=avg_latency_y_slack,
        name='Slack (SLA-aware)',
        marker_color='red',
        boxpoints='outliers',
        jitter=0.3,
        pointpos=-1.8,
        showlegend=False
    ),
    row=1, col=1
)

# Create boxplot data for P95 latency
p95_latency_x_standard = []
p95_latency_y_standard = []
p95_latency_x_slack = []
p95_latency_y_slack = []

for rate in sorted(rates):
    # Standard data
    p95_latency_x_standard.extend([str(rate)] * len(standard_p95_latency[rate]))
    p95_latency_y_standard.extend(standard_p95_latency[rate])

    # Slack data
    p95_latency_x_slack.extend([str(rate)] * len(slack_p95_latency[rate]))
    p95_latency_y_slack.extend(slack_p95_latency[rate])

fig.add_trace(
    go.Box(
        x=p95_latency_x_standard,
        y=p95_latency_y_standard,
        name='Standard (Queue Length)',
        marker_color='blue',
        boxpoints='outliers',
        jitter=0.3,
        pointpos=-1.8,
        showlegend=False
    ),
    row=1, col=2
)

fig.add_trace(
    go.Box(
        x=p95_latency_x_slack,
        y=p95_latency_y_slack,
        name='Slack (SLA-aware)',
        marker_color='red',
        boxpoints='outliers',
        jitter=0.3,
        pointpos=-1.8,
        showlegend=False
    ),
    row=1, col=2
)

# Create boxplot data for SLA violation
sla_x_standard = []
sla_y_standard = []
sla_x_slack = []
sla_y_slack = []

for rate in sorted(rates):
    # Standard data
    sla_x_standard.extend([str(rate)] * len(standard_sla_violation[rate]))
    sla_y_standard.extend(standard_sla_violation[rate])

    # Slack data
    sla_x_slack.extend([str(rate)] * len(slack_sla_violation[rate]))
    sla_y_slack.extend(slack_sla_violation[rate])

fig.add_trace(
    go.Box(
        x=sla_x_standard,
        y=sla_y_standard,
        name='Standard (Queue Length)',
        marker_color='blue',
        boxpoints='outliers',
        jitter=0.3,
        pointpos=-1.8,
        showlegend=False
    ),
    row=2, col=1
)

fig.add_trace(
    go.Box(
        x=sla_x_slack,
        y=sla_y_slack,
        name='Slack (SLA-aware)',
        marker_color='red',
        boxpoints='outliers',
        jitter=0.3,
        pointpos=-1.8,
        showlegend=False
    ),
    row=2, col=1
)

# Calculate improvement percentages
rate_comparisons_all = {}
for data in all_data:
    rate_comparisons = data['summary']['rate_comparisons']
    for rate, comparison in rate_comparisons.items():
        if rate not in rate_comparisons_all:
            rate_comparisons_all[rate] = []
        rate_comparisons_all[rate].append({
            'sla_improvement': comparison['sla_improvement_percent'],
            'latency_improvement': comparison['latency_improvement_percent']
        })

improvement_rates = sorted(rates, key=float)
avg_sla_improvements = []
avg_latency_improvements = []

for rate in improvement_rates:
    improvements = rate_comparisons_all.get(rate, [])
    if improvements:
        sla_values = [imp['sla_improvement'] for imp in improvements if imp['sla_improvement'] is not None]
        latency_values = [imp['latency_improvement'] for imp in improvements if imp['latency_improvement'] is not None]

        avg_sla = np.mean(sla_values) if sla_values else 0
        avg_latency = np.mean(latency_values) if latency_values else 0
    else:
        avg_sla = 0
        avg_latency = 0

    avg_sla_improvements.append(avg_sla)
    avg_latency_improvements.append(avg_latency)

# Add improvement percentage bars
fig.add_trace(
    go.Bar(
        x=improvement_rates,
        y=avg_sla_improvements,
        name='Avg SLA Improvement %',
        marker_color='green',
        opacity=0.7
    ),
    row=2, col=2
)
fig.add_trace(
    go.Bar(
        x=improvement_rates,
        y=avg_latency_improvements,
        name='Avg Latency Improvement %',
        marker_color='orange',
        opacity=0.7
    ),
    row=2, col=2
)

# Update layout
fig.update_layout(
    title='Autoscaling Policy Comparison: Standard (Queue Length) vs Slack (SLA-aware)',
    height=800,
    showlegend=True,
    legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)'),
    boxmode='group'
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
try:
    fig.write_image("autoscaling_comparison.png", width=1200, height=800)
    print("Boxplot saved as 'autoscaling_comparison.html' and 'autoscaling_comparison.png'")
except Exception as e:
    print(f"Could not save PNG image (install kaleido for PNG support): {e}")
    print("Boxplot saved as 'autoscaling_comparison.html'")

# Create individual boxplots for better visibility
# 1. Average Latency Comparison
fig1 = go.Figure()

# Add standard data
fig1.add_trace(
    go.Box(
        x=avg_latency_x_standard,
        y=avg_latency_y_standard,
        name='Standard (Queue Length)',
        marker_color='blue',
        boxpoints='outliers',
        jitter=0.3,
        pointpos=-1.8
    )
)

# Add slack data
fig1.add_trace(
    go.Box(
        x=avg_latency_x_slack,
        y=avg_latency_y_slack,
        name='Slack (SLA-aware)',
        marker_color='red',
        boxpoints='outliers',
        jitter=0.3,
        pointpos=-1.8
    )
)

fig1.update_layout(
    title='Average Latency Comparison',
    xaxis_title='Request Rate (req/s)',
    yaxis_title='Average Latency (ms)',
    height=600,
    boxmode='group',
    showlegend=True
)
fig1.write_html("avg_latency_comparison.html")
try:
    fig1.write_image("avg_latency_comparison.png", width=800, height=600)
except Exception as e:
    print(f"Could not save avg_latency_comparison.png: {e}")

# 2. P95 Latency Comparison
fig2 = go.Figure()

# Add standard data
fig2.add_trace(
    go.Box(
        x=p95_latency_x_standard,
        y=p95_latency_y_standard,
        name='Standard (Queue Length)',
        marker_color='blue',
        boxpoints='outliers',
        jitter=0.3,
        pointpos=-1.8
    )
)

# Add slack data
fig2.add_trace(
    go.Box(
        x=p95_latency_x_slack,
        y=p95_latency_y_slack,
        name='Slack (SLA-aware)',
        marker_color='red',
        boxpoints='outliers',
        jitter=0.3,
        pointpos=-1.8,
        showlegend=False
    )
)

fig2.update_layout(
    title='P95 Latency Comparison',
    xaxis_title='Request Rate (req/s)',
    yaxis_title='P95 Latency (ms)',
    height=600,
    boxmode='group',
    showlegend=True
)
fig2.write_html("p95_latency_comparison.html")
try:
    fig2.write_image("p95_latency_comparison.png", width=800, height=600)
except Exception as e:
    print(f"Could not save p95_latency_comparison.png: {e}")

# 3. SLA Violation Rate Comparison
fig3 = go.Figure()

# Add standard data
fig3.add_trace(
    go.Box(
        x=sla_x_standard,
        y=sla_y_standard,
        name='Standard (Queue Length)',
        marker_color='blue',
        boxpoints='outliers',
        jitter=0.3,
        pointpos=-1.8
    )
)

# Add slack data
fig3.add_trace(
    go.Box(
        x=sla_x_slack,
        y=sla_y_slack,
        name='Slack (SLA-aware)',
        marker_color='red',
        boxpoints='outliers',
        jitter=0.3,
        pointpos=-1.8,
        showlegend=False
    )
)

fig3.update_layout(
    title='SLA Violation Rate Comparison',
    xaxis_title='Request Rate (req/s)',
    yaxis_title='SLA Violation Rate',
    height=600,
    boxmode='group',
    showlegend=True
)
fig3.write_html("sla_violation_comparison.html")
try:
    fig3.write_image("sla_violation_comparison.png", width=800, height=600)
except Exception as e:
    print(f"Could not save sla_violation_comparison.png: {e}")

print("Individual boxplots saved:")
print("- avg_latency_comparison.html")
print("- p95_latency_comparison.html")
print("- sla_violation_comparison.html")

# Print summary statistics
print(f"\n{'='*70}")
print("SUMMARY STATISTICS ACROSS ALL ITERATIONS")
print(f"{'='*70}")

for rate in sorted(rates, key=float):
    print(f"\nRate: {rate} req/s")
    print("-" * 40)

    # Standard autoscaling stats
    std_avg = standard_avg_latency.get(rate, [])
    std_p95 = standard_p95_latency.get(rate, [])
    std_sla = standard_sla_violation.get(rate, [])

    print(f"Standard Autoscaling:")
    if std_avg:
        print(f"  Avg Latency: {np.mean(std_avg):.2f} ± {np.std(std_avg):.2f} ms")
    else:
        print(f"  Avg Latency: No data")

    if std_p95:
        print(f"  P95 Latency: {np.mean(std_p95):.2f} ± {np.std(std_p95):.2f} ms")
    else:
        print(f"  P95 Latency: No data")

    if std_sla:
        print(f"  SLA Violation: {np.mean(std_sla)*100:.2f} ± {np.std(std_sla)*100:.2f}%")
    else:
        print(f"  SLA Violation: No data")

    # Slack autoscaling stats
    slack_avg = slack_avg_latency.get(rate, [])
    slack_p95 = slack_p95_latency.get(rate, [])
    slack_sla = slack_sla_violation.get(rate, [])

    print(f"Slack Autoscaling:")
    if slack_avg:
        print(f"  Avg Latency: {np.mean(slack_avg):.2f} ± {np.std(slack_avg):.2f} ms")
    else:
        print(f"  Avg Latency: No data")

    if slack_p95:
        print(f"  P95 Latency: {np.mean(slack_p95):.2f} ± {np.std(slack_p95):.2f} ms")
    else:
        print(f"  P95 Latency: No data")

    if slack_sla:
        print(f"  SLA Violation: {np.mean(slack_sla)*100:.2f} ± {np.std(slack_sla)*100:.2f}%")
    else:
        print(f"  SLA Violation: No data")