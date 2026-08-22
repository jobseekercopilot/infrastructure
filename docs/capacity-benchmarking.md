# Capacity benchmarking

This workflow measures the complete `job-seeker-copilot-e2e` Compose project
while the existing Cucumber/Playwright DISCOVER journey drives the real browser
UI. It reuses production-shaped services and deterministic fixtures; it does
not claim to measure paid providers or production infrastructure.

## Evidence classes

- **Measured:** values read from Docker, the browser workload runner or the host
  during a named run. Raw JSON uses `evidenceClass: measured`.
- **Calculated:** arithmetic using measured values and a dated official price.
- **Projected:** scaling beyond a tested concurrency point. Projections are
  never benchmark results.

Browser processes execute on the host, so container CPU/RAM describes the
application stack only. Host specifications are retained beside each run.

## Workloads

`config/capacity-workloads.json` is authoritative. `idle` measures the fixed
floor. Browser profiles run 1, 5, 10, 15, 20, 25, 50 or 100 simultaneously active
DISCOVER sessions. They reuse one registered synthetic fixture identity, so
the reported concurrency is active browser sessions—not registered-user
capacity or a count of isolated HTTP requests.

The DISCOVER workload signs in, opens job search, searches fixture results,
views a representative result and exercises job matching plus fixture-backed
location/commute enrichment. Document generation is intentionally separate:
the safe default records zero paid LLM requests and does not extrapolate a
generation price from a search session.

## Safety and reruns

```bash
./scripts/build-all.sh --profile e2e
./scripts/start-local.sh --profile e2e --build
python -m scripts.benchmark.run_capacity --profile idle
python -m scripts.benchmark.run_capacity --profile single-user
python -m scripts.benchmark.run_capacity --profile concurrent-5
```

The runner is restricted to loopback port 3100, requires two explicit capacity
flags internally, rejects real-provider and AI-generation flags, checks all
gateway mode endpoints and prepares the fixture state before browser work.
Capacity preparation skips the broader provider-contract smoke script because
this workload exercises authenticated search only; full provider and generation
contracts remain the responsibility of their integration and E2E suites.
Profiles 50 and 100 additionally require `--allow-high-concurrency`; use it only
after the preceding run shows memory/CPU headroom. Stop increasing load after
errors, OOM kills, restarts, host pressure or sharply degrading latency.

Raw results live under ignored `benchmark-results/runs/`. Copy only reviewed,
non-secret baseline JSON into `benchmark-results/baseline/<date>/` when a run
should be retained in source control. Generate a human report with:

```bash
python -m scripts.benchmark.generate_report \
  benchmark-results/baseline/<date>/*.json \
  --output docs/capacity-report-<date>.md
```

## Metrics and limits

Each result includes per-container and aggregate CPU, average/idle/peak memory,
network and block-I/O counters, PIDs, writable-layer size, restarts, health and
OOM state. The browser result supplies response counts/errors, session and
response p50/p95 latency, p99 only at 100 or more samples, elapsed time and
session throughput.

Docker's instantaneous CPU percentage can exceed 100% on a multi-core host.
The first sample in an active profile is a pre-workload baseline, not a second
independent idle benchmark. Network counters are container-lifetime counters;
compare start/end samples rather than treating the final value as run-only
traffic. Database-operation and storage-growth attribution require dedicated
instrumentation before they can be claimed per feature.

## Real-world persona boundary

The seven-profile `real-world-personas-v2` System Data state validates profile
shape and lifecycle coverage. It is deliberately separate from this concurrent
browser workload: persona variety is not a substitute for measured active
sessions, and measured capacity must not be multiplied by persona count. The
infrastructure E2E overlay is pinned to the current governed multi-role fixture
dataset `1.2.0` so lifecycle preparation fails on genuine contract drift.
