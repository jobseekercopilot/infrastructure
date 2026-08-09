<div class="jsc-hero" markdown>

# Job Seeker Copilot

Technical documentation for the platform that helps a job seeker manage a profile and evidence, find and save jobs, track applications, and create application documents.

**Source of truth:** implementation on each repository's `develop` branch, audited 9 August 2026.

This is living documentation for the current development architecture. It
evolves alongside the repositories' `develop` branches and identifies features
as incomplete, disabled, or experimental until they are integrated and
verified.

</div>

## Start with the question you have

<div class="jsc-grid" markdown>

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

## Platform at a glance

```mermaid
flowchart LR
  User[Job seeker] --> Browser[Angular + Express BFF<br/>:3000]
  Browser --> Edge[Browser-facing gateways]
  Edge --> Domain[Domain services]
  Domain --> Stores[(Service-owned PostgreSQL<br/>and object storage)]
  Domain --> Providers[Provider gateways]
  Providers --> External[External APIs<br/>or System Data fixtures]
```

The browser uses same-origin BFF routes. The BFF sends session-derived identity to the appropriate gateway. Gateways validate identity and coordinate domain services; provider gateways isolate third-party protocols and credentials. Persistent domains own separate schemas and do not share a database.

!!! warning "Pre-release platform"
    The repositories describe private-beta hardening rather than a production release. Capability status is explicit throughout this site. Fixture mode is the safe local default; live integrations require deliberate overlays and credentials.

## Documentation path

This site is arranged so a new developer can drill down without first knowing repository names:

**Product → User journey → Architecture → Domain → Service → API → Data → Infrastructure**

Implementation-specific API details remain in producer-owned OpenAPI contracts and repository READMEs. The central site explains how those contracts work together.
