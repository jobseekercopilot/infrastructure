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

The scheduled backup and isolated restore roles use different retained
permissions boundaries. Their effective permissions are the intersection of
the exact attached AWS Backup managed policies and those boundaries. The
backup boundary names only `jsc-public-beta-postgres`, the exact documents
bucket, exact vault/recovery-point paths, the foundation data key and AWS
Backup-managed EventBridge rules. The restore boundary names only
`jsc-public-beta-restore-*` RDS identifiers and
`jsc-public-beta-restore-<account>-*` S3 destinations; it cannot restore over
the production database or documents bucket. It deliberately has no
`s3:CreateBucket`, bucket-encryption, bucket-policy or public-access-block
permission, so an AWS Backup job cannot create an under-protected destination.

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

1. Put the public listener into fixed-`503` mode if this is an incident; record
   the time and intended recovery point.
2. Select RDS and S3 recovery points from the same completed daily window.
3. Before `StartRestoreJob`, create the empty S3 destination through a separate
   reviewed infrastructure change. Its name must match
   `jsc-public-beta-restore-<account>-*`, it must be in `eu-west-2`, and it must
   have versioning `Enabled`, `BucketOwnerEnforced`, all four Block Public
   Access controls true, default SSE-KMS with the exact foundation data-key
   ARN, and TLS/exact-key bucket-policy enforcement. Record the outputs of
   `get-bucket-location`, `get-bucket-versioning`,
   `get-bucket-ownership-controls`, `get-public-access-block`,
   `get-bucket-encryption` and `get-bucket-policy-status`; fail if any value is
   absent or different. The restore role cannot create or weaken this bucket.
4. Use the protected restore role to restore to an isolated private RDS target
   named `jsc-public-beta-restore-*` with the exact reviewed parameter/subnet
   groups, an isolated VPC security group and `PubliclyAccessible=false`.
   Restore S3 to the pre-created destination with metadata
   `DestinationBucketName=<exact bucket>`, `NewBucket=false`,
   `EncryptionType=SSE-KMS`, `KMSKey=<exact foundation data-key ARN>` and
   `RestoreACLs=false`. AWS documents metadata keys as case-insensitive; retain
   the exact request and job ID as evidence without customer payloads.
5. Allow access only from an ephemeral, audited verification task. Do not
   attach restored data to the public fleet.
6. Verify all seven logical databases/roles, Flyway histories, row counts,
   referential/domain invariants and payment-ledger reconciliation.
7. Verify sampled Document Store metadata maps to readable, checksum-valid S3
   objects; run retention/reconciliation in report-only mode. Treat missing or
   extra documents as an integrity incident.
8. Exercise login/profile, application tracking and document retrieval against
   the isolated environment with approved synthetic or restored test records.
9. Record recovery-point age, elapsed restore time, evidence and gaps without
   recording credentials or customer payloads.
10. Delete the isolated restore through an approved, recoverable clean-up change
   after evidence retention is confirmed. Do not weaken the production vault.

Before launch, complete at least one drill. A rendered plan cannot prove that
the service-linked workflow, KMS grants and managed-policy intersection work in
the target account: activation evidence must also include one successful real
RDS job, one successful real S3 job, readable recovery points, and the isolated
restore result. Repeat quarterly and after material RDS/S3/KMS/retention/schema
changes.

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
