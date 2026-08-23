# AWS public-beta backup and restore

Initial public-beta objectives are a 24-hour recovery-point objective and an
8-hour recovery-time objective. The cross-store recovery guarantee is the
latest verified daily AWS Backup recovery-point window until restore drills
prove tighter consistency. Native RDS point-in-time recovery is deliberately
outside the restricted drill role; using it requires a separate incident
approval and source-resource IAM review. These objectives are operational
targets, not an AWS SLA.

## Protected state

- RDS PostgreSQL automated backups are retained 14 days by default; deletion
  protection, final snapshots and retained automated backups are enabled.
- AWS Backup captures RDS and the versioned documents S3 bucket daily at 05:00
  UTC and retains recovery points 35 days in the KMS-encrypted vault.
- Vault Lock is configured in governance mode with permitted retention between
  7 and 35 days. This is not compliance-mode immutability.
- S3 noncurrent document versions expire after 35 days. Temporary objects
  expire after one day and application-upload quarantine after seven days.
- Terraform state is separately versioned and encrypted in the bootstrap
  bucket; application backups do not include it.
- The Object-Locked permanent-erasure journal is separately versioned and
  encrypted with its own KMS key and is deliberately excluded from the
  customer-data Backup plan/restore blast radius. Document Store is the only
  runtime writer: it must bind the exact immutable S3 key/version/SHA-256
  before live object erasure can begin. Its task policy permits only
  `PutObject`, `GetObject` and `GetObjectVersion` on
  `permanent-erasures/v1/*`, plus S3-mediated `GenerateDataKey`/`Decrypt` on
  the dedicated key. It has no list, delete, governance-bypass or bucket
  administration permission, and the release operator has no direct journal
  data-plane access.
- CloudWatch/S3 operational logs support diagnosis but are not customer-data
  restoration inputs.

The scheduled backup and AWS Backup service restore roles use different
retained permissions boundaries. Their effective permissions are the
intersection of the exact attached AWS Backup managed policies and those
boundaries. The backup boundary names only `jsc-public-beta-postgres`, the
exact documents bucket, exact vault/recovery-point paths, the foundation data
key and AWS Backup-managed EventBridge rules. The service restore boundary
names only `jsc-public-beta-restore-*` RDS identifiers and
`jsc-public-beta-restore-<account>-*` S3 destinations; it cannot restore over
the production database or documents bucket. It deliberately has no
`s3:CreateBucket`, bucket-encryption, bucket-policy or public-access-block
permission, so an AWS Backup job cannot create an under-protected destination.
The boundary retains the AWS-managed restore policies' service-required
`rds:DeleteDBInstance` and `s3:DeleteObject` actions only on those drill
prefixes so AWS Backup can manage its restore lifecycle. It grants neither
version deletion nor bucket deletion and is not the operator cleanup path.

Two additional GitHub OIDC roles keep initiation and destruction separate.
`jsc-public-beta-github-restore-drill`, trusted only from the protected
`production-aws-restore` environment, can inspect tagged recovery points,
create and harden only drill-named buckets, start/observe restore jobs and pass
only `jsc-public-beta-backup-restore` to AWS Backup. It cannot delete the RDS or
S3 destination. `jsc-public-beta-github-restore-cleanup`, trusted only from
`production-aws-restore-cleanup`, cannot start a restore or pass the service
role; it can delete only drill-prefixed RDS destinations and bucket objects,
versions, delete markers, policies and buckets. The guarded workflow uses that
role only with the exact name derived from the confirmed drill ID. These roles
and environments must be created/configured through their separate reviewed
live procedures; their checked-in definitions are not evidence that they exist
in AWS or GitHub.

The reviewed managed-policy defaults and the action set that must survive each
boundary are pinned in
`aws/public-beta/config/aws-backup-managed-policy-contract.json`. Account-free
tests prove the checked-in boundary intersection. Immediately before the first
apply and every release, the trusted release preflight must retrieve each AWS
managed policy's current default version and document and fail closed if it no
longer matches that reviewed contract; an AWS-managed policy update is a
review event, not an automatic permission expansion. The real backup-job and
restore-drill evidence below remains mandatory because static policy analysis
cannot prove the service workflow in the target account.

Backup, copy and restore failures publish to the operations topic. The product
owner owns RPO/RTO approval; the release operator owns job checks and restore
drills; the data-service owners validate semantic consistency.

## Quarterly restore drill

Never test by overwriting a production database or production S3 key.

1. If this is an incident, put the public listener into fixed-`503` mode first.
   For a routine drill, leave production unchanged and record the drill ID,
   owner, start time and intended recovery window.
2. On the exact protected `main`, dispatch `AWS Public Beta Immutable Build`
   with `purpose=restore-candidate`. Record the successful run ID and release
   ID. Candidate validation requires production-shaped images and approvals but
   permits the isolated replay flag/hash alone to remain pending. A candidate
   artifact cannot be passed to the protected release workflow.
3. Select completed, quarterly-tagged RDS and S3 recovery points from the same
   reviewed daily window. Separately provision/review the dedicated no-ingress
   verification security group. The workflow does not create or alter the VPC,
   subnet group, security group or an application verification task.
4. Without changing `main`, manually dispatch `AWS Public Beta Isolated Restore
   Drill` with `action=start`, an 8–32 character drill ID, the candidate build
   run/release IDs, both recovery-point ARNs, the security-group ID and:

   ```text
   START ISOLATED RESTORE DRILL <drill-id>
   ```

   The protected restore-initiator creates the exact
   `jsc-public-beta-restore-<account>-<drill-id>` bucket and verifies its region,
   versioning, `BucketOwnerEnforced`, all four Block Public Access settings,
   default exact-key SSE-KMS, bucket key and TLS/exact-key policy before
   starting either job. The RDS request fixes the private DB subnet group, the
   supplied security group as its sole group and `PubliclyAccessible=false`.
   The S3 request names that already-created bucket as
   `DestinationBucketName`, fixes `RestoreACLs=false`,
   `EncryptionType=SSE-KMS`, the exact foundation data key and
   `RestoreLatestVersionsUpTo=all`, and omits the S3-unsupported
   `CopySourceTagsToRestoredResource` request field. Restoring only
   current/latest objects is not a valid permanent-erasure drill.
5. Retain the uploaded non-secret start artifact, including request hashes,
   candidate bindings and both job IDs. After both jobs finish, dispatch
   `action=observe` with the same drill/security-group IDs, both job IDs and:

   ```text
   OBSERVE ISOLATED RESTORE DRILL <drill-id>
   ```

   Observation verifies completed AWS Backup jobs, private RDS placement and
   destination bucket controls only. It does not run an application task,
   inspect customer/domain data, replay erasures, generate final evidence or
   delete the restore.
6. Through a separately approved ephemeral access path, run the exact candidate
   image against the isolated destinations. Verify all seven logical databases
   and roles, Flyway histories, referential/domain invariants, payment-ledger
   reconciliation and the approved synthetic journey. Verify Document Store
   metadata/object mapping and sampled checksums, then run retention in
   report-only mode. Missing or extra data is an integrity incident. Do not
   attach either destination to the public fleet or record customer payloads.
7. Follow the [permanent-erasure recovery procedure](document-store-permanent-erasure.md)
   to read the external journal and replay exact erasures. Readiness must be
   `document-permanent-erasure-readiness.v3`, `READY`, with journal, live replay
   and `backupRetentionOverdue` blockers at zero. A non-negative
   `backupRetentionPending` is informational for an erasure still inside its
   allowed recovery window and is not required to be zero.
8. Assemble a draft exact `jsc-public-beta-restore-drill-evidence.v1` record
   with the candidate revision/OpenAPI/image digest, completed job timestamps, recovery-
   point skew, isolation, all-version S3 settings, database/document/domain and
   replay results, reviewer, evidence reference and cleanup status. The record
   must cover no more than the 8-hour RTO and contain no credentials or customer
   payloads. Preserve all evidence needed to review the result before deleting
   the isolated destinations; while cleanup is outstanding its truthful status
   is `PENDING_SEPARATE_APPROVAL`.
9. After evidence retention is confirmed, dispatch the distinct cleanup job
   through `production-aws-restore-cleanup` with `action=cleanup` and:

   ```text
   DELETE ISOLATED RESTORE DRILL <drill-id>
   ```

   The deletion-only role removes the exact drill-named RDS instance, then all
   S3 object versions and delete markers before the bucket. It cannot weaken the
   production vault or start another restore. The standalone evidence schema
   permits a truthful draft status of `PENDING_SEPARATE_APPROVAL` because this
   dispatch is separate; that value is not a claim that cleanup occurred. The
   final release validator requires `cleanupStatus=COMPLETED`. After successful
   cleanup, finalise and review/sign the completed evidence. If a pending-status
   record was already signed, retain it and create a new reviewed completion
   record rather than silently editing the signed bytes.
10. SHA-256 the final reviewed evidence bytes, put that digest in
    `documentStorePermanentErasure.restoreDrillEvidenceSha256`, set
    `isolatedRestoreReplayVerified=true`, and supply the same bytes through
    protected `RESTORE_DRILL_EVIDENCE_B64`. Dispatch `AWS Public Beta Immutable
    Build` with `purpose=release`, the same candidate release ID and its build
    run ID. That account-free path re-verifies the candidate attestation and
    promotes its exact image/Frontend digests; it does not rebuild or republish
    images. The final validator requires the evidence hash and exact candidate
    release ID, Infrastructure revision, Document Store revision, OpenAPI hash
    and image digest to match. If they differ, repeat the drill. Only the newly
    attested `buildPurpose=release` promotion artifact may continue to
    prepare/activate.

Before launch, complete at least one drill and the final evidence-bound release
build. A rendered plan cannot prove that the service-linked workflow, KMS grants
and managed-policy intersection work in the target account: activation evidence
must also include one successful real RDS job, one successful real all-version
S3 job, readable recovery points, the isolated semantic/replay result and the
separately tracked cleanup. Repeat quarterly and after material RDS/S3/KMS/
retention/schema changes.

## Incident restoration

Keep the public listener dark. Preserve affected resources and logs, revoke
compromised identities and obtain the owner's recovery-point decision. Restore
new resources first; do not replace production in place. Validate as above,
then update protected Terraform/release inputs to the approved restored
endpoints, run database bootstrap/migration verification/private preflight, and
activate separately.

If database and object-store histories cannot be made consistent, prefer the
last mutually consistent point and document accepted data loss against the
24-hour RPO. Payment ledger inconsistencies block activation. KMS key loss is
not recoverable from ciphertext, so key access and deletion alarms/change
controls are part of backup ownership.
