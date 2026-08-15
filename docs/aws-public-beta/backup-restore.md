# AWS public-beta backup and restore

Initial public-beta objectives are a 24-hour recovery-point objective and an
8-hour recovery-time objective. RDS automated backups/PITR may provide a newer
database point, but the cross-store recovery guarantee remains the latest
verified daily AWS Backup recovery points until restore drills prove tighter
consistency. These objectives are operational targets, not an AWS SLA.

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
- CloudWatch/S3 operational logs support diagnosis but are not customer-data
  restoration inputs.

Backup, copy and restore failures publish to the operations topic. The product
owner owns RPO/RTO approval; the release operator owns job checks and restore
drills; the data-service owners validate semantic consistency.

## Quarterly restore drill

Never test by overwriting a production database or production S3 key.

1. Put the public listener into fixed-`503` mode if this is an incident; record
   the time and intended recovery point.
2. Select RDS and S3 recovery points from the same completed daily window, or
   document why a PITR database point is consistent with the selected S3
   versions.
3. Use the protected restore role to restore to an isolated, private test RDS
   identifier and a new isolated S3 destination/prefix. Apply production-like
   encryption and public-access blocks.
4. Allow access only from an ephemeral, audited verification task. Do not
   attach restored data to the public fleet.
5. Verify all seven logical databases/roles, Flyway histories, row counts,
   referential/domain invariants and payment-ledger reconciliation.
6. Verify sampled Document Store metadata maps to readable, checksum-valid S3
   objects; run retention/reconciliation in report-only mode. Treat missing or
   extra documents as an integrity incident.
7. Exercise login/profile, application tracking and document retrieval against
   the isolated environment with approved synthetic or restored test records.
8. Record recovery-point age, elapsed restore time, evidence and gaps without
   recording credentials or customer payloads.
9. Delete the isolated restore through an approved, recoverable clean-up change
   after evidence retention is confirmed. Do not weaken the production vault.

Before launch, complete at least one drill. Repeat quarterly and after material
RDS/S3/KMS/retention/schema changes.

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
