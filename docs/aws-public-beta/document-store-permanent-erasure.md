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
   `document-permanent-erasure-readiness.v3`, `enabled:true`, `ready:true`,
   `status:READY`, the exact reviewed policy versions and
   `maximumBackupRetentionDays:35`. The blocking counters
   `recoveryJournalWritePending`, `recoveryJournalEvidenceMissing`,
   `liveErasureReconciliationPending`, `restoreJournalReadPending`,
   `restoreReplayPending` and `backupRetentionOverdue` must all be zero.
   `backupRetentionPending` is a non-negative informational count for erasures
   still inside their permitted recovery window; it does not by itself block
   readiness. Once an attestation is due, an unattested item is overdue and
   must be represented by `backupRetentionOverdue`, which does block readiness.

## Isolated restore replay

Any restored database, bucket or recovery point is hostile until erasure replay
proves otherwise. The repository supplies a guarded restore control plane; it
does not prove that the protected GitHub environments, bootstrap roles,
isolated network, application verification task or reviewed evidence exist in
the live account.

1. On the exact protected `main`, dispatch `AWS Public Beta Immutable Build`
   with `purpose=restore-candidate`. This production-shaped build may leave
   only `isolatedRestoreReplayVerified=false` and
   `restoreDrillEvidenceSha256=""` pending. Record its run ID and release ID.
   It is a drill input, not an artifact that the normal release workflow may
   prepare, activate or roll back. Its only live release action is the dark,
   candidate-bound source preparation below.
2. Dispatch `AWS Public Beta Protected Release` with
   `action=prepare-restore-source`, the exact candidate run/release IDs, a new
   canary ID and `PREPARE RESTORE SOURCE <release-id> <canary-id>`. The workflow
   must prove fixed-`503` ingress, bootstrap/migrate all seven databases, quiesce
   the private fleet, write/re-read two checksum-bound versions of one controlled
   S3 object and matching rows in every database, and complete paired backups.
   Preserve the source-evidence artifact and use only its recovery points.
3. Provision and review the dedicated no-ingress restore security group before
   the drill. The automated RDS request uses the existing private
   `jsc-public-beta-postgres` DB subnet group, that security group as its sole
   security group and `PubliclyAccessible=false`; it does not create a new VPC
   or network controls. Do not attach the restored database or bucket to the
   ALB, Route 53, service discovery, providers or the public fleet.
4. From the same unchanged protected `main`, dispatch `AWS Public Beta Isolated
   Restore Drill` with `action=start`, the attested candidate run/release IDs,
   source-preparation run/canary IDs, its exact canary-bound RDS/S3 recovery
   points, the
   security-group ID and exact confirmation
   `START ISOLATED RESTORE DRILL <drill-id>`. The
   `production-aws-restore` environment assumes the restore-initiator role,
   which creates and verifies the exact versioned, ACL-free, public-blocked,
   SSE-KMS destination bucket and passes only
   `jsc-public-beta-backup-restore` to AWS Backup. The S3 request names that
   pre-created destination, fixes `RestoreACLs=false` and
   `RestoreLatestVersionsUpTo=all`, and omits the S3-unsupported source-tag copy
   field; a latest-only restore is invalid.
5. After both jobs complete, dispatch `action=observe` with the successful exact
   restore-start workflow run ID, their exact job IDs, the same security-group ID and
   `OBSERVE ISOLATED RESTORE DRILL <drill-id>`. This proves only the AWS Backup
   job/source/role/destination binding, private RDS placement, exact restore
   ownership/cost tags and destination-bucket controls. It does
   not run Document Store, replay erasures, validate domain data, sign evidence
   or clean up resources.
6. Through a separately reviewed, ephemeral and audited verification path,
   mount the stable fingerprint primary/previous key ring and exact journal
   configuration on the candidate Document Store image. Keep the permanent
   write fence, normal purge, permanent erasure and versioned-object erasure
   enabled. Startup and readiness must fail when any retained verifier lacks
   its key or journal evidence.
7. The restore scheduler durably records each required journal-read/replay
   request. For each operation, call
   `PUT /internal/retention/v1/permanent-erasures/{operationId}/restore-replays/{restoreReplayId}`
   with the exact owner header, retention-administrator service token and a
   bounded non-secret `evidenceReference`.
8. Document Store reads the server-owned immutable record by its bound key and
   version, verifies bytes/digest/fingerprint, and idempotently re-erases the
   exact database and versioned-S3 scope. The raw journal key, version and
   content are never returned or logged. HTTP 202 remains isolated and
   retryable; HTTP 200 means the replay step is complete, not that restored
   backups have expired.
9. Run database, document and payment/domain verification plus reconciliation
   only after the exact marker SHA/row exists in all seven restored databases
   and exactly two restored versions of the canary key have distinct new
   destination VersionIds, zero delete markers, and match the source generation payloads, metadata,
   sizes and SHA-256 values. AWS Backup does not preserve source VersionIds; use
   those only as source provenance, never as a destination equality check. Then
   continue until the journal-write/evidence, journal-read, live-erasure and replay
   blocking counts are zero. Run the release preflight and require exact
   readiness v3 `READY` with `backupRetentionOverdue=0`. A non-negative
   `backupRetentionPending` may remain while the corresponding erasures are
   still inside the 35-day recovery window; separately prove there is no
   already-overdue or exceptional recovery point capable of reintroducing an
   erased scope.
10. Assemble a draft exact `jsc-public-beta-restore-drill-evidence.v1` record. It
   must bind the candidate Document Store revision, OpenAPI SHA-256 and image
   digest, canary source-evidence/marker hashes, completed RDS/S3 jobs,
   all-version S3 controls, exact restored-two-generation payload verification,
   `sourceVersionIdsPreserved=false`, the maximum ten-minute recovery-point creation skew
   (not completion skew), isolation, seven-database/domain/document checks, replay/
   readiness v3 results and the truthful cleanup status. Preserve the evidence
   needed for review without customer data; while cleanup is outstanding use
   `PENDING_SEPARATE_APPROVAL`.
11. Preserve evidence, then separately dispatch `action=cleanup` through
    `production-aws-restore-cleanup` with
    `DELETE ISOLATED RESTORE DRILL <drill-id>`. Its distinct deletion-only role
    deletes only the exact drill-named RDS target and every version/delete
    marker in the exact drill bucket before deleting that bucket. Neither
    `observe` nor evidence validation performs cleanup; a recorded
    `PENDING_SEPARATE_APPROVAL` remains an outstanding live action. After
    successful cleanup, finalise and review/sign the evidence with
    `cleanupStatus=COMPLETED` and retain its signed evidence reference. Never
    silently edit an already signed pending-status record; issue a new reviewed
    completion record.
12. Hash the final reviewed evidence bytes into
    `documentStorePermanentErasure.restoreDrillEvidenceSha256`, set
    `isolatedRestoreReplayVerified=true`, and supply the same bytes as protected
    `RESTORE_DRILL_EVIDENCE_B64`. Only then dispatch `AWS Public Beta Immutable
    Build` with `purpose=release`, the same candidate release ID and candidate
    build run ID. That account-free path re-verifies the candidate attestation
    and promotes its exact manifest/image/Frontend digests without rebuilding
    or publishing to ECR. Its new provenance must say `buildPurpose=release`
    and hash-bind the `restore-candidate` source in `promotedFrom`; the promoted
    manifest receives a new GitHub build-provenance attestation. Validation
    checksum-binds the evidence through the launch approval and requires its
    release ID, Infrastructure revision, Document Store revision, OpenAPI hash
    and image digest to match. Any mismatch requires a new drill, not an edited
    attestation or bypass.
13. Use only that final attested release artifact for the normal private
    prepare and separate activation. Missing evidence, a key/digest mismatch,
    an overdue/blocking counter, a reconciliation error or an uncompleted
    required cleanup is a hard stop; keep the restore isolated and escalate.

This recovery procedure does not grant the task or operator any permission to
delete the immutable journal or mutate the retained foundation.
