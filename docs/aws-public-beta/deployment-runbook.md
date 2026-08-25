# AWS public-beta deployment runbook

This runbook is a release contract, not permission to deploy. Checked-in
CloudFormation, workflows, tests and documentation do not prove that any AWS
resource, GitHub environment, restore drill or evidence record exists in the
live account. AWS bootstrap/update, GitHub environment configuration, every
Terraform mutation, each restore/cleanup dispatch and public activation remain
separate reviewed live actions.

## Release states

```text
not bootstrapped
    -> dark foundation (no application tasks, ALB returns 503)
    -> digest-verified restore candidate
    -> isolated restore/replay evidence and separate cleanup
    -> evidence-bound exact-candidate release promotion
    -> private prepared fleet (all tasks healthy, ALB still returns 503)
    -> public exact release
    -> dark maintenance / private rollback / public previous release
```

Merging `develop` cannot reach AWS: its CI has no OIDC token and uses a local
Terraform backend with dummy credentials. Merging `main` also does not deploy.
Only a manual dispatch on `main`, through one of the exact protected GitHub
environments and its API-verified owner-only fallback, can assume the matching
bootstrap-created role. That fallback is explicitly approved because the
current private-repository plan does not provide the desired required-reviewer
control; it is not described as independent review or no-self-approval.

## 1. Bootstrap the account boundary

An AWS account administrator, not the release workflow, owns this one-time
step.

1. Read [`aws/public-beta/bootstrap/README.md`](../../aws/public-beta/bootstrap/README.md).
2. Confirm the target account and `eu-west-2`; resolve the current GitHub OIDC
   certificate thumbprint from authoritative AWS/GitHub guidance.
3. Hash `bootstrap/state-and-oidc.yaml`, upload those exact bytes to a separate
   versioned/SSE-KMS bootstrap-artifact bucket, and create a CloudFormation
   **change set** using the immutable S3 `TemplateURL`, recorded object version
   and `CAPABILITY_NAMED_IAM`. The template exceeds the 51,200-byte inline body
   limit; an inline or unversioned submission is invalid. Follow the exact
   manual command/evidence contract in the bootstrap README. Do not execute an
   unreviewed template.
4. Confirm it creates only the KMS-encrypted/versioned/public-blocked state
   bucket, GitHub OIDC provider/roles, workload permissions boundary and the
   retained data/notification/journal keys, Object-Locked erasure journal,
   operations topic, Backup vault/plan, reviewed ECS AMI input and Cost Anomaly
   controls listed in the bootstrap README. These foundation resources are
   deliberately outside routine Apply authority.
5. Execute the approved change set manually. Record the outputs in the six
   GitHub environments described in the bootstrap README. For an existing
   bootstrap stack, the restore roles/outputs require a reviewed `UPDATE`
   change set; a repository merge does not create them.
6. Protect `production-build`, `production-aws-plan`, `production-aws`,
   `production-aws-restore`, `production-aws-restore-observe` and
   `production-aws-restore-cleanup` for `main` only and disable administrator
   bypass. The current private-repository plan
   returns HTTP 422 for required reviewers, so the approved sole-operator
   fallback requires `jobseekercopilot` to be the workflow actor before OIDC is
   issued. Record all six API-visible settings and the plan limitation in the
   signed `githubEnvironmentProtection` approval block.
7. Request/validate the exact `app.<domain>` ACM certificate through the
   separately reviewed account process and record its eu-west-2 ARN as
   `existing_certificate_arn`. Terraform certificate creation is intentionally
   disabled because ACM deletion cannot be safely constrained by resource tag;
   the apply role has no ACM write permission.

Never put runtime secret values in CloudFormation, Terraform variables,
Terraform state, GitHub variables, logs or release artifacts. The protected
`PUBLIC_BETA_TFVARS_B64`, `LAUNCH_APPROVALS_B64`,
`RESTORE_DRILL_EVIDENCE_B64` and `LANDING_RUNTIME_ENV_B64` inputs contain
reviewed configuration/attestations, not credentials. Build and release must
use byte-identical launch approvals; their SHA-256 is signed into the release
manifest. Restore evidence is separately SHA-256-bound by that approval and is
required only after the candidate drill has produced reviewed evidence.

## 2. Prove release prerequisites

Complete the [launch checklist](launch-checklist.md). In particular:

- merge the Document Store task-role change represented by commit
  `1183ce5a54ab60999ca37d826ceb16857d5763ff` and the exact Adzuna/JSearch
  health-command changes represented by `594ac33862c6360fe05768905bab0e2cb9ac1898`
  and `79677c6586207f5aa30b9c6d0720f5ed2cfe728a` into each service's `develop`,
  then into its reviewed `main` release;
- include the tested Postcodes NI/BT licensing-gate commit
  `f5588e5b0a2ca9e63319674f4b6cd40048b9e0fb`, Location Service commit
  `4d8d09a79018c3f281cfead84348d14ed84be851` and Location Gateway commit
  `86b2805c8430ede14a53a7320b87f0eeb2797b17`, with exported OpenAPI SHA-256
  `0cd7a877836dfbf1a42b5f71e0a807ec8dc99f88d69a695d7c5734e320cdef27`
  and `30d71d6b2508c7cbd452b522c30c26bfa7a571e1f1ebcda979008422db469cfc`
  respectively. Authentication payment-lifecycle evidence is pinned to
  `d447addae21714f51267c0ab073377c24e3cfe81` and OpenAPI SHA-256
  `8ef5f12a32e836c2046fb163944b62d76cea31e389612408ca6ed1d1ccc42884`,
  while UMG export/lifecycle evidence is exact locked main `15e6bed692352f92daccc295c3987319e18ef720`
  with OpenAPI SHA-256 `ebb1332f8927cdb69dd659db444627e59c4f5d8f4330e04d95ed17164fb8bcf7`
  and Auth snapshot SHA-256
  `95811cb81b0c32ad2f9c5cc42cd8f85c0385359cdade6c0f9e67e3ed63950dc0`.
  The final payment chain is Document Generation Gateway
  `e15784c7098d327835e2a7d14dd257c1b95b08bd`, Payment Service
  `baeec9aa8da1285a2406900c9550773ac3841af7`, Payment Gateway
  `99ee685a6809a254305a4cbb4dd92ba0fa7751bc`, and Stripe Gateway
  `04dd9fa7c095f65120afd37cfc11380176756216`, each bound to the exact exported
  OpenAPI hash in the manifest. The release builder proves every reviewed SHA
  is an ancestor of the locked image before setting the capability true. It
  separately ancestor-verifies the isolated signed-settlement acceptance
  evidence: System Data `ca4bafeafbfe41b25a8507f6f08d97490ef71a28`, E2E
  `cfa1a70a0028f11f8019c889b9057ba8124ff8f5` and Infrastructure
  `412566a750ead55740e0b2b4b81cebe29d3e0ad9`, which proved 36 healthy services
  and 4/4 scenarios (33/33 steps). Those are test-only provenance: System Data
  and E2E remain absent from production tasks/ECR/ALB. Stripe's single reviewed
  JAR contains dormant fixture classes; the exact-image gate instead proves the
  production profile rejects `FIXTURE`, `DISABLED` registers no conditional
  fixture control/provider beans and returns 404 for the control route. No
  fixture token/signing secret enters a production task or public OpenAPI;
- update `config/workspace-lock.json` to the tested release revisions,
  including LLM Gateway `d84427061766244ec10e367fb3a7a6587809612c`
  and Client `72936c0b76df0d616a110ed77c481d55eebaa5c8`;
- prove the pinned Client/Landing revisions and artifact-contract SHA-256 values
  are ancestors of protected `main`. The protected build replaces the generated
  Landing static/runtime-config/SAM `PENDING` hashes. Client remains one SSR/BFF
  OCI artifact; Landing remains a non-deployed static/config/SAM evidence bundle;
- bind the protected Client legal-artifact checksum to
  `040e208e49e9b12d8504fc3fe2b4f9ccd864f6a0d209475b77881e8b44b77b30`;
- pin an official RDS CA bundle URL and SHA-256, and prove every DB-owning
  image plus the release operator has that exact file at
  `/etc/jsc/rds/global-bundle.pem`;
- pin the reviewed London AL2023 ECS-optimised AMI and upstream container
  digests; and
- keep every integration disabled unless its non-secret approval metadata,
  quota, cost ceiling, attribution obligations and separately supplied secret
  are complete. Credentials never count as approval.
- keep the application at desired count zero until the protected public-legal
  record contains the real reviewed seller identity, explicit tax/ICO status,
  published Terms/Privacy URLs, exact immutable Client/Landing legal-artifact
  checksums, and bounded deletion/retention values. Its `legalVersion` must
  exactly match Authentication, Client and the
  Payment terms/entity configuration; `NOT_CONFIGURED` is intentionally dark.
  Account/document deletion promises must be at least the configured 35-day
  backup/noncurrent recovery window.

The release builder checks out only the workspace-lock revisions, builds all
27 application images, runs the exact-image health-client/non-root capability
checks, verifies the RDS CA bundle, scans the images, publishes digests and
emits a non-secret immutable manifest. Service CI owns endpoint-level image
health tests. Placeholder, mutable, unscanned or `develop` manifests fail closed.
The seven DB images get the same checksum-bound CA bundle in one central derived
image step; the operator independently verifies the identical checksum. The
release workflow fail-closes on GitHub's immutable artifact SHA-256 and verifies
build-run identity, exact `main` SHA, workspace-lock checksum, protected approval checksum,
every locked exported OpenAPI checksum and Client/Landing artifact checksums
before assuming AWS access.
The source-build job has no GitHub OIDC permission and rejects AWS credentials.
It exports the verified local images as a checksum-bound, one-day prepared
archive. A separate publisher job verifies and loads (but does not execute)
that archive before assuming the build-only role; no repository test/build code
runs with AWS credentials.

## 3. Create the dark foundation

This is the only phase allowed before immutable images exist. Manually dispatch
`AWS Public Beta Protected Release` from `main` with:

```text
action: foundation
confirmation: FOUNDATION public-beta
```

Before this first foundation run, manually execute the reviewed bootstrap
`UPDATE` from the same protected `main` revision. The account-email change adds
only exact SES read/manage permissions and exact SES publisher statements on
the retained operations topic/notification key. Without that update, the
normal apply must fail closed rather than broadening its own authority.

Review the refresh-backed plan in the protected environment. The plan must
show `application_desired_count=0` and `public_entrypoint_enabled=false`.
Confirm the expected lean shape, cost tags, single-node ASG bound and no
unexpected replacement before approval. Foundation creates empty secret
containers and ECR repositories; it does not seed secrets or start tasks.

If the reviewed ECS AMI or launch-template inputs changed, confirm the ASG is
bound to the new numeric launch-template version and the proposed instance
refresh remains `0/100` in lean mode or `50/100` in the separately approved HA
mode. The protected-instance behavior must be `Refresh`, because ECS managed
termination protection marks nodes with tasks as scale-in protected. Managed
draining must remain enabled. Lean host replacement has a maintenance outage;
HA drains one of two hosts at a time and never launches a temporary third host.
Do not approve a refresh that falls back to `Wait`, references `$Latest`, or
increases the ASG maximum. If the automatic host refresh/rollback fails, keep
the listener dark and investigate before any application activation.

Confirm the operations SNS subscription, that all three USD 750 budgets have
no cost filter, the available billing cost-allocation tags, and DNS/certificate
state. Account-wide budgets are intentional: tag discovery or an accidentally
untagged resource must not hide spend. Foundation creates the purpose-specific
`JobSeekerCopilotAccountEmails` configuration/event destination, then performs
the read-only SES/SNS/KMS verification described in
[account-email delivery](../account-email-ses.md). It sends no email. Keep the
ALB fixed at `503`.

For the first release after the dedicated RDS monitoring-boundary change,
update the manual bootstrap from the exact promoted `main` bytes before this
dispatch, following the ordered migration in the bootstrap README. The
foundation plan must update `jsc-public-beta-rds-monitoring` in place from the
common boundary to `jsc-public-beta-rds-monitoring-boundary`, tighten its trust
from `db:*` to the full `jsc-public-beta-postgres` ARN and leave the DB itself
unreplaced. The preflight verifies the bootstrap-owned boundary's live default
document exactly; a missing or broadened policy is a hard stop. If an apply is
interrupted after trust narrows but before its boundary changes, the next
foundation preflight accepts only that exact safer intermediate so Terraform
can retry. A successful Terraform apply is not sufficient evidence: the
workflow must then pass the exact post-migration IAM check and its live RDS
stability/event verifier at `MonitoringInterval=60`.

## 4. Build a restore candidate, drill, then promote the exact release

The restore gate deliberately requires two immutable workflow purposes. A
`restore-candidate` is built/published before live recovery is exercised. It
can never enter the normal `prepare`, `activate` or rollback paths; its sole
live use is the protected, dark `prepare-restore-source` action below. After reviewed restore/replay evidence is
signed and checksum-bound, `release` promotes that exact candidate manifest and
digests without rebuilding or calling AWS.

The sole initial-public-beta exception is explicit and time-bounded. The
protected approval may contain an approved
`initialPublicBetaRecoveryException` for no more than seven days, with a named
owner, approval timestamp, P0 tracking reference, justification, compensating
controls and `maximumApplicationDesiredCount=1`. It may defer only the isolated
RDS/S3 restore, semantic replay and checksum-bound restore evidence. Retained
backup/journal controls, encryption, fixed scaling ceilings, cost protection,
legal/payment gates, private preparation, smoke tests and emergency darkening
remain mandatory. Under that active exception the exact digest-verified candidate may
be promoted without `RESTORE_DRILL_EVIDENCE_B64`; the approval must keep
`isolatedRestoreReplayVerified=false` and `restoreDrillEvidenceSha256=""` and
must not claim completed evidence. Complete the drill before expiry, replace
the exception with the real evidence hash, and promote the same exact candidate
digests again. An expired exception blocks every subsequent plan or mutation.

1. On exact protected `main`, prepare a reviewed launch approval in which every
   production prerequisite is complete except the not-yet-run drill:
   `isolatedRestoreReplayVerified=false` and
   `restoreDrillEvidenceSha256=""`. Manually dispatch `AWS Public Beta Immutable
   Build` with `purpose=restore-candidate`. Record its run and release IDs and
   verify the fail-closed artifact SHA-256 plus accompanying provenance; the latter
   must say `buildPurpose=restore-candidate`.
2. From the same unchanged `main`, dispatch `AWS Public Beta Protected Release`
   in `production-aws` with `action=prepare-restore-source`, the candidate
   run/release IDs, a new 8–32 character canary ID and exact confirmation
   `PREPARE RESTORE SOURCE <release-id> <canary-id>`. This exceptional mode
   applies the candidate dark, bootstraps all seven logical databases, starts
   the private fleet only long enough to apply/verify Flyway migrations, then
   stops every service again. With the live listener proven fixed `503`, a
   dedicated least-privilege task writes and re-reads one checksum-bound row in
   every database plus two distinct versions of one controlled, non-customer S3
   object. A second invocation verifies those exact rows/versions after the
   fleet is quiesced. Only then may the apply role start paired on-demand RDS/S3
   backups in the exact customer-data vault using the exact boundary-constrained
   backup role. The workflow checks actual recovery-point tags and uploads
   `public-beta-restore-source-<release-id>-<canary-id>` evidence. An existing
   exact marker is verified and reused; backup idempotency is marker-hash-bound,
   and the bounded backup poll allows four hours (the first live RDS backup took
   about 2h42m). The protected source action alone requests a six-hour Apply-role
   session and uses the GitHub-hosted runner's hard six-hour job limit. Its
   mutation step is capped at five hours, reserving the outer window for
   checkout/init plus the bounded 30-minute containment step; ordinary mutations
   retain three-hour sessions. A timeout can be resumed by re-dispatching the exact
   candidate/canary without rewriting source state or selecting an older backup.
   This path requires `additional_tags={}` so the measured inherited RDS tag set
   remains exact. Any failure while the temporary private fleet is starting,
   migrating or seeding triggers an `always()` containment step that keeps the
   edge fixed `503` and drains every application/scanner service.
3. Apply and review the Terraform-owned restore database, semantic child and
   broker security groups before the drill. Their rules are static: the restored
   database accepts only PostgreSQL from the semantic group; semantic tasks have
   only that database path, exact S3 gateway-prefix HTTPS, VPC DNS and same-group
   port 8089; the secret-free broker has control-plane HTTPS and DNS. Verify the
   three restore GitHub environments and exact bootstrap role variables. Take
   the recovery-point ARNs only from successful source evidence. RDS uses the
   native `arn:aws:rds:...:snapshot:awsbackup:job-*` shape; S3 uses
   `arn:aws:backup:...:recovery-point:*`.
4. From the same unchanged `main`, dispatch `AWS Public Beta Isolated Restore
   Drill` with `action=start`, the exact candidate run/release IDs, source
   preparation run/canary IDs, its exact paired recovery points, and
   `START ISOLATED RESTORE DRILL <drill-id>`. After both jobs complete, dispatch
   `action=observe` with the successful restore-start run ID and their job IDs and
   `OBSERVE ISOLATED RESTORE DRILL <drill-id>`. The start path creates/hardens
   the exact drill bucket and requests every S3 object version with
   `RestoreLatestVersionsUpTo=all`; observe verifies exact source/job/role/
   destination binding, private RDS placement, ownership/cost tags and bucket controls.
   Because RDS restores inherit source tags, start first establishes the five
   canonical drill tags, removes only the five measured production-only keys,
   and rejects any other unexpected non-AWS key before exact verification.
5. Obtain explicit owner approval for the drill's retained synthetic Object
   Lock journal record, then dispatch `AWS Public Beta Restore Semantic
   Verification` with `action=start`, the exact restore-start run ID and
   `START RESTORE SEMANTIC VERIFICATION <drill-id>`. The protected start role can
   only start/describe the exact bounded Standard state machine; it has no
   `ecs:RunTask`, `iam:PassRole` or stop authority. The state machine fixes the
   secret-free broker task revision, private subnets, broker security group,
   roles, command and tags. The broker in turn fixes every child task revision,
   role, command, synthetic credential, tag and semantic security group. It
   verifies no semantic ENI exists before launch, clones restored
   `document_store` while quiescent, and runs the exact candidate image against
   the restored source database and its pre-operation clone. A durable tagged
   SSM tombstone reserves the drill/operation namespace; never delete or reuse
   it. Failed bounded attempts may be redriven only with the same exact input,
   and every prior child must be stopped before the next attempt. The start job
   holds the shared `jsc-public-beta-aws-mutation` concurrency group until the
   Standard execution reaches a bounded terminal or explicit redrive state. An
   administrator-triggered Step Functions redrive outlives that GitHub lock;
   while it is active, do not dispatch any production release, restore or
   cleanup mutation. Resume only after the redrive is terminal and exact task
   containment has been proved. Redrive never reclones after the immutable
   operation identity has been used: it permits only an untouched clone, the
   exact same source operation with an untouched clone, or the exact same
   canonical source/replay pair. Both APIs and their idempotent retries run
   again and must retain one journal version; extra rows/scopes/requests or any
   changed operation, replay or journal binding fail closed.

   After the Standard execution is terminal, dispatch the same workflow with
   `action=observe`, its successful semantic-start run ID and
   `OBSERVE RESTORE SEMANTIC VERIFICATION <drill-id>`. The separate read-only
   observer binds the stopped broker/child tasks, exact task definitions,
   images, roles, static network, restore jobs/destinations and broker-issued
   `RunTask` CloudTrail requests. It requires the source canary in all seven
   databases and exactly two restored destination versions with new distinct
   VersionIds, zero delete markers and exact generation metadata, sizes and
   payload SHA-256 values. It then validates empty-bootstrap domain/payment
   invariants and the real application-path synthetic empty-scope erasure:
   exactly one immutable journal version across source retry, absent-operation
   reconstruction from the pre-operation clone, replay retry, and readiness v3
   `READY` with one in-window `backupRetentionPending`, zero overdue and zero
   actual blockers. This proves non-customer journal write/read/reconstruction
   and restored-canary version integrity. It does **not** claim customer object
   erasure, customer metadata/object mapping or aggregate Document Store object
   health; liveness, startup and Flyway are the only health claims.
6. Assemble a draft exact `jsc-public-beta-restore-drill-evidence.v1` record. It
   binds the candidate Document Store revision, OpenAPI SHA-256 and image
   digest, same-window completed jobs, isolation and all-version S3 controls,
   the source-evidence/marker hashes, seven-database, source-two-version and
   restored-two-generation counts, zero restored delete markers, verified
   generation payloads and `sourceVersionIdsPreserved=false`, the explicit
   synthetic/non-customer scope limitations and independently observed
   broker/runtime/network bindings, semantic verification, replay/readiness
   results, RPO/RTO timing, reviewer,
   evidence reference and truthful cleanup status. The workflow does not
   assemble or sign this record; retain the supporting material outside
   customer payloads and use `PENDING_SEPARATE_APPROVAL` until cleanup succeeds.
   Pairing is measured from recovery-point creation/start timestamps (maximum
   ten minutes), not completion timestamps; each job still has its own eight-hour
   completion bound.
7. Preserve the evidence. If containment must be repeated before deletion,
   dispatch `AWS Public Beta Restore Semantic Verification` with
   `action=contain` and `CONTAIN RESTORE SEMANTIC VERIFICATION <drill-id>`.
   The cleanup identity cannot stop the Standard execution: it refuses until
   the exact execution is terminal, then stops and proves zero exact pending or
   running broker/child tasks. Next dispatch the isolated restore workflow
   through `production-aws-restore-cleanup` with `action=cleanup`, the exact
   semantic-start run ID and
   `DELETE ISOLATED RESTORE DRILL <drill-id>`. This deletion-only path removes
   the exact drill RDS target plus every S3 object version/delete marker and the
   exact bucket. `observe`, evidence validation and a later release build do not
   perform cleanup. If evidence was signed while
   `cleanupStatus=PENDING_SEPARATE_APPROVAL`, keep that residual live action
   tracked until a new reviewed completion record exists. Cleanup retains both
   the durable SSM tombstone and the synthetic locked journal version; their
   retention is intentional namespace/provenance protection, not an incomplete
   ephemeral-resource cleanup. After successful deletion, finalise and
   review/sign the evidence with
   `cleanupStatus=COMPLETED`; do not silently edit already signed bytes.

   Omit the semantic-start run ID only if semantic verification was never
   started. The workflow then proves the deterministic Standard execution and
   permanent marker absent, zero drill-tagged broker/child tasks and ENIs, and
   exact terminal bindings for both AWS Backup restore jobs before allowing
   deletion. Any execution, marker, task or uncertain restore state fails
   closed and requires the original semantic-start artifact. This path never
   launches the synthetic immutable-journal operation merely to clean an
   isolated restore.
8. Hash the exact final reviewed evidence bytes. Update the protected approval
   to `isolatedRestoreReplayVerified=true` and set
   `restoreDrillEvidenceSha256` to that non-zero SHA-256; supply the same bytes
   as `RESTORE_DRILL_EVIDENCE_B64` in build, plan and apply environments. Now
   manually dispatch `AWS Public Beta Immutable Build` with `purpose=release`,
   the same candidate release ID and the candidate build run ID. This path
   downloads and re-verifies the candidate artifact SHA-256, changes only the
   approval/evidence binding and provenance, and emits a newly digest-bound final
   artifact without AWS credentials, image rebuilding or ECR publication. Its
   validator requires the evidence bytes to match the approval hash and the
   exact candidate release ID, Infrastructure revision, Document Store
   revision, OpenAPI SHA-256 and image digest to match the promoted manifest.
   Any mismatch requires a new candidate/drill rather than an edited
   artifact substitution or bypass.

Only the promoted artifact, whose provenance says `buildPurpose=release` and
whose `promotedFrom` block hashes the digest-verified restore-candidate manifest, may
continue below. It must contain the image manifest, release metadata and
digests for every application, ClamAV and release operator, plus the
deterministic Landing static tar, Landing metadata and exact selected SAM
template. Verify every Landing checksum, `deploymentStatus=NOT_DEPLOYED` and
`scanStatus=PASSED` for every image entry. The protected Landing legal/runtime
configuration must match the same launch approval. Artifact generation performs
no Amplify, SAM, DNS or other Landing deployment;
`AMPLIFY_RELEASE_AUTHORISED` remains absent/false. Preserve the artifact for the
later coordinated Landing promotion described in
[landing integration](landing-integration.md).

The build role can publish ECR images; it cannot change ECS, databases,
networking, restore resources or the public listener. Reject either build if
the workspace lock, source revisions, RDS bundle evidence or required
dependency evidence differs from the reviewed inputs.

All images are pushed first so their per-repository scans can run concurrently;
the publisher then verifies every result before it can emit the digest-bound candidate
manifest. If candidate publication or scanning fails after an immutable tag was
pushed, that release ID is failed and must never be reused. Diagnose it and
create a new candidate release ID; unreferenced candidate/failed images remain
subject to the reviewed ECR lifecycle. A promotion failure makes no AWS call or
new image; correct the final evidence/approval input and promote the same exact
candidate only if its protected-main/source bindings remain valid.

## 5. Seed and prepare privately

Supply external credentials one integration at a time with
`put-external-secret.sh` from an owner-only `0400` or `0600` JSON input after
that integration is approved. Do not enable it yet. Core tokens, JWT keys and
seven database-user passwords are generated/idempotently preserved by the
protected release operator; values are never returned in workflow output.

For Stripe, store only the live runtime secret/restricted key and live endpoint
signing secret in `jsc-public-beta/integration/stripe`. Record the safe,
permanent Product and Price identifiers in `integrations.stripe.liveStripeCatalog`
in the protected approval manifest. Terraform injects only the three approved
Price IDs into Stripe Gateway. Live readiness fails closed if an ID is missing,
malformed, duplicated or not bound to the approved catalogue evidence.

Dispatch `prepare` with the exact build artifact and:

```text
confirmation: PREPARE <release-id>
```

The script deliberately performs these steps in order:

1. scales every application and scanner service to zero and keeps the listener dark;
2. re-verifies live SES identity/DKIM/suppression/event publication without
   sending email;
3. seeds missing core/database secret versions;
4. verifies the expected ECS nodes, `awsvpcTrunking` registration, private
   subnet IP headroom, and registered CPU, memory and branch-ENI capacity;
5. runs an idempotent database bootstrap task to create/repair exactly seven
   roles and logical databases with least-privilege ownership;
6. records the exact database-bootstrap release marker;
7. renders the whole private-fleet plan;
8. starts and proves the isolated no-task-role ClamAV scanner fleet (one per
   reviewed node) before any document path;
9. starts application services one at a time in reviewed dependency/build
   order, waiting for each to stabilise;
10. converges the full private desired-count-one stack;
11. verifies every service's Flyway history over hostname-verified TLS; and
12. runs private health/preflight, then records the exact release marker.

The one-node beta cannot schedule old and new copies of the complete fleet.
Stop-first `0/100` deployment and ordered service starts are intentional in
both the lean and reviewed HA shapes: HA autoscaling may already consume two
copies per service, so a `200%` replacement would exceed the two-node capacity
contract. This phase has a maintenance window and must never be described as
zero downtime.
If any step fails, leave the listener dark, capture redacted ECS/RDS/CloudWatch
evidence and repair or roll back; do not skip markers or start services before
database bootstrap.

## 6. Activate separately

Before activation, the release owner must name and approve one tester
account/mailbox they control for the single real password-reset delivery. Do
not infer the recipient from support/contact configuration and do not record
its address or reset token in evidence. If the controlled journey cannot be
completed through the reviewed real application path, keep the listener dark;
do not send directly with the AWS CLI as a substitute for Authentication
Service behavior.

Review an `action=plan` dispatch for desired count `1` and public entrypoint
`true`. Verify the exact release ID is both the database-bootstrap and
preflight SSM marker, targets are healthy, alarms are `OK`, backups succeeded,
provider/payment/email approvals remain current and the WAF three-path
body-size-exception tests pass.
Confirm provenance says `buildPurpose=release`, the supplied restore evidence
matches the SHA-256 in the protected launch approval, and its candidate-bound
Document Store revision, OpenAPI hash and image digest still match this final
manifest. A plan or mutation refuses a missing, unsafe or mismatched evidence
file; do not substitute the earlier restore-candidate artifact.
Confirm the Client source/digest and Landing source/static/config/SAM evidence
still match the digest-bound artifact. This activates only the application stack; the
Landing artifact remains undeployed until its separate reviewed promotion.
The activation build SHA must equal current protected `main`. If `main` changed
after private prepare—even for infrastructure-only work—build and prepare again;
an ancestor artifact is accepted only by the stop-first rollback path.

Only then dispatch:

```text
action: activate
confirmation: ACTIVATE <release-id>
```

Smoke-test registration/email, login, job search, document upload/generation/
download, account lifecycle and live checkout/webhook/reconciliation using the
approved test accounts. Observe ALB 5xx/latency, ECS health, RDS connections,
free memory/storage, backup status, provider quotas and spend.

## Rollback and emergency dark mode

For an application rollback, select a last-known-good immutable build whose
infrastructure revision is still an ancestor of current protected `main`, then
dispatch:

```text
action: rollback
confirmation: ROLLBACK <previous-release-id>
```

Rollback uses the same dark, stop-first, database-bootstrap, ordered-start,
migration-history and preflight process. Activate the previous release only
with a separate `ACTIVATE <previous-release-id>` dispatch. Flyway migrations
are never automatically reversed; an incompatible schema change needs an
approved forward fix or documented restore decision.

The workflow verifies the old build run, fail-closed artifact SHA-256, release ID, its own
historical workspace-lock checksum and ancestry before AWS credentials are
assumed. If the current Terraform/runtime contract no longer accepts that
artifact, do not bypass the gate: prepare a reviewed forward-fix release or
revert the incompatible infrastructure change through the normal `main` path.

For immediate containment, dispatch `darken` with confirmation
`DARKEN <current-release-id>`. The workflow proves the supplied ID is the
currently applied release from remote-state outputs, changes both the Stripe
webhook rule and HTTPS listener default to fixed `503`, verifies those edge
changes, suspends any ECS dynamic/scheduled scaling and lowers its minima to
zero, then drains all 27
application services while preserving RDS, S3, logs and recovery points.

This emergency path deliberately requires neither the retained build artifact
nor a currently valid commercial/legal approval manifest: an expired or
revoked approval must never block containment. It performs no Terraform plan
or general reconciliation. It is still `main`-only, uses the required-reviewer
`production-aws` environment and binds the typed release ID to the currently
applied state before mutation. After the incident, keep traffic dark and use a
normal reviewed release/rollback to reconcile the deliberate listener/service
drift. Rotate affected credentials and follow
[backup/restore](backup-restore.md) when integrity is uncertain.

## Provider and cost response

Reed, Adzuna and JSearch start disabled and need written commercial approval.
Postcodes GB and NI are separate decisions. The gateway receives
`POSTCODES_IO_NORTHERN_IRELAND_ENABLED=false` unless the NI approval is
complete, and the immutable build itself remains blocked until the service's
pre-provider-call `BT` rejection is represented by exact dependency evidence.
NHS Jobs and DfE apprenticeships can be
enabled independently after their own reviews. Google Maps has a separate GCP
project/quota/budget gate and is not required for hosting. It cannot be enabled
until `googleBillingQuotasVerified=true` names exact billable quota IDs and
limits, records 50/75/90/100% GCP budget alerts and assigns an emergency-disable
owner/runbook. Those alerts are not a hard cap. Stripe, OpenAI and
SES each have additional readiness metadata. A secret alone never unlocks any
of them.

The USD 750 AWS Budget is an alert threshold, not a hard cap. On an 80% forecast
or material anomaly, keep activation dark or place the site into maintenance,
identify the tagged driver, and obtain a new cost approval before changing the
one-node/NAT/RDS/retention bounds. See [cost controls](cost-controls.md).
