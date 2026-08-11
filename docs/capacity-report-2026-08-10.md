# Capacity benchmark report

> Evidence class: **measured** unless a paragraph explicitly says calculated or projected.

## Environment

- Host: 16 logical CPUs, 30.63 GiB RAM, x86_64
- Docker: 29.6.1
- Stack: `job-seeker-copilot-e2e` with fixture providers
- Browser processes run on the host and are not included in per-container memory figures.

## Measured profiles

| Profile | Active | Passed | Failed | Responses | App errors | Sessions/s | Session p95 | Response p50 | Response p95 | Response p99 | Avg CPU | Peak CPU | Idle memory | Peak memory |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| idle | 0 | 0 | 0 | 0 | 0 | 0.000 | — | — | — | — | 10.52% | 27.47% | 9.71 GiB | 9.74 GiB |
| single-user | 1 | 1 | 0 | 54 | 4 | 0.144 | 6945 ms | 9 ms | 89 ms | — | 136.50% | 262.94% | 9.84 GiB | 9.89 GiB |
| concurrent-5 | 5 | 5 | 0 | 283 | 20 | 0.569 | 8767 ms | 19 ms | 164 ms | 198 ms | 30.40% | 62.48% | 9.87 GiB | 9.91 GiB |
| concurrent-10 | 10 | 10 | 0 | 567 | 40 | 0.613 | 16285 ms | 36 ms | 273 ms | 384 ms | 175.70% | 651.73% | 9.92 GiB | 9.96 GiB |
| concurrent-25 | 25 | 0 | 25 | 1266 | 141 | 0.483 | 50452 ms | 43 ms | 1110 ms | 4815 ms | 306.62% | 1214.41% | 8.21 GiB | 8.71 GiB |

## Per-service measurements

Container measurements below are from `concurrent-25`, the highest attempted concurrency point.

| Container | Avg CPU | Peak CPU | First-sample memory | Peak memory |
|---|---:|---:|---:|---:|
| `job-seeker-copilot-e2e-clamav-1` | 0.41% | 4.86% | 0.94 GiB | 0.94 GiB |
| `job-seeker-copilot-e2e-application-tracker-service-1` | 48.40% | 333.04% | 0.50 GiB | 0.57 GiB |
| `job-seeker-copilot-e2e-user-profile-service-1` | 46.59% | 229.22% | 0.41 GiB | 0.56 GiB |
| `job-seeker-copilot-e2e-job-service-1` | 25.25% | 153.78% | 0.46 GiB | 0.53 GiB |
| `job-seeker-copilot-e2e-document-store-service-1` | 34.45% | 223.85% | 0.50 GiB | 0.53 GiB |
| `job-seeker-copilot-e2e-authentication-service-1` | 19.42% | 94.36% | 0.39 GiB | 0.45 GiB |
| `job-seeker-copilot-e2e-payment-service-1` | 1.75% | 17.59% | 0.36 GiB | 0.36 GiB |
| `job-seeker-copilot-e2e-reporting-service-1` | 23.74% | 136.69% | 0.18 GiB | 0.28 GiB |
| `job-seeker-copilot-e2e-reporting-gateway-1` | 11.56% | 58.95% | 0.19 GiB | 0.27 GiB |
| `job-seeker-copilot-e2e-location-gateway-1` | 0.19% | 0.24% | 0.26 GiB | 0.26 GiB |
| `job-seeker-copilot-e2e-user-management-gateway-1` | 34.17% | 141.82% | 0.21 GiB | 0.26 GiB |
| `job-seeker-copilot-e2e-document-generation-gateway-1` | 0.68% | 6.04% | 0.25 GiB | 0.25 GiB |
| `job-seeker-copilot-e2e-job-finder-gateway-1` | 18.16% | 82.17% | 0.20 GiB | 0.25 GiB |
| `job-seeker-copilot-e2e-google-maps-gateway-1` | 0.20% | 0.36% | 0.23 GiB | 0.23 GiB |
| `job-seeker-copilot-e2e-system-data-service-1` | 3.70% | 41.60% | 0.22 GiB | 0.22 GiB |
| `job-seeker-copilot-e2e-location-service-1` | 0.21% | 0.36% | 0.22 GiB | 0.22 GiB |
| `job-seeker-copilot-e2e-postcode-io-gateway-1` | 0.19% | 0.26% | 0.22 GiB | 0.22 GiB |
| `job-seeker-copilot-e2e-llm-gateway-1` | 0.19% | 0.24% | 0.21 GiB | 0.21 GiB |
| `job-seeker-copilot-e2e-stripe-gateway-1` | 0.26% | 0.55% | 0.21 GiB | 0.21 GiB |
| `job-seeker-copilot-e2e-cv-cover-letter-service-1` | 0.57% | 4.39% | 0.20 GiB | 0.20 GiB |
| `job-seeker-copilot-e2e-apprenticeships-gateway-1` | 3.80% | 43.41% | 0.19 GiB | 0.19 GiB |
| `job-seeker-copilot-e2e-reed-gateway-1` | 5.76% | 66.63% | 0.18 GiB | 0.19 GiB |
| `job-seeker-copilot-e2e-payment-gateway-1` | 0.59% | 4.63% | 0.19 GiB | 0.19 GiB |
| `job-seeker-copilot-e2e-adzuna-gateway-1` | 0.20% | 0.29% | 0.19 GiB | 0.19 GiB |
| `job-seeker-copilot-e2e-document-export-service-1` | 0.19% | 0.27% | 0.19 GiB | 0.19 GiB |
| `job-seeker-copilot-e2e-nhs-jobs-gateway-1` | 1.60% | 13.79% | 0.19 GiB | 0.19 GiB |
| `job-seeker-copilot-e2e-jsearch-gateway-1` | 0.20% | 0.34% | 0.18 GiB | 0.18 GiB |
| `job-seeker-copilot-e2e-job-matching-service-1` | 6.37% | 47.50% | 0.18 GiB | 0.18 GiB |
| `job-seeker-copilot-e2e-job-seeker-copilot-client-1` | 6.78% | 28.61% | 0.10 GiB | 0.10 GiB |
| `job-seeker-copilot-e2e-authentication-postgres-1` | 0.78% | 4.22% | 0.06 GiB | 0.06 GiB |
| `job-seeker-copilot-e2e-application-tracker-postgres-1` | 3.41% | 13.42% | 0.04 GiB | 0.05 GiB |
| `job-seeker-copilot-e2e-user-profile-postgres-1` | 3.02% | 15.55% | 0.04 GiB | 0.05 GiB |
| `job-seeker-copilot-e2e-document-store-postgres-1` | 1.47% | 4.66% | 0.04 GiB | 0.04 GiB |
| `job-seeker-copilot-e2e-payment-postgres-1` | 0.76% | 4.10% | 0.04 GiB | 0.04 GiB |
| `job-seeker-copilot-e2e-job-service-postgres-1` | 0.62% | 4.16% | 0.04 GiB | 0.04 GiB |
| `job-seeker-copilot-e2e-document-generation-postgres-1` | 0.99% | 4.32% | 0.04 GiB | 0.04 GiB |

## Bottleneck indicators

Highest peak memory:

- `job-seeker-copilot-e2e-clamav-1`: 0.94 GiB
- `job-seeker-copilot-e2e-application-tracker-service-1`: 0.57 GiB
- `job-seeker-copilot-e2e-user-profile-service-1`: 0.56 GiB
- `job-seeker-copilot-e2e-job-service-1`: 0.53 GiB
- `job-seeker-copilot-e2e-document-store-service-1`: 0.53 GiB
- `job-seeker-copilot-e2e-authentication-service-1`: 0.45 GiB
- `job-seeker-copilot-e2e-payment-service-1`: 0.36 GiB
- `job-seeker-copilot-e2e-reporting-service-1`: 0.28 GiB
- `job-seeker-copilot-e2e-reporting-gateway-1`: 0.27 GiB
- `job-seeker-copilot-e2e-location-gateway-1`: 0.26 GiB

Highest peak CPU:

- `job-seeker-copilot-e2e-application-tracker-service-1`: 333.04%
- `job-seeker-copilot-e2e-user-profile-service-1`: 229.22%
- `job-seeker-copilot-e2e-document-store-service-1`: 223.85%
- `job-seeker-copilot-e2e-job-service-1`: 153.78%
- `job-seeker-copilot-e2e-user-management-gateway-1`: 141.82%
- `job-seeker-copilot-e2e-reporting-service-1`: 136.69%
- `job-seeker-copilot-e2e-authentication-service-1`: 94.36%
- `job-seeker-copilot-e2e-job-finder-gateway-1`: 82.17%
- `job-seeker-copilot-e2e-reed-gateway-1`: 66.63%
- `job-seeker-copilot-e2e-reporting-gateway-1`: 58.95%

## Stability and variable consumption

- Restarts across profiles: 0
- OOM-killed containers: 0
- Paid provider, Google Maps and LLM consumption: measured zero because this benchmark is fixture-only.
- Highest fully successful measured concurrency: 10 active sessions.
- Highest attempted concurrency: 25 active sessions; 25 sessions failed.

## Interpretation boundary

These runs measure the listed concurrency points only. They do not establish capacity above the largest successful run. Any AWS sizing or higher-user figures derived from them must be labelled **calculated** or **projected**, not benchmark results.

The later real-world profile audit added seven deterministic persona shapes but
did not rerun or reinterpret these historical workload measurements. The
highest evidenced concurrency therefore remains 10 successful active sessions;
the 25-session attempt remains a failure.
