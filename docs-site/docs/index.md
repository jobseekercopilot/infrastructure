<div class="jsc-hero" markdown>

# Job Seeker Copilot

Technical documentation for the platform that helps a job seeker manage a profile and evidence, find and save jobs, track applications, and create application documents.

**Source of truth:** reviewed implementation and retained evidence on the
production-confidence feature branches, audited 11 August 2026.

This is living documentation for the current development architecture. It
evolves alongside the repositories' `develop` branches and identifies features
as incomplete, disabled, or experimental until they are integrated and
verified.

</div>

## Start with the question you have

<div class="jsc-grid" markdown>

<div class="jsc-card" markdown>

### Does it work for different people?

Start with the [product-confidence evidence](confidence/index.md),
[testing layers](confidence/testing.md) and [real-world personas](confidence/personas.md).

</div>

<div class="jsc-card" markdown>

### What has actually been measured?

Review [capacity](evidence/capacity.md), the dated [AWS decision](evidence/aws.md)
and [unit-economics inputs](evidence/unit-economics.md).

</div>

<div class="jsc-card" markdown>

### What does it do?

Read the [product overview](product/overview.md) and current [implementation status](reference/implementation-status.md).

</div>

<div class="jsc-card" markdown>

### What happens when…?

Follow an end-to-end [user journey](journeys/account-authentication.md), including the requests, services, stores, and providers involved.

</div>

<div class="jsc-card" markdown>

### Where does this service fit?

Scan the [service catalogue](services/catalogue.md) or the [dependency maps](architecture/dependency-maps.md).

</div>

<div class="jsc-card" markdown>

### Where does data live?

Use [data ownership](data/ownership.md) to identify the system of record and its access boundary.

</div>

<div class="jsc-card" markdown>

### How do I run it?

Follow the verified [local development](infrastructure/local-development.md) path and [configuration reference](operations/configuration.md).

</div>

<div class="jsc-card" markdown>

### What should I update?

Use the [change guide](development/change-guide.md) and [documentation maintenance checklist](development/documentation-maintenance.md).

</div>

</div>

## Confidence snapshot

<div class="jsc-grid" markdown>

<div class="jsc-card jsc-card--measured" markdown>

### 10 concurrent sessions

**Measured · 10 August 2026**

10/10 fixture-backed DISCOVER journeys succeeded. Session p95 was 16.285 s;
browser-response p95 was 273 ms.

</div>

<div class="jsc-card jsc-card--failed" markdown>

### 25 concurrent sessions

**Measured failure · 10 August 2026**

0/25 journeys completed. The first observed boundary was job-detail latency,
not an OOM or container restart.

</div>

<div class="jsc-card jsc-card--calculated" markdown>

### Initial beta compute

**Calculated, not benchmarked on AWS**

One `m7i.2xlarge` in London is the current bounded public-beta candidate at
$340.33/month compute-only On-Demand.

</div>

<div class="jsc-card jsc-card--partial" markdown>

### Seven profile personas

**Deterministic coverage added**

Sparse, typical, rich, stress, CV-led, manual-first and career-change profiles
are canonical System Data states. Full browser coverage remains in progress.

</div>

</div>

!!! warning "Evidence, not a readiness percentage"
    Measured, calculated and planned claims are labelled separately. Known
    failures remain visible; this site does not turn them into a vanity score.

## Platform at a glance

```mermaid
flowchart LR
  A[Job seeker] --> B[Web application]
  B --> C[Browser gateways]
  C --> D[Domain services]
  D --> E[Service data stores]
  D --> F[Provider gateways]
  F --> G[External APIs and fixtures]
```

The browser uses same-origin BFF routes. The BFF sends session-derived identity to the appropriate gateway. Gateways validate identity and coordinate domain services; provider gateways isolate third-party protocols and credentials. Persistent domains own separate schemas and do not share a database.

!!! warning "Pre-release platform"
    The repositories describe private-beta hardening rather than a production release. Capability status is explicit throughout this site. Fixture mode is the safe local default; live integrations require deliberate overlays and credentials.

## Documentation path

This site is arranged so a new developer can drill down without first knowing repository names:

**Product → User journey → Architecture → Domain → Service → API → Data → Infrastructure**

Implementation-specific API details remain in producer-owned OpenAPI contracts and repository READMEs. The central site explains how those contracts work together.
