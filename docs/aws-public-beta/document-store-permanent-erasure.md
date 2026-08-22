# Document Store permanent-erasure recovery procedure

Status: release-gated and not yet approved. This procedure is immutable release
evidence; it does not authorise an erasure, deployment or recovery action.

## Fixed production contract

The protected release pins the clean-verified Document Store source revision
and exact SHA-256 of its exported OpenAPI contract. The checked-in capability
remains false: only the protected immutable build may set
`documentStorePermanentErasureVerified=true`, after proving the pinned source
is contained by the workspace lock, rebuilding the service and matching the
exact contract and this runbook's checksum.

The customer-data recovery maximum is exactly 35 days: the bootstrap AWS
Backup plan and locked vault retain recovery points for at most 35 days, and
S3 noncurrent document versions expire after 35 days. Operators must also
inventory exceptional, copied, manual and exported recovery material before a
backup-expiry attestation; AWS configuration alone is not proof that no older
copy exists.

The independently reviewed erasure-journal retention is a separate policy and
must exceed 35 days and every published deletion-completion window. Its
Object-Locked, versioned bucket and KMS key are foundation resources outside
the Document Store database, documents bucket and customer-data Backup plan.
The journal bucket must not equal the documents bucket and the journal key
must not equal the application-data key.

Production requires all of the following controls:

- permanent-erasure initiation, the permanent write fence and versioned-object
  erasure are explicitly enabled;
- the ordinary document purge remains enabled under its reviewed policy;
- the fingerprint primary key is a stable generated secret and the optional
  previous-key ring contains only retained keys still needed to verify durable
  operations; new operations always use the primary key;
- the journal provider is `s3`, credentials mode is `task-role`, Object Lock is
  explicitly expected, and the region, exact bucket name, exact KMS key ARN
  and journal-policy version match the foundation and launch approval;
- custom endpoints and static AWS credentials are absent; and
- JVM/application timestamps are UTC. Document Store also uses explicit UTC
  clocks for the erasure saga, so `TZ=UTC` is defence in depth.

Fingerprint keys, document content, filenames and raw evidence must never be
placed in this procedure, a launch approval, an application log or a release
artifact.

## Machine-written immutable journal

An erasure operation begins in `JOURNAL_PENDING`. Before any live object
version can be deleted, Document Store serialises its canonical recovery
record and conditionally writes the fixed server-owned key
`permanent-erasures/v1/{operationId}.json` with `If-None-Match: *`, exact
content type and digest metadata/checksum, SSE-KMS using the dedicated exact
key ARN, and S3 Bucket Keys enabled.

After S3 accepts the write, Document Store must strongly read the exact
returned `VersionId`, compare the exact canonical bytes and digest, and verify
the returned SSE-KMS evidence. Only then may PostgreSQL bind the exact object
key, version and SHA-256 and transition the operation to
`OBJECT_ERASURE_PENDING`. An ambiguous response is reconciled by exact-key or
exact-version reads; a collision, missing version, byte/hash mismatch or
encryption mismatch fails closed. No operator supplies an object key.

The task role permits only:

- `s3:PutObject`, `s3:GetObject` and `s3:GetObjectVersion` on
  `permanent-erasures/v1/*`; and
- S3-mediated `kms:GenerateDataKey` and `kms:Decrypt` on the dedicated journal
  key with the exact bucket encryption context.

It has no journal List, Head, Delete, version-delete, governance-bypass,
bucket-administration or Backup-vault permission. The release operator has no
direct journal data-plane permission. The bucket policy independently denies
insecure transport, missing/wrong SSE-KMS headers, the wrong key and a missing
or disabled bucket-key header.

## Normal erasure and backup-expiry attestation

1. Confirm the request and policy versions are reviewed. Call the owner-scoped
   initiation API with the dedicated retention-administrator token, exact
   owner, operation UUID and complete document UUID set. Never use a browser,
   BFF or account-lifecycle token.
2. Confirm the operation has durably crossed the journal binding before any
   object deletion. If the journal is unavailable, leave the operation
   retryable and do not bypass `JOURNAL_PENDING`.
3. Poll the owner-scoped status while live database metadata, current S3
   versions, noncurrent versions and delete markers are reconciled. A storage
   error remains retryable; do not attest completion while live reconciliation
   is pending.
4. At or after `backupRetentionUntil`, inventory the locked AWS Backup vault,
   RDS automated/manual snapshots and any approved exports or copied recovery
   points. Every copy capable of restoring pre-erasure data must have expired
   or have separately reviewed deletion evidence.
5. Submit the bounded backup-expiry evidence reference through the retention
   API. Document Store stores only the required hashed reference and state; do
   not log or copy raw evidence.
6. Require the readiness response to have schema
   `document-permanent-erasure-readiness.v2`, `enabled:true`, `ready:true`,
   `status:READY`, the exact reviewed policy versions,
   `maximumBackupRetentionDays:35`, and all six counters at zero:
   `recoveryJournalWritePending`, `recoveryJournalEvidenceMissing`,
   `liveErasureReconciliationPending`, `restoreJournalReadPending`,
   `restoreReplayPending` and `backupRetentionPending`.

## Isolated restore replay

Any restored database, bucket or recovery point is hostile until erasure replay
proves otherwise.

1. Restore into a new isolated VPC/security group with no ALB, Route 53,
   service discovery, provider egress or user traffic. Never replace the live
   stack in place.
2. Mount the stable fingerprint primary/previous key ring and exact journal
   configuration. Keep the permanent write fence, normal purge, permanent
   erasure and versioned-object erasure enabled. Startup and readiness must
   fail when any retained verifier lacks its key or journal evidence.
3. The restore scheduler durably records each required journal-read/replay
   request. For each operation, call
   `PUT /internal/retention/v1/permanent-erasures/{operationId}/restore-replays/{restoreReplayId}`
   with the exact owner header, retention-administrator service token and a
   bounded non-secret `evidenceReference`.
4. Document Store reads the server-owned immutable record by its bound key and
   version, verifies bytes/digest/fingerprint, and idempotently re-erases the
   exact database and versioned-S3 scope. The raw journal key, version and
   content are never returned or logged. HTTP 202 remains isolated and
   retryable; HTTP 200 means the replay step is complete, not that restored
   backups have expired.
5. Run reconciliation until journal-read, live-erasure and restore-replay
   pending counts are zero. Keep the candidate isolated through any recreated
   backup horizon and obtain a fresh backup-expiry attestation; never waive or
   shorten the 35-day evidence rule.
6. Run the release preflight and require exact readiness v2 `READY` with all
   six counters zero. Independently prove no exceptional recovery point can
   reintroduce an erased scope.
7. Record the signed restore/replay evidence reference. Only a separate
   reviewed traffic change may then attach DNS/ALB. Missing evidence, a key
   mismatch, a pending counter or a reconciliation error is a hard stop: keep
   the candidate isolated and escalate.

This recovery procedure does not grant the task or operator any permission to
delete the immutable journal or mutate the retained foundation.
