# Data ownership

## Systems of record

| Domain | Owning component | Store | Important entities | Direct access by other services? |
|---|---|---|---|---|
| Accounts and sessions | Authentication Service | `authentication` PostgreSQL | users, sessions, refresh tokens, reset tokens, deletion operations | No; API/JWKS only |
| Profile and evidence | User Profile Service | `user_profile` PostgreSQL | profile, roles, qualifications, preferences, evidence entries/revisions/facts, immutable snapshots | No; subject-bound API only |
| Found jobs | Job Service during request | Bounded in-memory cache | canonical provider results | No persistent record unless saved |
| Saved jobs | Job Service | `job_service` PostgreSQL | saved jobs, immutable snapshots | No; API only |
| Generation coordination | Document Generation Gateway | `document_generation` PostgreSQL | durable generation operations/checkpoints/references | No; owner-scoped gateway API |
| Documents | Document Store Service | `document_store` PostgreSQL + object provider | families/versions, files, activity, lifecycle, upload/reconciliation/workflow records | No database access; API only |
| Applications | Application Tracker Service | `application_tracker` PostgreSQL | records, events, exact references, selections, workflow/reconciliation records | No; API only |
| AI credit/payment | Payment Service | `payment` PostgreSQL | wallets, append-only transactions, reservations | No; service APIs only |
| Rejected LLM output | CV/Cover Letter Service | Optional encrypted filesystem quarantine | owner/operation-bound short-lived artifacts | Operator API only; disabled unless configured |
| Synthetic fixtures | System Data Service | Versioned read-only dataset files | named states and provider responses | Non-production HTTP APIs only |
| Reporting | No independent owner | None | Computed projection | Reads domain APIs; never writes |

## Boundary rule

No service on `develop` connects to a sibling service's database. Cross-domain consistency is achieved with trusted APIs, immutable references/digests, idempotency keys, optimistic versions, durable workflow records, and reconciliation.

Application and Document Store intentionally hold related but different facts:

- Document Store owns whether a document version exists, its state/content/files/lineage, and family current choice.
- Application Tracker owns which exact versions an application selected and froze when applied.

Neither is allowed to silently rewrite the other's history.

## Object bytes

Document Store separates file metadata from object bytes. Local Compose configures a persistent filesystem volume at `/app/data/objects`; the configured object-provider abstraction owns upload/read/delete/reconciliation. ClamAV scans untrusted uploads on an isolated network. Export Service writes through the Store API and never mounts the volume.

## Backups and deletion

Service runbooks define PostgreSQL backup/restore evidence. Local volumes are developer data, not a backup. Document deletion has archive, recovery, retention, legal hold, and separately enabled purge semantics. Coordinated account deletion records durable progress because several service-owned stores cannot be erased atomically.
