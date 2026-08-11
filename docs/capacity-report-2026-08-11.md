# Capacity benchmark report

> Evidence class: **measured** unless a paragraph explicitly says calculated or projected.

## Environment

- Host: 16 logical CPUs, 30.63 GiB RAM, x86_64
- Docker: 29.6.1
- Stack: `job-seeker-copilot-e2e` with fixture providers
- Sampler interval: 2 seconds
- Browser processes run on the host and are not included in per-container memory figures.
- Workload: one headless browser per active session signs in, opens DISCOVER, searches the governed nine-job fixture and expands job details; it does not generate documents.
- Safety controls: loopback port 3100 only; real providers and paid AI explicitly disabled; dataset `uk-software-developer-demo` version `1.0.0` reset and verified before each active run.

### Source revisions

The benchmark used the following repository HEADs. `dirty` means the tested working tree also contained coordinated, uncommitted closure changes; the SHA alone is not claimed as a complete build identifier.

| Repository | HEAD | Working tree |
|---|---|---|
| `adzuna-gateway` | `d57fb6c37c34` | clean |
| `application-tracker-service` | `3c8781fb0795` | dirty |
| `apprenticeships-gateway` | `73daae862189` | clean |
| `authentication-service` | `331c01f31a7c` | clean |
| `cv-cover-letter-service` | `990d3922b286` | dirty |
| `document-export-service` | `5de2d563b373` | clean |
| `document-generation-gateway` | `22fa349415ba` | dirty |
| `document-store-service` | `badfd3b418eb` | dirty |
| `e2e` | `541e2b919136` | dirty |
| `google-maps-gateway` | `bd45bda74040` | clean |
| `infrastructure` | `c8a52e4b5b56` | dirty |
| `job-finder-gateway` | `7a8a93126e04` | clean |
| `job-matching-service` | `47826c19a744` | clean |
| `job-seeker-copilot-client` | `6839361353a0` | dirty |
| `job-service` | `1e5d947db50c` | dirty |
| `jsearch-gateway` | `e1ab0efa68e5` | clean |
| `llm-gateway` | `1562213a268d` | clean |
| `location-gateway` | `0805848be15f` | clean |
| `location-service` | `04ccdffe5e95` | clean |
| `nhs-jobs-gateway` | `d27fe8dc8fa6` | clean |
| `payment-gateway` | `8d49a6477c30` | clean |
| `payment-service` | `af48d12dd95e` | clean |
| `postcode-io-gateway` | `48d9e39fb7c2` | clean |
| `reed-gateway` | `518aff9503a4` | clean |
| `reporting-gateway` | `f3f352516510` | clean |
| `reporting-service` | `835f507cb02e` | clean |
| `stripe-gateway` | `d9aa6b338d21` | clean |
| `system-data-service` | `4e3d2e66bffe` | dirty |
| `user-management-gateway` | `9ce00d56946e` | dirty |
| `user-profile-service` | `13ced1c7e913` | clean |

## Measured profiles

| Profile | Active | Passed | Failed | Responses | App errors | Sessions/s | Session p95 | Response p50 | Response p95 | Response p99 | Avg CPU | Peak CPU | Idle memory | Peak memory |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| idle | 0 | 0 | 0 | 0 | 0 | 0.000 | — | — | — | — | 11.33% | 27.83% | 7.82 GiB | 7.83 GiB |
| single-user | 1 | 1 | 0 | 52 | 0 | 0.168 | 5969 ms | 9 ms | 182 ms | — | 163.36% | 317.05% | 7.99 GiB | 8.01 GiB |
| concurrent-5 | 5 | 5 | 0 | 251 | 0 | 0.483 | 10340 ms | 15 ms | 571 ms | 1107 ms | 95.27% | 258.86% | 8.04 GiB | 8.14 GiB |
| concurrent-10 | 10 | 10 | 0 | 507 | 0 | 0.588 | 16995 ms | 26 ms | 709 ms | 970 ms | 206.30% | 782.91% | 8.29 GiB | 8.35 GiB |
| concurrent-15 | 15 | 15 | 0 | 807 | 0 | 0.577 | 25971 ms | 46 ms | 472 ms | 961 ms | 174.33% | 714.42% | 8.34 GiB | 8.42 GiB |
| concurrent-20 | 20 | 20 | 0 | 1131 | 0 | 0.492 | 40432 ms | 63 ms | 609 ms | 2248 ms | 123.86% | 702.47% | 8.54 GiB | 8.66 GiB |
| concurrent-25 | 25 | 25 | 0 | 1414 | 0 | 0.420 | 59449 ms | 71 ms | 546 ms | 1207 ms | 119.62% | 566.73% | 8.63 GiB | 8.64 GiB |

## Per-service measurements

Container measurements below are from `concurrent-25`, the highest attempted concurrency point.

| Container | Avg CPU | Peak CPU | First-sample memory | Peak memory |
|---|---:|---:|---:|---:|
| `job-seeker-copilot-e2e-clamav-1` | 0.60% | 5.32% | 0.95 GiB | 0.95 GiB |
| `job-seeker-copilot-e2e-authentication-service-1` | 15.07% | 76.02% | 0.45 GiB | 0.48 GiB |
| `job-seeker-copilot-e2e-job-service-1` | 6.15% | 34.32% | 0.47 GiB | 0.47 GiB |
| `job-seeker-copilot-e2e-user-profile-service-1` | 14.58% | 66.68% | 0.44 GiB | 0.45 GiB |
| `job-seeker-copilot-e2e-document-store-service-1` | 6.44% | 38.87% | 0.41 GiB | 0.41 GiB |
| `job-seeker-copilot-e2e-application-tracker-service-1` | 19.95% | 89.73% | 0.40 GiB | 0.40 GiB |
| `job-seeker-copilot-e2e-payment-service-1` | 3.80% | 20.75% | 0.39 GiB | 0.39 GiB |
| `job-seeker-copilot-e2e-user-management-gateway-1` | 10.30% | 63.84% | 0.29 GiB | 0.29 GiB |
| `job-seeker-copilot-e2e-reporting-gateway-1` | 4.24% | 26.84% | 0.27 GiB | 0.28 GiB |
| `job-seeker-copilot-e2e-job-finder-gateway-1` | 6.77% | 30.06% | 0.25 GiB | 0.25 GiB |
| `job-seeker-copilot-e2e-payment-gateway-1` | 3.88% | 22.04% | 0.23 GiB | 0.24 GiB |
| `job-seeker-copilot-e2e-postcode-io-gateway-1` | 0.18% | 0.21% | 0.24 GiB | 0.24 GiB |
| `job-seeker-copilot-e2e-jsearch-gateway-1` | 0.61% | 4.13% | 0.23 GiB | 0.23 GiB |
| `job-seeker-copilot-e2e-google-maps-gateway-1` | 0.18% | 0.24% | 0.23 GiB | 0.23 GiB |
| `job-seeker-copilot-e2e-job-matching-service-1` | 5.41% | 26.07% | 0.23 GiB | 0.23 GiB |
| `job-seeker-copilot-e2e-document-generation-gateway-1` | 0.18% | 0.28% | 0.23 GiB | 0.23 GiB |
| `job-seeker-copilot-e2e-cv-cover-letter-service-1` | 0.63% | 4.30% | 0.23 GiB | 0.23 GiB |
| `job-seeker-copilot-e2e-reporting-service-1` | 3.90% | 16.95% | 0.22 GiB | 0.22 GiB |
| `job-seeker-copilot-e2e-reed-gateway-1` | 0.17% | 0.19% | 0.22 GiB | 0.22 GiB |
| `job-seeker-copilot-e2e-adzuna-gateway-1` | 0.16% | 0.18% | 0.22 GiB | 0.22 GiB |
| `job-seeker-copilot-e2e-location-gateway-1` | 0.18% | 0.23% | 0.21 GiB | 0.21 GiB |
| `job-seeker-copilot-e2e-location-service-1` | 0.17% | 0.25% | 0.21 GiB | 0.21 GiB |
| `job-seeker-copilot-e2e-stripe-gateway-1` | 0.18% | 0.20% | 0.21 GiB | 0.21 GiB |
| `job-seeker-copilot-e2e-nhs-jobs-gateway-1` | 0.19% | 0.36% | 0.21 GiB | 0.21 GiB |
| `job-seeker-copilot-e2e-apprenticeships-gateway-1` | 0.17% | 0.21% | 0.20 GiB | 0.20 GiB |
| `job-seeker-copilot-e2e-system-data-service-1` | 0.18% | 0.26% | 0.19 GiB | 0.19 GiB |
| `job-seeker-copilot-e2e-document-export-service-1` | 0.20% | 0.40% | 0.18 GiB | 0.18 GiB |
| `job-seeker-copilot-e2e-llm-gateway-1` | 0.17% | 0.21% | 0.18 GiB | 0.18 GiB |
| `job-seeker-copilot-e2e-job-seeker-copilot-client-1` | 5.33% | 27.14% | 0.13 GiB | 0.13 GiB |
| `job-seeker-copilot-e2e-user-profile-postgres-1` | 1.98% | 9.23% | 0.06 GiB | 0.06 GiB |
| `job-seeker-copilot-e2e-application-tracker-postgres-1` | 1.91% | 8.19% | 0.05 GiB | 0.05 GiB |
| `job-seeker-copilot-e2e-document-store-postgres-1` | 0.80% | 4.68% | 0.05 GiB | 0.05 GiB |
| `job-seeker-copilot-e2e-authentication-postgres-1` | 1.56% | 6.59% | 0.04 GiB | 0.05 GiB |
| `job-seeker-copilot-e2e-payment-postgres-1` | 1.46% | 5.15% | 0.04 GiB | 0.04 GiB |
| `job-seeker-copilot-e2e-job-service-postgres-1` | 0.99% | 4.73% | 0.04 GiB | 0.04 GiB |
| `job-seeker-copilot-e2e-document-generation-postgres-1` | 0.95% | 4.47% | 0.03 GiB | 0.04 GiB |

## Bottleneck indicators

Highest peak memory:

- `job-seeker-copilot-e2e-clamav-1`: 0.95 GiB
- `job-seeker-copilot-e2e-authentication-service-1`: 0.48 GiB
- `job-seeker-copilot-e2e-job-service-1`: 0.47 GiB
- `job-seeker-copilot-e2e-user-profile-service-1`: 0.45 GiB
- `job-seeker-copilot-e2e-document-store-service-1`: 0.41 GiB
- `job-seeker-copilot-e2e-application-tracker-service-1`: 0.40 GiB
- `job-seeker-copilot-e2e-payment-service-1`: 0.39 GiB
- `job-seeker-copilot-e2e-user-management-gateway-1`: 0.29 GiB
- `job-seeker-copilot-e2e-reporting-gateway-1`: 0.28 GiB
- `job-seeker-copilot-e2e-job-finder-gateway-1`: 0.25 GiB

Highest peak CPU:

- `job-seeker-copilot-e2e-application-tracker-service-1`: 89.73%
- `job-seeker-copilot-e2e-authentication-service-1`: 76.02%
- `job-seeker-copilot-e2e-user-profile-service-1`: 66.68%
- `job-seeker-copilot-e2e-user-management-gateway-1`: 63.84%
- `job-seeker-copilot-e2e-document-store-service-1`: 38.87%
- `job-seeker-copilot-e2e-job-service-1`: 34.32%
- `job-seeker-copilot-e2e-job-finder-gateway-1`: 30.06%
- `job-seeker-copilot-e2e-job-seeker-copilot-client-1`: 27.14%
- `job-seeker-copilot-e2e-reporting-gateway-1`: 26.84%
- `job-seeker-copilot-e2e-job-matching-service-1`: 26.07%

## Stability and variable consumption

- Restarts across profiles: 0
- OOM-killed containers: 0
- Paid provider, Google Maps and LLM consumption: measured zero because this benchmark is fixture-only.
- Highest fully successful measured concurrency: 25 active sessions.
- Highest attempted concurrency: 25 active sessions; 0 sessions failed.
- Docker stats sampling errors disclosed across profiles: 1. The 25-session run retained nine valid samples and one stats call exceeded the 20-second sampler limit.
- Transport observations at 25 sessions: 100 expected unauthenticated bootstrap responses, 3 cancelled navigation requests and 0 application errors.

## Interpretation boundary

All required levels through 25 sessions completed, so this run did not expose a failing application-service boundary. It did expose a practical latency boundary: throughput peaked at 10 sessions and the 25-session p95 reached 59.45 seconds, leaving essentially no headroom against the 60-second journey timeout. The host-side browser processes are excluded from Docker CPU/memory, so the test cannot attribute that slowdown solely to the service stack.

The job-details interaction is client-side expansion of the search result, so there is no separate job-details endpoint latency to report. The response percentiles include the job search and dashboard/reporting calls that precede that interaction. Generation latency is not applicable because this capacity workload intentionally forbids paid generation.

No 50-session run was attempted: the instruction allowed higher levels only when 25 succeeded comfortably, and a 59.45-second p95 is not comfortable. These runs do not establish capacity above 25. Any AWS sizing or higher-user figures derived from them must be labelled **calculated** or **projected**, not benchmark results.
