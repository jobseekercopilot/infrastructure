# Implementation status

Status is derived from source, Compose/catalogue inclusion, client route registration, and repository beta-readiness notes on `develop`.

The authenticated private GitHub account lists 30 repositories, exactly matching the 29 platform workspaces plus the adjacent landing checkout audited here. The landing repository's default branch is `main`, but this audit explicitly fetched and used its existing `develop` branch as requested.

## User-facing capability status

| Capability | Backend | Client path | External mode | Confidence |
|---|---|---|---|---|
| Account/session/profile/evidence | Implemented and composed | Enabled | Local/hosted auth; SES fixture or configured | Confirmed |
| Job search and saved jobs | Implemented and composed | Enabled | Fixture default; five live providers optional | Confirmed |
| Application tracking | Implemented and composed | Enabled through Job Finder and documents | Internal | Confirmed |
| Document generation/approval/export | Implemented and composed | Enabled | Fixture LLM default; OpenAI optional | Confirmed |
| Document management | Implemented and composed | Enabled route allowlist | Filesystem + ClamAV locally | Confirmed |
| UK place/postcode | Implemented and composed through Location Service | Enabled | Fixture default; Postcodes.io and optional Google Places | Confirmed |
| Reporting | Implemented and composed | Enabled | Internal projection | Confirmed |
| Payment/Stripe | Backend implemented/composed | Explicitly disabled | Stripe fixture backend | Confirmed disabled |
| Commute route assessment | Implemented and composed | Displayed on eligible job cards | Google Routes when explicitly enabled; unavailable/degraded otherwise | Confirmed controlled-beta capability |
| NHS Jobs and apprenticeship providers | Implemented and composed | Enabled with specialist badges/details | Fixture default; approved live profiles smoke-tested | Confirmed |

## Beta readiness

The platform is pre-release. Many repository READMEs explicitly say “not beta-ready” or “sanitised audit baseline” even where the primary implementation exists. That wording generally reflects remaining production evidence, security rollout, operational controls, or cross-service journey gates—not an absence of all code.

Treat these labels carefully:

- **Implemented**: code, tests/contracts, and runtime wiring exist on `develop`.
- **Optional**: implementation exists but only a deliberate profile/overlay enables it.
- **Disabled by default**: code or backend exists, but the normal user path rejects it.
- **Incomplete/skeleton**: no callable implementation can be established from `develop`.
- **Not beta-ready**: repository owners have recorded release blockers; do not equate with production-ready.

## Known documentation/code discrepancies found during audit

- The client README said reporting was unavailable, while `src/server.ts` registers the reporting proxy and the fail-closed prefix contains only payment. This documentation set treats reporting as enabled and payments as disabled.
- “Job matching” names and DTOs can suggest candidate scoring. The implementation performs application-record reconciliation and does not set `matchScore`.
- Location retains a compatibility `GET /api/locations` and postcode path through Postcodes.io, while the current v2 autocomplete/resolve path runs through Location Service and can use Google Places. Job Matching requests bounded commute matrices through Location Service for eligible jobs.
- Infrastructure Compose lists `payment-gateway` as a client dependency, although the BFF rejects its route prefix. Composition indicates backend availability, not browser enablement.

## Not confirmed from current implementation

- A production deployment topology, registry image set, public observability stack, or production database encryption evidence.
- Production approval, long-term operational quotas, and reliability evidence for Google Maps beyond bounded local live validation.
- Browser-accessible Stripe checkout or a live Stripe deployment profile.
