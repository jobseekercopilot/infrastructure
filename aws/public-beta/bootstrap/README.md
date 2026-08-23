# Public-beta bootstrap boundary

`state-and-oidc.yaml` is a manual, reviewed CloudFormation bootstrap for the
otherwise circular prerequisites of Terraform state and GitHub OIDC. It also
owns retained resources whose AWS-generated IDs make request-tag-based routine
apply unsafe: retained KMS keys, the Object-Locked erasure journal, operations
SNS topic, three account-wide USD 750 Budgets, Backup vault/plan and Cost
Anomaly monitor/subscription. The Budgets intentionally have no cost filter so
tag propagation or an accidentally untagged resource cannot evade alerts. It
is not called by CI or release automation and it does not deploy the
application.
The operations-topic and notification-key policies also permit only the exact
`JobSeekerCopilotAccountEmails` configuration-set ARN to publish SES delivery
events. The normal Terraform root owns that configuration set; bootstrap owns
only the retained notification boundary and the narrowly scoped plan/apply
permissions required to reconcile it.

Before creating a change set, an account administrator must verify the target
account, `eu-west-2`, the unique state bucket name, the existing Route 53 hosted
zone ARN, exact application hostname (used to constrain record mutations),
whether a GitHub OIDC provider already exists, and the current GitHub
OIDC certificate thumbprint from authoritative AWS/GitHub guidance. Review the
complete change set; then execute it manually only after approval.

Supply the immutable GitHub owner and repository IDs as
`GitHubOrganisationId` and `GitHubRepositoryId`. GitHub repositories created
after 15 July 2026 include these IDs in the default OIDC `sub` claim. Confirm
the exact `sub_claim_prefix` with the repository OIDC settings API and do not
substitute the older name-only subject format.

The administrator must also supply the owner mailbox that will receive the
encrypted operations-topic email subscription and either the existing
account-wide AWS-services Cost Anomaly monitor ARN or confirm that none exists.
AWS sends a subscription confirmation email; public activation is blocked
until that confirmation is accepted. The bootstrap reuses an existing
DIMENSIONAL SERVICE monitor because Cost Anomaly Detection permits only one
account-wide AWS-services monitor.

The template is intentionally larger than CloudFormation's 51,200-byte inline
`TemplateBody` limit and smaller than the 1 MiB `TemplateURL` limit. An account
administrator must upload the exact reviewed bytes to a separate, versioned,
SSE-KMS bootstrap-artifact bucket, record the local SHA-256 and immutable S3
version ID, and create the change set from that exact `TemplateURL`. Do not use
the Terraform-state, application-data or erasure-journal buckets for this
upload. Change-set creation must include `CAPABILITY_NAMED_IAM`; without it the
named OIDC roles, boundaries and managed policies are rejected. A representative
manual sequence is:

```bash
sha256sum state-and-oidc.yaml
aws s3api put-object --bucket REPLACE_BOOTSTRAP_ARTIFACT_BUCKET \
  --key reviewed/jsc-public-beta/state-and-oidc.yaml \
  --body state-and-oidc.yaml --server-side-encryption aws:kms \
  --ssekms-key-id REPLACE_BOOTSTRAP_ARTIFACT_KEY_ARN \
  --checksum-algorithm SHA256
aws cloudformation create-change-set \
  --region eu-west-2 --stack-name jsc-public-beta-bootstrap \
  --change-set-name REPLACE_REVIEW_ID \
  --change-set-type CREATE --capabilities CAPABILITY_NAMED_IAM \
  --template-url 'https://REPLACE_BUCKET.s3.eu-west-2.amazonaws.com/reviewed/jsc-public-beta/state-and-oidc.yaml?versionId=REPLACE_VERSION_ID' \
  --parameters file://REPLACE_REVIEWED_PARAMETERS.json
```

These are operator instructions, not an automated apply. Verify the returned
change set, local/object checksums, exact account/region and every named IAM
resource before a separate approved execution. For an update use change-set
type `UPDATE`; never fall back to an unversioned URL or inline template body.
An update that introduces account-email SES support must complete before the
normal `foundation` action, because the prior apply role cannot create or read
the purpose-specific configuration set and the prior encrypted topic/key
policies cannot accept its events.

Record the outputs as protected GitHub environment variables. The current
private-repository billing plan does not support required environment
reviewers. Under the explicitly approved sole-operator fallback, create six
GitHub environments with administrator bypass disabled and a custom
deployment-branch policy that permits only the `main` branch. Retain the exact
`RestoreEnvironmentName=production-aws-restore` and
`RestoreSemanticObserveEnvironmentName=production-aws-restore-observe` and
`RestoreCleanupEnvironmentName=production-aws-restore-cleanup` inputs: those
names are part of the OIDC subjects, workflow checks and signed approval, not
aliases an operator may choose locally.

| Environment | Branch policy | Role output | Purpose |
|---|---|---|---|
| `production-aws-plan` | `main` only | `PlanRoleArn` | refresh-backed release plan; never apply |
| `production-build` | `main` only | `BuildRoleArn` | credential-free source preparation followed by isolated immutable ECR publication |
| `production-aws` | `main` only | `ApplyRoleArn` | reviewed infrastructure apply and one-shot release operations |
| `production-aws-restore` | `main` only | `RestoreDrillRoleArn`, `RestoreSemanticStartRoleArn` | create/protect exact drill buckets and start/observe isolated AWS Backup restores; start/describe only the fixed restore-semantic Standard execution; no destination deletion or direct semantic-task launch |
| `production-aws-restore-observe` | `main` only | `RestoreSemanticObserveRoleArn` | read-only independent restore-semantic observation; no task, state-machine or destination mutation |
| `production-aws-restore-cleanup` | `main` only | `RestoreCleanupRoleArn` | delete only exact drill-prefixed RDS/S3 destinations and all S3 versions; no restore start/pass-role |

Develop and pull-request CI is account-free and receives no OIDC token. A merge
to `develop` therefore cannot plan against or mutate AWS. The protected main
workflow also requires an explicit dispatch and confirmation phrase. For the
current one-person business, the pre-OIDC guard requires the dispatcher to be
the repository owner `jobseekercopilot`. This is an explicitly signed
sole-operator launch decision, not a claim of independent review.
Before any OIDC exchange, each protected workflow calls the GitHub API and
fails closed unless the owner actor, disabled administrator bypass and exact
`main` branch settings are present. The signed `githubEnvironmentProtection`
approval records the HTTP 422 reviewer-plan limitation and the approved
owner-only fallback without claiming an independent reviewer.

ECR repositories deliberately remain owned by the normal Terraform state, not
split between CloudFormation and Terraform. They are created by the protected
`foundation` apply only after this backend/OIDC bootstrap is complete, while
the listener and task counts remain dark. The immutable build/publisher is a
later phase and cannot publish successfully before those exact repositories
exist. This ordered boundary avoids both an uninitialised-backend cycle and an
unreviewed import/split-ownership cycle. GitHub production environments are
also human-created prerequisites: this AWS template cannot create or claim
their branch/reviewer protection.

The restore identities have five deliberately different duties. The GitHub
restore-initiator role is trusted only by `production-aws-restore` and may pass
only `jsc-public-beta-backup-restore` to AWS Backup. That service role remains
constrained by `BackupRestorePermissionsBoundaryArn` to private drill-named
destinations and cannot create the destination bucket. Its boundary retains
the AWS-managed policies' service-required `rds:DeleteDBInstance` and
`s3:DeleteObject` actions only within those prefixes, but not version or bucket
deletion; those service lifecycle actions are not the human cleanup route. The
initiator therefore creates and verifies the exact versioned, public-blocked,
BucketOwnerEnforced, exact-key SSE-KMS bucket before it starts a job, but has no
direct destination-delete actions. The GitHub cleanup role is trusted only by
`production-aws-restore-cleanup`; it has no `backup:StartRestoreJob` or
`iam:PassRole`, and can delete only drill-prefixed RDS instances plus objects,
versions, delete markers, policies and buckets. A separate cleanup dispatch and
typed `DELETE ISOLATED RESTORE DRILL <drill-id>` phrase are required after
evidence retention. The semantic-start role reuses
`production-aws-restore` but can only start/describe the exact bounded Standard
state machine; it has no ECS `RunTask`, `PassRole` or stop authority. The
semantic observer uses the distinct `production-aws-restore-observe` subject
and is read-only. A retained dedicated broker permissions boundary constrains
the state-machine and broker task control-plane roles; it is not the common
workload boundary. Defining these roles here does not update an existing stack:
an administrator must execute a reviewed CloudFormation `UPDATE` change set and
separately configure all three restore GitHub environments before the drill
workflows can use them.

The service-bound apply role deliberately is not an account administrator.
Workload roles must use a bootstrap-created permissions boundary; role
creation, managed-policy attachment and `PassRole` are limited to exact JSC
workload names, allowed policies and target AWS services. Mutating resource
operations use exact JSC ARNs/names or the reviewed Application/Environment/
ManagedBy tags. Only unavoidable discovery/list calls, the ECS account-level
`awsvpcTrunking` setting and condition-limited service-linked-role creation
remain account-scoped. The account-setting call is constrained by
`ecs:account-setting=awsvpcTrunking`. Tagged Cloud Map creation also requires
AWS's standalone, resource-agnostic `servicediscovery:TagResource` dependent
action. That call is limited to the exact protected request tags and allowed
tag keys; the apply role has no Cloud Map update, delete or untag action, so
tagging an opaque pre-existing resource cannot unlock a destructive lifecycle.
The protected saved-plan verifier also refuses Cloud Map service deletion or
replacement before apply. Any abandoned namespace/service is therefore a
manually reviewed cleanup after its ownership, registrations and ECS
dependencies have been proved safe.

Cloud Map services deliberately omit an empty `health_check_custom_config`
while AWS provider 6.55 is pinned. The provider does not materialise that empty
block and subsequently proposes a ForceNew replacement on every refresh. ECS
task/container health and service registration remain the runtime health
boundary; adding Cloud Map custom-health filtering requires an explicit,
reviewed migration rather than deploy-role delete permission.

Apply has two inline policies: the exact state-object access and explicit
non-removable state/tag/boundary guardrails. Their realistically rendered
aggregate is checked below IAM's 10,240-character role limit. Ten separately
named customer-managed policies are attached, each tested after realistic
eu-west-2/account ARN rendering below the 6,144-character policy quota and at
(not above) the ten-attachment role quota. The reviewed ECS AMI is a bootstrap
input; `RunInstances` is restricted to that AMI, the tagged launch
template/network, the lean `m7i.2xlarge` shape, IMDSv2, private networking and
encrypted gp3 volumes. ASG creation/update additionally requires protected
explicit tags, a numeric launch-template version and min/max one. Apply has no
policy create/version/default/delete actions, so it cannot mutate those policy
documents. Opaque foundation resources have `Retain`/`UpdateReplacePolicy:
Retain`; changing or removing them requires another administrator-reviewed
CloudFormation change set, never a normal Terraform apply.

Before Terraform attaches or passes any reserved workload role, the protected
release must list all `jsc-public-beta-*-task` and `*-execution` roles and the
fixed instance/monitoring/backup/operator roles. An unexpected wildcard match,
wrong permissions-boundary ARN or non-exact trust policy is a hard stop; a
planned role may be absent only when Terraform is about to create it. The apply
identity can read those roles but is explicitly denied permission-boundary
removal. This live collision check is required because AWS does not expose a
supported permissions-boundary condition for `iam:PassRole`.

RDS Enhanced Monitoring is intentionally excluded from the common application
boundary. Its AWS-managed service-role policy writes the account-owned
`RDSOSMetrics` CloudWatch Logs group, whereas the common boundary permits only
`/jsc/public-beta/*`. The retained
`RdsMonitoringPermissionsBoundary` allows only the six required log-group and
log-stream actions against the exact regional/account `RDSOSMetrics` ARNs. The
RDS role trust is additionally limited by `SourceAccount` and the full
`jsc-public-beta-postgres` DB ARN.

For an existing stack that still has the common boundary and `db:*` trust on
`jsc-public-beta-rds-monitoring`, migration order is mandatory:

1. Merge the reviewed infrastructure change through `develop`, then promote
   that exact tested revision to `main`.
2. From the `main` revision, upload the exact bootstrap bytes to versioned,
   encrypted S3 and execute a reviewed CloudFormation `UPDATE` change set. It
   must create `RdsMonitoringPermissionsBoundary` and update the exact apply
   policies; it must not create, replace or edit the Terraform-owned RDS role.
3. Record `RdsMonitoringPermissionsBoundaryArn`, then dispatch the dark
   `foundation` action. Its pre-apply IAM check first proves the live default
   boundary document contains exactly the six approved actions and two
   `RDSOSMetrics` resources. It permits only the byte-exact old
   common-boundary/`db:*` role, or the retry-safe intermediate with that old
   boundary and the already-narrowed exact DB trust, as one-way migration
   states.
4. Approve only an in-place role-boundary/trust update and
   `MonitoringInterval=60`; reject DB or role replacement. After apply, the
   workflow repeats the exact IAM check without the migration exception and
   observes six consecutive live RDS samples while rejecting any Enhanced
   Monitoring failure event emitted since apply began.

Do not dispatch `prepare` or `activate` between steps 2 and 4. Do not manually
remove the old boundary or change the live role to bypass the saved plan.

RDS-managed master credentials are the only dependent authorization whose
secret name is generated by AWS (`rds!db-*`). Creation is coupled to the exact
`jsc-public-beta-postgres` RDS action and application KMS key. RDS's dependent
tag-on-create action is necessarily limited to the regional `rds!db-*` ARN
shape because the final secret ID and system tags do not exist yet; it grants
no secret read/update/delete. Subsequent rotation and reads require RDS
ownership plus the exact primary-DB ARN. Effective
operator access remains the intersection of its exact inline policy and its
permissions boundary.

The retained erasure-journal bucket is separate from the documents bucket and
uses a separate retained KMS key, versioning and Object Lock. Only the Document
Store task receives the matching data-plane grant: conditional `PutObject` and
version-bound `GetObject`/`GetObjectVersion` under
`permanent-erasures/v1/*`, plus S3-mediated `GenerateDataKey`/`Decrypt` using
the exact bucket encryption context. It receives no list, head, delete,
governance-bypass or bucket-control action. The release operator has no direct
journal read/write grant; recovery goes through the authenticated, owner-scoped
Document Store retention API and its durable scheduler.

## Protected environment inputs

Bootstrap outputs establish only the trust boundary. An owner separately
records these non-secret variables and protected inputs; no bootstrap template
or workflow invents their values.

The Apply role permits a six-hour maximum session so the measured ~2h42m RDS
on-demand backup can follow ordered private migration/quiescence in one protected
`prepare-restore-source` job. The workflow requests that duration only for this
action. GitHub-hosted jobs have a hard six-hour limit, so the mutation step is
capped at five hours. The remaining outer window covers checkout/init and
reserves 30 minutes for fail-closed containment; an exact candidate/canary retry
resumes the idempotent jobs if the bounded step expires. Normal apply mutations
retain three-hour sessions and job bounds.

| Environment | Name | Kind | Purpose |
|---|---|---|---|
| all six | `AWS_ACCOUNT_ID` where used | variable | exact 12-digit target account |
| `production-build` | `AWS_BUILD_ROLE_ARN` | variable | `BuildRoleArn` output |
| `production-build` | `RELEASE_READER_APP_ID` | variable | contents-read-only cross-repository GitHub App |
| `production-build` | `RELEASE_READER_APP_PRIVATE_KEY` | secret | GitHub App private key; never an AWS key |
| `production-build` | `POSTGRES_IMAGE_BY_DIGEST` | variable | reviewed PostgreSQL 15 Alpine digest |
| `production-build` | `RDS_CA_BUNDLE_URL` / `RDS_CA_BUNDLE_SHA256` | variables | official trust bundle and reviewed checksum |
| `production-build` | `LANDING_RUNTIME_ENV_B64` | protected secret | exact reviewed non-secret Landing generation JSON |
| build, plan and apply | `LAUNCH_APPROVALS_B64` | protected secret | byte-identical reviewed approval JSON; signed hash must match |
| build, plan and apply | `RESTORE_DRILL_EVIDENCE_B64` | protected secret | exact reviewed non-secret restore/replay evidence; required for final `purpose=release`, plan and mutations, and SHA-256-bound by the launch approval |
| `production-aws-plan` | `AWS_PLAN_ROLE_ARN` | variable | `PlanRoleArn` output |
| `production-aws` | `AWS_APPLY_ROLE_ARN` | variable | `ApplyRoleArn` output |
| `production-aws` | restore-source evidence artifact | workflow output | non-secret exact candidate/canary marker, actual paired recovery-point tags/job metadata and hashes; never customer payloads |
| `production-aws` | `WORKLOAD_PERMISSIONS_BOUNDARY_ARN` | variable/evidence | `WorkloadPermissionsBoundaryArn`; must match standard Terraform workload roles |
| `production-aws` | `RDS_MONITORING_PERMISSIONS_BOUNDARY_ARN` | variable/evidence | `RdsMonitoringPermissionsBoundaryArn`; must match only the Enhanced Monitoring service role |
| `production-aws` | `BACKUP_PERMISSIONS_BOUNDARY_ARN` / `BACKUP_RESTORE_PERMISSIONS_BOUNDARY_ARN` | variables/evidence | exact specialised bootstrap boundary outputs for scheduled backup and isolated restore roles |
| `production-aws` | `RESTORE_SEMANTIC_BROKER_PERMISSIONS_BOUNDARY_ARN` | variable/evidence | exact retained `RestoreSemanticBrokerPermissionsBoundaryArn`; used only by the semantic state-machine and broker task roles |
| plan and apply | `TF_STATE_BUCKET` / `TF_STATE_KMS_KEY_ARN` | variables | bootstrap state outputs |
| plan and apply | `foundation_data_kms_key_arn` | protected tfvars | `ApplicationDataKeyArn` bootstrap output |
| plan and apply | `foundation_operations_topic_arn` | protected tfvars | `OperationsTopicArn` bootstrap output |
| plan and apply | `foundation_backup_plan_id` | protected tfvars | `CustomerDataBackupPlanId` bootstrap output |
| plan and apply | `foundation_erasure_journal_kms_key_arn` | protected tfvars | `ErasureJournalKeyArn` bootstrap output |
| plan and apply | `foundation_erasure_journal_bucket_name` | protected tfvars | `ErasureJournalBucketName` bootstrap output |
| plan and apply | `foundation_erasure_journal_retention_days` | protected tfvars | exact reviewed `ErasureJournalRetentionDays` input/output |
| plan and apply | `foundation_approved_ecs_ami_id` | protected tfvars | `ApprovedEcsAmiId`; must equal the reviewed `ecs_ami_id` |
| plan and apply | `foundation_monthly_alert_budget_usd` | protected tfvars | exact retained `MonthlyAlertBudgetUsd` output; default and current public-beta ceiling are USD 750 |
| plan and apply | `PUBLIC_BETA_TFVARS_B64` | protected secret | reviewed non-secret Terraform input file |
| `production-aws-restore` | `AWS_RESTORE_DRILL_ROLE_ARN` | variable | exact `RestoreDrillRoleArn` output; restore initiation/observation only |
| `production-aws-restore` | `AWS_RESTORE_SEMANTIC_START_ROLE_ARN` | variable | exact `RestoreSemanticStartRoleArn`; start/describe only the fixed bounded semantic state machine |
| restore and cleanup | `AWS_BACKUP_RESTORE_ROLE_ARN` | variable | exact `arn:aws:iam::<account>:role/jsc-public-beta-backup-restore`; passed only by initiation and checked as an invariant by cleanup |
| `production-aws-restore` | `AWS_DATA_KMS_KEY_ARN` | variable/evidence | exact `ApplicationDataKeyArn` output used to protect the workflow-created pre-restore bucket |
| `production-aws-restore-observe` | `AWS_RESTORE_SEMANTIC_OBSERVE_ROLE_ARN` | variable | exact `RestoreSemanticObserveRoleArn`; independent read-only semantic observation |
| `production-aws-restore-observe` | `AWS_DATA_KMS_KEY_ARN` | variable/evidence | exact `ApplicationDataKeyArn` used only to compare restored destination controls |
| `production-aws-restore-cleanup` | `AWS_RESTORE_CLEANUP_ROLE_ARN` | variable | exact `RestoreCleanupRoleArn` output; deletion-only drill cleanup |

GitHub secrets are used for access control/redaction even where the payload is
not a credential. Runtime service credentials do not belong in any item in this
table. Rotate the GitHub App key independently, require environment review for
every change, and record only checksums in release evidence.

The workflow's prepare job deliberately has no OIDC permission. It may use the
environment's read-only GitHub App and non-secret protected configuration, then
passes a one-day checksum-bound Docker archive to a second job. Only that
publisher job requests `BuildRoleArn`, and it runs no repository build/test
code.
