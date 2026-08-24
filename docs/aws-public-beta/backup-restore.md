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

The initial low-traffic public beta may launch before this first drill only
under the protected, owner-approved `initialPublicBetaRecoveryException`. The
exception lasts no more than seven days, caps the application at one task,
names its P0 tracking item and compensating controls, and cannot weaken backup,
journal, encryption, cost, ingress or emergency-darkening controls. It must
leave the replay flag false and evidence checksum empty rather than claiming a
test that did not occur. Expiry blocks later release plans/mutations until this
drill is complete and the approval is replaced by checksum-bound evidence.

1. Put the public listener into fixed-`503` mode and record the maintenance
   window, drill ID, owner, start time and intended recovery window. Source
   preparation deliberately starts the private fleet and then quiesces it; it
   is never an online zero-downtime drill.
2. On the exact protected `main`, dispatch `AWS Public Beta Immutable Build`
   with `purpose=restore-candidate`. Record the successful run ID and release
   ID. Candidate validation requires production-shaped images and approvals but
   permits the isolated replay flag/hash alone to remain pending. A candidate
   artifact cannot enter normal release prepare/activation; only the exceptional
   dark source-preparation action may consume it.
3. Dispatch the protected release workflow with
   `action=prepare-restore-source`, the exact candidate run/release IDs, a new
   canary ID and `PREPARE RESTORE SOURCE <release-id> <canary-id>`. It keeps the
   listener fixed `503`, bootstraps seven databases, privately applies and
   verifies Flyway, quiesces every service, then writes and independently
   re-verifies a controlled cross-database marker and two checksum-bound S3
   object versions. Only after those live preconditions pass does the exact-vault
   `StartBackupJob` path start paired RDS/S3 jobs through the existing
   boundary-constrained backup role. Preserve the uploaded source-evidence
   artifact and its actual recovery-point tags. The poll is bounded at four
   hours because the measured first RDS backup took about 2h42m; this is distinct
   from the eight-hour recovery objective. The protected source action has a
   five-hour mutation-step ceiling inside the GitHub-hosted runner's hard
   six-hour job limit and six-hour role session. This leaves real headroom for
   checkout/init plus the bounded 30-minute containment step. The protected
   preparation rejects non-empty Terraform `additional_tags`, keeping the
   measured RDS copied-tag set deterministic. If
   any private-start, migration or canary step fails, the workflow's `always()`
   containment fixes the edge at `503` and drains every application/scanner
   service before the failed run ends. If the bounded poll expires,
   re-run the exact candidate/canary: the marker and jobs are idempotently reused.
4. Select only the completed recovery points named by that source evidence.
   Their creation timestamps—not their potentially very different completion
   timestamps—must be within ten minutes, and each job must complete within the
   eight-hour RTO. Before the drill, apply/review the Terraform-owned dedicated
   restored-database, semantic-child and secret-free-broker security groups.
   Their static SG-reference, S3 gateway-prefix and DNS rules are part of the
   isolation proof; no GitHub OIDC identity may authorize or revoke them.
5. Without changing `main`, manually dispatch `AWS Public Beta Isolated Restore
   Drill` with `action=start`, an 8–32 character drill ID, the candidate build
   run/release IDs, source-preparation run/canary IDs, both recovery-point ARNs,
   the security-group ID and:

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
   current/latest objects is not a valid permanent-erasure drill. RDS can copy
   source tags regardless of the request's copy-tags flag. As soon as the exact
   destination ARN appears, start writes the five canonical drill ownership/cost
   tags, removes only the measured source-only `Name`, `Repository`, `DataClass`,
   `Backup` and `BetaBlocker` keys through a tag-conditioned permission, and
   verifies that no unexpected non-AWS tag remains.
6. Retain the uploaded non-secret start artifact, including request hashes,
   candidate bindings and both job IDs. After both jobs finish, dispatch
   `action=observe` with the same drill/security-group IDs, the successful exact
   restore-start workflow run ID, both job IDs and:

   ```text
   OBSERVE ISOLATED RESTORE DRILL <drill-id>
   ```

   Observation verifies each job against the exact start artifact, source
   recovery point/resource/vault, restore role and destination; it also verifies
   private RDS placement and both destinations' ownership/cost/security tags and
   bucket controls. It does not run an application task,
   inspect customer/domain data, replay erasures, generate final evidence or
   delete the restore.
7. Obtain explicit owner approval for one retained synthetic, non-customer
   Object Lock journal record. Dispatch `AWS Public Beta Restore Semantic
   Verification` with `action=start`, the exact restore-start run ID and
   `START RESTORE SEMANTIC VERIFICATION <drill-id>`. GitHub can start/describe
   only the exact Standard state machine. Its fixed-network, secret-free broker
   fixes every child task definition revision, role, command, tag and synthetic
   credential; direct OIDC `RunTask`/`PassRole` is forbidden. The broker clones
   restored `document_store` before mutation, runs the exact candidate on the
   restored source database, and runs the replay against that pre-operation
   clone. The durable SSM marker is a permanent operation-namespace tombstone;
   do not delete it or reuse the drill ID. The start job retains the shared AWS
   mutation concurrency lock through the bounded execution. If an administrator
   redrives the execution after that job returns a redrive state, run no release,
   restore or cleanup mutation until the redrive is terminal and contained. A
   redrive never drops or recreates the replay database after the immutable
   operation identity has been used. It accepts only the untouched clone, the
   exact same source operation with an untouched clone, or the exact same
   canonical source/replay operation pair; it then repeats both APIs and their
   retries and still requires one unchanged journal version. Any other row,
   scope, request, operation/replay ID or journal binding is a hard failure.
8. After the bounded execution is terminal, dispatch the same workflow with
   `action=observe`, the semantic-start run ID and
   `OBSERVE RESTORE SEMANTIC VERIFICATION <drill-id>`. The read-only observer
   independently binds the exact state-machine execution, stopped broker and
   four child tasks, task definitions/images/roles, fixed network and every
   broker `RunTask` CloudTrail request. It verifies the source marker row in all
   seven logical databases and exactly two restored versions of the canary key.
   AWS Backup assigns new destination VersionIds, so never require equality with
   source IDs. Require two distinct destination IDs, zero delete markers and the
   exact generation payloads, metadata, sizes and source SHA-256 values.

   The application-path test creates an empty-scope synthetic erasure on the
   restored source database, proves its immutable journal version is not
   rewritten by retry, then reconstructs the absent operation from that journal
   on the pre-operation clone and proves replay retry. Readiness must be
   `document-permanent-erasure-readiness.v3`, `READY`, with one in-window
   `backupRetentionPending`, zero overdue and all actual blockers zero. This is
   non-customer journal write/read/reconstruction evidence, not proof of
   customer object erasure or customer metadata/object mapping. Aggregate
   Document Store object health is intentionally not claimed; liveness, startup
   and Flyway are. Missing, extra or mismatched evidence is an integrity
   incident. No destination is attached to the public fleet and no customer
   payload is recorded.
9. Assemble a draft exact `jsc-public-beta-restore-drill-evidence.v1` record
   with the candidate revision/OpenAPI/image digest, source-evidence/marker
   hashes and seven-database/source-two-version/restored-two-generation counts,
   `restoredDeleteMarkerCount=0`, `restoredGenerationPayloadsVerified=true` and
   `sourceVersionIdsPreserved=false`, completed job timestamps,
   maximum ten-minute recovery-point creation skew, isolation, all-version S3 settings, database/document/domain and
   replay results, reviewer, evidence reference and cleanup status. The record
   must cover no more than the 8-hour RTO and contain no credentials or customer
   payloads. Preserve all evidence needed to review the result before deleting
   the isolated destinations; while cleanup is outstanding its truthful status
   is `PENDING_SEPARATE_APPROVAL`.
10. After evidence retention is confirmed, optionally repeat exact containment
   with semantic `action=contain` and
   `CONTAIN RESTORE SEMANTIC VERIFICATION <drill-id>`. It cannot stop a running
   Standard execution and refuses until that execution is terminal; it then
   proves no exact broker/child task remains pending or running. Dispatch the
   distinct restore cleanup job through `production-aws-restore-cleanup` with
   `action=cleanup`, the semantic-start run ID and:

   ```text
   DELETE ISOLATED RESTORE DRILL <drill-id>
   ```

   The semantic-start run ID may be omitted only when semantic verification
   was never started. That recovery-only path derives the deterministic
   execution name from the exact restore-start evidence and refuses deletion
   unless the Standard execution and permanent marker are both absent, no
   drill-tagged broker or child task/ENI exists, and both exact AWS Backup jobs
   are bound to their approved recovery point, role and destination and have
   reached a terminal state. Any semantic execution, marker, task or uncertain
   restore-job state requires the original semantic-start artifact; cleanup
   never launches the WORM-producing semantic path merely to delete an
   otherwise isolated restore.

   The deletion-only role removes the exact drill-named RDS instance, then all
   S3 object versions and delete markers before the bucket. It cannot weaken the
   production vault or start another restore. The standalone evidence schema
   permits a truthful draft status of `PENDING_SEPARATE_APPROVAL` because this
   dispatch is separate; that value is not a claim that cleanup occurred. The
   final release validator requires `cleanupStatus=COMPLETED`. Cleanup does not
   delete the permanent SSM tombstone or retained synthetic locked journal
   version. After successful cleanup, finalise and review/sign the completed
   evidence. If a pending-status
   record was already signed, retain it and create a new reviewed completion
   record rather than silently editing the signed bytes.
11. SHA-256 the final reviewed evidence bytes, put that digest in
    `documentStorePermanentErasure.restoreDrillEvidenceSha256`, set
    `isolatedRestoreReplayVerified=true`, and supply the same bytes through
    protected `RESTORE_DRILL_EVIDENCE_B64`. Dispatch `AWS Public Beta Immutable
    Build` with `purpose=release`, the same candidate release ID and its build
    run ID. That account-free path re-verifies the candidate artifact SHA-256 and
    promotes its exact image/Frontend digests; it does not rebuild or republish
    images. The final validator requires the evidence hash and exact candidate
    release ID, Infrastructure revision, Document Store revision, OpenAPI hash
    and image digest to match. If they differ, repeat the drill. Only the newly
    digest-bound `buildPurpose=release` promotion artifact may continue to
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
