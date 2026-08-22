# Public-beta stateful-storage inventory

No ECS task or EC2 host may silently be the only copy of required durable
state. The lean node is disposable and deployments intentionally stop tasks.

| State/path | Required durability | Production location | Retention/restore owner |
|---|---|---|---|
| seven service databases and Flyway history | durable | encrypted private RDS PostgreSQL | daily AWS Backup + 14-day automated backups; service/data owners |
| generated/imported documents under `documents/` | durable | versioned SSE-KMS S3 | daily AWS Backup + 35-day noncurrent window; Document Store owner |
| rejected/incomplete application uploads under `quarantine/application-uploads/` | short-lived durable quarantine | same SSE-KMS S3 bucket | active objects expire after seven days; encrypted bucket recovery points can retain a recoverable copy for up to 35 days; Document Store/security owner |
| Document Store metadata, retention and reconciliation records | durable | `document_store` logical DB | restored with RDS and reconciled against S3; Document Store owner |
| permanent-erasure recovery journal | durable, immutable recovery evidence outside the customer-data restore blast radius | separately keyed/versioned/Object-Locked bootstrap S3 bucket under `permanent-erasures/v1/`; never selected by AWS Backup | Document Store writes the canonical checksum-bound record before object erasure, retains its exact key/version/hash binding in PostgreSQL and reconciles ambiguous writes; privacy/disaster-recovery owners approve the independently versioned retention policy and isolated replay |
| document-generation retained-response/recovery records | durable | `document_generation` logical DB and Document Store APIs where declared | restored with owning DB/S3; generation owner validates reconciliation |
| payment reservations, ledger, Stripe event/reconciliation state | durable | `payment` logical DB | restored with RDS; payment owner must reconcile before activation |
| application-tracker/provider-derived records | durable where retained | `application_tracker`/`job_service` logical DBs | restored with RDS; owning service validates provider terms/retention |
| rejected LLM-generation forensic quarantine | not enabled for beta | none | `REJECTED_GENERATION_QUARANTINE_ENABLED=false`; local-only adapter is not accepted as durable storage |
| ClamAV signatures/database, sockets and file logs | cache/ephemeral operations state, not business state | preloaded signatures plus updates on the disposable task layer; UID/GID-owned bounded `tmpfs` at `/run/clamav`, `/var/log/clamav` and `/tmp` in a dedicated no-task-role scanner task | no restore; signatures are recreated from the immutable image and scanner HTTPS-only refresh egress; loaded/on-disk mismatch triggers reload and remains unhealthy, while stale/missing signatures fail health/use after 48 hours; platform owner |
| uploads/exports/application/operator `/tmp` | scratch only | bounded hardened per-container task `tmpfs` (128 MiB application, 32 MiB operator) | no restore; remove on task replacement and never reference as durable output |
| ECS host filesystem/EBS | disposable | encrypted EC2 root volume | no application restore; replace node from pinned AMI/user data |
| runtime secrets/JWT keys | durable configuration | KMS-encrypted Secrets Manager versions | rotation/recovery owner; Terraform creates containers but never values |
| application/access/security logs | operational evidence | CloudWatch and encrypted access-log S3 | exact reviewed `securityLogRetentionDays` value for every store (30-day lean default); operations/security owner |
| Terraform state and locks | control-plane state | bootstrap S3/KMS/native lock | versioned; platform owner; never in application backup vault |
| immutable images/release evidence | release evidence | ECR digests + protected GitHub artifact containing manifest/provenance and non-deployed Landing tar/config/SAM evidence | ECR retains the 20 newest images and GitHub artifact retention is 90 days; platform owner must preserve every active/rollback release before either bound expires |
| prepared Docker image archive | short-lived release transport, not a deployable record | checksum-bound GitHub Actions artifact between no-OIDC prepare and OIDC publisher jobs | one day; never used for rollback, publisher verifies/loads it and final ECR digests replace it as authority |

Current S3 `tmp/` objects expire after one day. Quarantined application uploads
are not a document system of record: active objects expire after seven days,
but an encrypted daily AWS Backup recovery point can retain either class for up
to 35 days. An operator restoring the bucket must reapply the lifecycle and
retention decision and avoid promoting temporary/quarantine objects to accepted
documents.

CV/cover-letter rejected-generation quarantine remains explicitly disabled
because the current encrypted adapter writes to a local filesystem. Enabling it
requires a separately reviewed durable adapter, lifecycle policy, access
control and restore/erasure semantics; mounting an unreviewed host path is not
an acceptable workaround.

The published legal deletion period must account for the longest recoverable
copy. The release gate therefore refuses account/document completion promises
under 35 days while S3 noncurrent versions and daily AWS Backup recovery points
use that window. A shorter promise requires a reviewed retention redesign, not
an operator deleting recovery evidence ad hoc.

The inverse bound is enforced as well: the immutable erasure journal cannot
expire before either published account- or document-deletion completion
window. Its independently reviewed policy/version, Object Lock days and
foundation output must agree. This keeps the exact replay evidence available
for every operation that may still be within its published completion window.

Application images must stream accepted output to the declared database/S3
owner before returning success. Scratch data may be lost on health failure,
deployment, scaling or node replacement. A new stateful path is a launch-contract
change: add it to this inventory, choose encrypted durable or explicitly
ephemeral storage, define retention/erasure/backup/restore ownership, update
least-privilege IAM and prove the failure behaviour.

The pinned upstream ClamAV entrypoint requires a writable container root layer,
so that scanner cannot claim a read-only root filesystem. It is still explicitly
disposable: the preloaded signature database and later updates live only on the
task's ephemeral writable layer, socket/log/scratch paths use bounded UID/GID-
owned `tmpfs`, the EC2 root volume is not backed up, and no restore process may
read ClamAV state from a stopped task or host. Not mounting an empty
`/var/lib/clamav` preserves the image's preloaded database and avoids a full CDN
download on each replacement. The scanner is a separate ECS task with no AWS
task role; only Document Store can reach `3310`, and only the scanner gets public
HTTPS signature-refresh egress. Exact-image launch validation proves initial
reload, loaded/on-disk equality, freshness and an idempotent second health pass;
it must be rerun if the upstream entrypoint or image digest changes.
