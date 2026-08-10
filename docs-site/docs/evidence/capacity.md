# Performance and capacity

Benchmark date: **10 August 2026**
Evidence class: **measured local fixture stack**

| Active browser sessions | Result | Session p95 | Response p95 | Peak app CPU | Peak app memory |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | 1/1 pass | 6.945 s | 89 ms | 262.94% | 9.89 GiB |
| 5 | 5/5 pass | 8.767 s | 164 ms | 62.48% | 9.91 GiB |
| 10 | 10/10 pass | 16.285 s | 273 ms | 651.73% | 9.96 GiB |
| 25 | **0/25 fail** | 50.452 s | 1.110 s | 1,214.41% | 8.71 GiB |

The host had 16 logical x86 CPUs and 30.63 GiB RAM. Browser processes ran on
the host and are excluded from container memory. No containers restarted or
were OOM-killed. At 25 sessions every journey timed out waiting for job details,
so the first observed boundary is application latency, not proven memory
exhaustion.

!!! danger "No unsupported scale claim"
    This result supports neither 25 concurrent DISCOVER sessions nor a 50/100
    session claim. Registered users and monthly active users are not concurrent
    browser sessions.

The detailed methodology and raw-result retention rules are in
`docs/capacity-benchmarking.md`; the complete retained table is in
`docs/capacity-report-2026-08-10.md`.
