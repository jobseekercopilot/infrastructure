# Maintaining documentation

Use this checklist whenever a service or capability changes.

## New repository or service

- Add it to `infrastructure/config/services.json`, build order, and workspace lock as appropriate.
- Add/verify Compose wiring, port, health, and profile membership.
- Create a repository README with role, callers, callees, data, configuration, run/test commands, and central-doc links.
- Update the [catalogue](../services/catalogue.md), relevant dependency map, and implementation status.

## New or changed endpoint

- Update the producer-owned OpenAPI contract and consumer pin/checksum.
- Keep endpoint details in OpenAPI; update this site only where the route changes a workflow, trust boundary, or important entry point.
- Verify whether it is browser-facing, internal service-to-service, provider-facing, operator-only, or non-production-only.

## New external integration

- Add a provider gateway or document why isolation is unnecessary.
- Document fixture/live/disabled modes, credentials, enable switch, error translation, rate limits, and licence/provenance constraints.
- Update [external integrations](../infrastructure/external-integrations.md), configuration, dependency maps, and mode-isolation checks.

## New database or store

- Name the owning service and prohibit direct sibling access.
- Add migration, backup/restore, retention/deletion, encryption, and recovery guidance.
- Update [data ownership](../data/ownership.md), the ER diagram, Compose, environment schema, and service catalogue.

## New or changed user journey

- Trace browser → BFF → gateway → services → stores/providers → response.
- Add/update a sequence diagram and describe partial failures.
- Label capability status based on client route registration and runtime wiring, not repository presence alone.

## New environment variable

- Add it to the owning repository's example/config guide.
- Add it to Infrastructure's runtime schema and generated-profile logic when fleet-wide.
- State consumer, required/optional behaviour, safe default, purpose, and whether it is secret.
- Never put a real value in source or docs.

## Architecture change

- Write or update an ADR in the repository that owns the decision.
- Update system/domain maps, principles, ownership, and affected journeys.
- Explain inconsistencies during migration rather than documenting the target as current.

## Review before merge

- Build this site with `mkdocs build --strict`.
- Check repository names, paths, ports, service URLs, Compose names, API paths, database owners, external modes, and configuration against code.
- Search for stale capability claims such as “planned”, “unavailable”, or “implemented”.
- Keep diagrams as Mermaid text and link detailed API schemas instead of copying them.

## Source hierarchy

When sources disagree, use this order:

1. Executable code and migrations on `develop`.
2. Tests and generated/checked producer contracts.
3. Infrastructure catalogue, Compose, and profile validation.
4. Repository README/runbooks/ADRs.
5. This central narrative.

Correct the lower source or explicitly record uncertainty. Do not guess; write **Not confirmed from current implementation**.
