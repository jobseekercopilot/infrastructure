# Performance and capacity

Benchmark date: **11 August 2026**

Evidence class: **measured local fixture stack**

| Active browser sessions | Result | Session p95 | Response p95 | Peak app CPU | Peak app memory |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | 1/1 pass | 5.97 s | 182 ms | 317% | 8.01 GiB |
| 5 | 5/5 pass | 10.34 s | 571 ms | 259% | 8.14 GiB |
| 10 | 10/10 pass | 17.00 s | 709 ms | 783% | 8.35 GiB |
| 15 | 15/15 pass | 25.97 s | 472 ms | 714% | 8.42 GiB |
| 20 | 20/20 pass | 40.43 s | 609 ms | 702% | 8.66 GiB |
| 25 | 25/25 pass | 59.45 s | 546 ms | 567% | 8.64 GiB |

The prior 0/25 failure was traced to a frontend card being recreated when an
immutable refresh introduced a canonical identifier. Stable provider-job
tracking fixed it. The final ladder had zero application errors, restarts, OOM
kills and unhealthy containers.

!!! warning "Functional pass, not comfortable capacity"
    Throughput peaked at 10 sessions and the 25-session p95 left about 0.55
    seconds against the journey timeout. Browser workers consume host resources
    outside Docker. No 50-session run was attempted and no capacity above 25 is
    claimed. The sensible initial operating cap is about 15 active DISCOVER
    journeys until the intended AWS shape is measured.

The host had 16 logical x86 CPUs and 30.63 GiB RAM. The benchmark used only the
governed fixture providers; real providers and paid generation were disabled.
One Docker-stats observation at 25 sessions exceeded the sampler limit; nine
valid observations and the error are retained.

See `docs/capacity-report-2026-08-11.md` for source revisions, workload,
per-service measurements and interpretation limits.
