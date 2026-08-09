# Principles and boundaries

These are conventions demonstrated by `develop`, not aspirational rules.

## Gateways versus services

- Browser-facing gateways validate or translate identity, constrain the exposed route set, and orchestrate downstream calls.
- Domain services own behaviour and persistent state.
- Provider gateways isolate external authentication, protocol mapping, rate/error translation, and fixture/live mode.
- The Express BFF is the same-origin browser boundary. It is not a general service mesh and exposes an explicit allowlist.

The split is not completely uniform. Location Gateway directly contains validation, caching, rate limiting, and resilience that might otherwise sit in a domain service. `location-service` is not yet implemented on `develop`.

## Ownership derived from trusted identity

Browser-supplied `Authorization`, `X-User-Id`, email, and owner selectors are ignored at the BFF boundary. JWT resource services use the validated `sub`. Internal service calls combine a dedicated service token with an owner header set from that trusted subject.

Not every service is a JWT resource server: stateless internal services such as Reporting Service and Payment Service use caller-specific service identities and bounded owner headers.

## Database ownership

Persistent services have separate PostgreSQL databases and forward-only Flyway migrations. Consumers call an API; they do not read a sibling schema. Cross-service mutations use idempotency keys, operation records, and reconciliation rather than distributed database transactions.

## Producer-owned contracts

The producing repository owns its OpenAPI snapshot. Consumers pin a reviewed producer revision and checksum and generate clients reproducibly. Runtime Swagger is usually local-only or disabled by default in production. Handwritten adapters remain in a few repositories where the consumed slice is deliberately small; contract checks still validate those operations.

## Canonical data and provenance

Provider-specific job data becomes a canonical job with stable identity, source references, and field provenance. Saving captures an immutable snapshot. Profile/evidence, job, claim-ledger, document, and application references use revision IDs and digests so later edits cannot rewrite prior decisions.

## Immutable versions and explicit pointers

Documents use immutable versions grouped into families. “Current” and “approved” are explicit pointers/actions, not in-place content edits. Applications freeze exact document versions at the first `APPLIED` transition.

## Safe provider defaults

Fixture mode is the standard local/E2E default. Live mode requires explicit overlays, enable switches, and credentials. Provider errors are translated to stable platform errors; credentials stay server-side and are absent from browser bundles and documentation.

## Degradation rather than invented success

Job search reports partial provider/matching status. Reporting can omit unavailable document activity but does not write. Recoverable document/application workflows return `202` while incomplete. Missing payment/browser approval returns feature unavailable. The code does not conceal partial completion behind a success response.

