# Unit-economics inputs — 2026-08-10

## Evidence boundary

This model separates three classes of evidence:

- **Measured:** fixture E2E resource and request evidence from
  `benchmark-results/baseline/2026-08-10/`.
- **Calculated:** arithmetic using measured values and dated public rates.
- **Projected:** example utilisation mixes; these are not forecasts or customer
  pricing recommendations.

The measured DISCOVER session signs in, searches, views a job and exercises
matching plus location/commute enrichment. It does not generate documents or
call paid providers. The benchmark therefore measured zero LLM requests,
tokens, paid job-provider calls and Google Maps calls.

## Fixed compute allocation

The recommended single-node public-beta compute input is the calculated
`m7i.2xlarge` London On-Demand cost of **$340.33/month**. This excludes database,
storage, networking, observability, backups, support, tax and engineering cost.
It must not be treated as total cost of service.

| Projected utilisation | Sessions/month | Fixed compute/user | Fixed compute/session |
|---|---:|---:|---:|
| 500 monthly active users × 4 sessions | 2,000 | $0.681 | $0.1702 |
| 2,000 monthly active users × 8 sessions | 16,000 | $0.170 | $0.0213 |
| 5,000 monthly active users × 12 sessions | 60,000 | $0.068 | $0.0057 |

These divisions assume demand remains within the measured successful
concurrency boundary. They do not imply that 5,000 users can all be active at
once. A two-node availability model doubles the fixed compute allocation before
adding the load balancer and database costs.

For a very small private beta, the calculated `t3.xlarge` input is
$137.82/month. At 500 users × 4 sessions this is $0.276/user/month and
$0.0689/session, but that host has only four burstable vCPUs and is not a
comfortable public-beta capacity claim.

## Variable-cost inputs

### Job search, matching and commute

- Measured paid provider cost: **$0** in fixture mode.
- Measured Google Maps cost: **$0** in fixture mode.
- Measured composite request volume at 10 sessions: 567 browser responses.
- Measured composite latency at 10 sessions: response p50 36 ms, p95 273 ms,
  p99 384 ms.
- Measured application failures: four pricing/wallet 404s per session.

The current evidence cannot reliably split platform compute between search,
matching and commute because they execute in one short composite browser
session against a large fixed idle floor. The calculated fixed compute/session
figures above are the defensible input for that bundle. A per-feature cost claim
requires isolated repetitions long enough to distinguish marginal CPU from
background noise.

### CV and cover-letter generation

The governed fixture records 2,100 input and 1,600 output tokens for the
combined CV/cover-letter operation. The configured
model family is GPT-4.1 mini; its official standard text price retrieved on
2026-08-10 is [$0.40 per million input tokens and $1.60 per million output
tokens](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

Calculated provider cost for that combined fixture-shaped generation:

`(2,100 × $0.40 / 1,000,000) + (1,600 × $1.60 / 1,000,000) = $0.00340`

That is **0.34 US cents per combined generation**, or $3.40 per 1,000, before
retries, moderation, failed outputs, longer prompts, taxes or any priority tier.
It is a scenario rather than the observed live average. Six bounded live
combined generations on 11 August used 4,622 input and 4,703 output tokens in
total, costing $0.009377 by provider-reported usage, or $0.001563 mean per
combined output. That small synthetic sample is quality evidence, not a demand
forecast. The current fixture does not support a credible
split between “cost per CV” and “cost per cover letter”; measure those operations
separately before pricing either one.

### Storage, databases and external providers

The benchmark captured container-lifetime network/block counters, not
feature-attributed storage growth or database operations. Current paid job
provider and Google Maps prices/quotas were not exercised and are therefore
left as unknown rather than represented as zero-cost production inputs.

## Product-pricing use

A later gross-margin model should add, at minimum:

1. fixed compute at the selected availability level;
2. RDS, EBS/object storage, backups, load balancer, NAT/data transfer, logging
   and support;
3. observed generations per light/medium/heavy user multiplied by live token
   distributions rather than fixture averages;
4. paid search/location operations and retry/error rates;
5. payment fees, customer support and engineering/operational overhead;
6. a capacity step function when concurrency approaches the measured
   10-session boundary.

No customer subscription price is changed or recommended by this document.

## Current validation spend

Six OpenAI calls were executed on 11 August through the product gateway after
the initial credential inventory. Their usage-calculated spend was $0.009377;
latency was 6.349–13.466 seconds. Job-provider and location costs remain
separate. The exact execution boundary is recorded in
`real-world-validation-costs-2026-08-10.md`.
