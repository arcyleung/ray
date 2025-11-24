# Sequential Performance Load Test Sweep Guide

## Overview
This guide explains how to use the improved benchmark load test script that sweeps a range of loads and records SLA violation comparisons between Standard and RemainingSlack autoscaling policies.

## Files Created

1. **Main Script**: [`python/ray/serve/tests/run_sequential_performance_test_sweep.py`](python/ray/serve/tests/run_sequential_performance_test_sweep.py)
   - Enhanced version of the original test script
   - Sweeps multiple request rates automatically
   - Records detailed SLA violation comparisons

2. **Wrapper Script**: [`run_sweep_test.sh`](run_sweep_test.sh)
   - Simple script to run the sweep test with default parameters
   - Tests rates from 10 to 30 in increments of 5

## Quick Start

### Option 1: Use the Wrapper Script (Recommended)
```bash
# Make the script executable (if not already done)
chmod +x run_sweep_test.sh

# Run the sweep test
./run_sweep_test.sh
```

### Option 2: Use the Python Script Directly
```bash
# Run with default parameters (rates 10-30, step 5, duration 60s)
python python/ray/serve/tests/run_sequential_performance_test_sweep.py

# Or specify custom parameters
python python/ray/serve/tests/run_sequential_performance_test_sweep.py \
    --min-rate 5 \
    --max-rate 50 \
    --rate-step 5 \
    --duration 30
```

## Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--min-rate` | Minimum request rate | 10.0 |
| `--max-rate` | Maximum request rate | 30.0 |
| `--rate-step` | Request rate increment | 5.0 |
| `--duration` | Test duration per rate (seconds) | 60.0 |
| `--rates` | Comma-separated list of specific rates | (uses min/max/step) |

## Examples

### Test Specific Rates
```bash
python python/ray/serve/tests/run_sequential_performance_test_sweep.py \
    --rates "10,15,20,25,30"
```

### Test a Wider Range
```bash
python python/ray/serve/tests/run_sequential_performance_test_sweep.py \
    --min-rate 5 \
    --max-rate 50 \
    --rate-step 5 \
    --duration 30
```

### Quick Test (Shorter Duration)
```bash
python python/ray/serve/tests/run_sequential_performance_test_sweep.py \
    --duration 30
```

## Prerequisites

Before running the sweep test, make sure:

1. **Ray and Serve are running**:
   ```bash
   ray start --head
   ```

2. **Applications are deployed**:
   ```bash
   serve deploy python/ray/serve/tests/sequential_performance_load_test_config.yaml
   ```

3. **Resource requirements are set**:
   - All deployments should have `ray_actor_options={"num_cpus": 0.01}` set
   - This is already configured in the updated files

## Output

### Console Output
The script provides:
- Real-time progress for each rate being tested
- Detailed metrics for each application at each rate
- Comparison summary for each rate
- Overall summary table showing all rates

### JSON Output
Results are saved to a timestamped JSON file: `sequential_load_test_sweep_results_[timestamp].json`

The JSON contains:
- Test configuration
- Summary statistics
- Detailed results for each rate
- SLA violation trends
- Latency trends

## Understanding the Results

### Key Metrics
- **SLA Violation Rate**: Percentage of requests exceeding 20 seconds
- **Average Latency**: Mean end-to-end latency
- **95th Percentile**: Latency at the 95th percentile
- **Success Rate**: Percentage of successful requests

### Comparison Summary
The script automatically determines which policy performs better at each rate:
- **Winner determination**: Based on lower SLA violation rate, then lower latency
- **Improvement percentage**: How much better the winning policy performed
- **Overall winner**: Policy that wins at the most rates

### Sample Output
```
Rate     Std SLA%  Slack SLA%  Improvement  Winner    
------------------------------------------------------------
10       0.00      0.00       0.00         tie       
15       5.20      2.10       59.62        slack     
20       15.30     8.70       43.14        slack     
25       28.90     18.20      37.02        slack     
30       45.60     32.40      28.95        slack     
------------------------------------------------------------
Overall: Slack wins 4, Standard wins 0, Ties 1
Overall winner: RemainingSlack Autoscaling
```

## Troubleshooting

### Common Issues

1. **"Error getting deployment handles"**
   - Make sure applications are deployed with the config file
   - Check that Ray and Serve are running

2. **High failure rates**
   - Check if the cluster has sufficient resources
   - Verify the deployments are healthy

3. **Inconsistent results**
   - Ensure the system has time to stabilize between rate changes
   - Check for other processes consuming resources

### Tips

1. **Start with shorter durations** (30 seconds) to verify everything works
2. **Use specific rates** if you're interested in particular load points
3. **Monitor system resources** during the test
4. **Save results** with different filenames for comparison

## Advanced Usage

### Custom Rate Patterns
```bash
# Test exponential growth
python python/ray/serve/tests/run_sequential_performance_test_sweep.py \
    --rates "5,10,20,40,80"

# Test specific problematic rates
python python/ray/serve/tests/run_sequential_performance_test_sweep.py \
    --rates "18,22,26"
```

### Post-Processing
The JSON output can be processed to generate:
- Performance graphs
- Trend analysis
- Statistical reports

Example Python snippet to extract SLA trends:
```python
import json

with open("sequential_load_test_sweep_results_*.json", "r") as f:
    data = json.load(f)

sla_trends = data["summary"]["sla_violation_trends"]
for trend in sla_trends["slack"]:
    rate = trend["rate"]
    sla_rate = trend["sla_violation_rate"] * 100
    print(f"Rate {rate}: SLA violation {sla_rate:.2f}%")