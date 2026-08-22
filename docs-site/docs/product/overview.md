# Product overview

Job Seeker Copilot is a pre-release application for organising a job search. Its implemented core brings together the information a claimant supplies, job adverts from several providers, application records, and generated application documents.

## Major capabilities

| Capability | What the user gets | Status on `develop` |
|---|---|---|
| Account and session | Registration, sign-in, refresh, logout, password reset, account export/deletion | <span class="status status--implemented">Implemented</span> |
| Profile and evidence | Search preferences plus a versioned evidence library and immutable evidence snapshots | <span class="status status--implemented">Implemented</span> |
| Job search | Reed, Adzuna, JSearch, NHS Jobs, and Find an apprenticeship results normalised into canonical jobs, deduplicated and optionally enriched with application state | <span class="status status--implemented">Implemented</span> |
| Saved jobs | Owner-scoped immutable canonical snapshots | <span class="status status--implemented">Implemented</span> |
| Application tracking | Saved/generated/applied lifecycle, immutable events, document selections, replacement and withdrawal recovery | <span class="status status--implemented">Implemented</span> |
| CV and cover-letter generation | Durable generation operations, evidence-grounded drafts, approval, export, download, and application linkage | <span class="status status--implemented">Implemented</span> |
| Document management | Families, immutable versions, files, approvals/current choice, uploads, archive/restore, retention and recovery controls | <span class="status status--implemented">Implemented</span> |
| Location lookup | UK place and postcode lookup through Postcodes.io or deterministic fixtures | <span class="status status--implemented">Implemented</span> |
| Reporting | Application summary, activity timeline, UC-journal text, and evidence text download | <span class="status status--implemented">Implemented</span> |
| Payments | Non-renewing document-credit catalogue, wallet/history, owned Stripe Checkout and signed reconciliation; live charging remains approval-gated | <span class="status status--implemented">Implemented, release-gated</span> |
| Commute routing | Rich route assessment through Google Maps | <span class="status status--incomplete">Not on develop</span> |
| Specialist job sources | NHS Jobs and Find an apprenticeship, with visible provenance and apprenticeship details | <span class="status status--implemented">Implemented</span> |

## What makes the platform distinctive

- Candidate evidence is versioned and explicitly selected before generation.
- Job provider responses are converted to a canonical model while retaining source provenance.
- Generated documents are immutable versions in document families; approval and “current” selection are explicit actions.
- Applications freeze the exact document versions used when moving to `APPLIED`.
- External providers can be replaced by deterministic System Data fixtures for local and E2E operation.
- Each persistent domain owns its own PostgreSQL database; cross-domain work uses APIs and recoverable workflows.

## Product boundaries

The application is not a job board and does not submit applications to provider sites. It records job-search and application activity. “Job matching” currently means reconciling found jobs with existing application records; it is not a candidate suitability score. Reporting estimates commitment progress from application statuses and explicitly says it is not an official or measured time log.

See [user journeys](../journeys/job-search.md) for behaviour and [implementation status](../reference/implementation-status.md) for beta limitations.
