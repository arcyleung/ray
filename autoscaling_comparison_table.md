# Autoscaling Policies Comparison

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