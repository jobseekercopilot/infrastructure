# AWS public-beta deployment runbook

This runbook is a release contract, not permission to deploy. At the time it
was written, no Job Seeker Copilot public-beta resource had been created by
this work. AWS account bootstrap, every Terraform mutation and public
activation require separate human approval.

## Release states

```text
not bootstrapped
    -> dark foundation (no application tasks, ALB returns 503)
    -> private prepared fleet (all tasks healthy, ALB still returns 503)
    -> public exact release
    -> dark maintenance / private rollback / public previous release
```

Merging `develop` cannot reach AWS: its CI has no OIDC token and uses a local
Terraform backend with dummy credentials. Merging `main` also does not deploy.
Only a manual dispatch on `main`, through a protected GitHub environment with a
required reviewer and no self-approval, can assume a bootstrap-created role.

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
5. Execute the approved change set manually. Record the outputs in the three
   GitHub environments described in the bootstrap README.
6. Protect `production-build`, `production-aws-plan` and `production-aws` for
   `main` only, require a reviewer other than the dispatcher, and disable
   administrator bypass. Record the settings-page evidence in the signed
   `githubEnvironmentProtection` approval block because GitHub's environment
   REST response does not expose that switch.
7. Request/validate the exact `app.<domain>` ACM certificate through the
   separately reviewed account process and record its eu-west-2 ARN as
   `existing_certificate_arn`. Terraform certificate creation is intentionally
   disabled because ACM deletion cannot be safely constrained by resource tag;
   the apply role has no ACM write permission.

Never put runtime secret values in CloudFormation, Terraform variables,
Terraform state, GitHub variables, logs or release artifacts. The protected
`PUBLIC_BETA_TFVARS_B64`, `LAUNCH_APPROVALS_B64` and
`LANDING_RUNTIME_ENV_B64` inputs contain reviewed configuration/attestations,
not credentials. Build and release must use byte-identical launch approvals;
their SHA-256 is signed into the release manifest.

## 2. Prove release prerequisites

Complete the [launch checklist](launch-checklist.md). In particular:

- merge the Document Store task-role change represented by commit
  `1183ce5a54ab60999ca37d826ceb16857d5763ff` and the exact Adzuna/JSearch
  health-command changes represented by `594ac33862c6360fe05768905bab0e2cb9ac1898`
  and `79677c6586207f5aa30b9c6d0720f5ed2cfe728a` into each service's `develop`,
  then into its reviewed `main` release;
- include the tested Postcodes NI/BT licensing-gate commit
  `f5588e5b0a2ca9e63319674f4b6cd40048b9e0fb`, Location Service commit
  `91857140c71bfda8b807c535272f918fe7741263` and Location Gateway commit
  `777ec7e8885fcb07368e05ad2543181e4ef7a891`, with their exact exported
  OpenAPI hashes. Authentication payment-lifecycle evidence is pinned to
  `d447addae21714f51267c0ab073377c24e3cfe81` and OpenAPI SHA-256
  `8ef5f12a32e836c2046fb163944b62d76cea31e389612408ca6ed1d1ccc42884`,
  while UMG export/lifecycle evidence is `5dc8aa1e7afb9492a96d3dedde847c530b6209b0`
  with OpenAPI SHA-256 `dde3349e015f2cd7ef7bf9bc810681bebe98fca1ed1510005aa0b1a8b0e6d08e`
  and Auth snapshot SHA-256
  `95811cb81b0c32ad2f9c5cc42cd8f85c0385359cdade6c0f9e67e3ed63950dc0`.
  The final payment chain is Document Generation Gateway
  `cd9b71a3d4dbfbe41d6784f3eeeb7b1b113f5218`, Payment Service
  `63a2f3f2c6e29bb2d2744124c4b1ebe3a3b895ff`, Payment Gateway
  `c49f9dc7441d146e58b428793a9c1a833c24aec5`, and Stripe Gateway
  `0e84d1bd97a00194809322307682c557069f30d4`, each bound to the exact exported
  OpenAPI hash in the manifest. The release builder proves every reviewed SHA
  is an ancestor of the locked image before setting the capability true. It
  separately ancestor-verifies the isolated signed-settlement acceptance
  evidence: System Data `ca4bafeafbfe41b25a8507f6f08d97490ef71a28`, E2E
  `1541d92f34a3068bb160e1638834a06af6a60796` and Infrastructure
  `412566a750ead55740e0b2b4b81cebe29d3e0ad9`, which proved 36 healthy services
  and 4/4 scenarios (33/33 steps). Those are test-only provenance: System Data
  and E2E remain absent from production tasks/ECR/ALB. Stripe's single reviewed
  JAR contains dormant fixture classes; the exact-image gate instead proves the
  production profile rejects `FIXTURE`, `DISABLED` registers no conditional
  fixture control/provider beans and returns 404 for the control route. No
  fixture token/signing secret enters a production task or public OpenAPI;
- update `config/workspace-lock.json` to the tested release revisions;
- prove the pinned Client/Landing revisions and artifact-contract SHA-256 values
  are ancestors of protected `main`. The protected build replaces the generated
  Landing static/runtime-config/SAM `PENDING` hashes. Client remains one SSR/BFF
  OCI artifact; Landing remains a non-deployed static/config/SAM evidence bundle;
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
release workflow verifies GitHub attestation, build-run identity, exact `main`
SHA, artifact checksum, workspace-lock checksum, protected approval checksum,
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

Confirm the operations SNS subscription, billing cost-allocation tag and DNS/
certificate state. Keep the ALB fixed at `503`.

## 4. Build one immutable release

Manually dispatch `AWS Public Beta Immutable Build` on `main`. Record the build
run ID and release ID. The release artifact must contain the image manifest,
release metadata and digests for every application, ClamAV and release
operator, plus the deterministic Landing static tar, Landing metadata and exact
selected SAM template. Verify build provenance, every Landing checksum,
`deploymentStatus=NOT_DEPLOYED` and `scanStatus=PASSED` for every image entry.

The protected build input must generate complete reviewed Landing legal/runtime
configuration matching the same launch approval used by the app release.
Artifact generation performs no Amplify, SAM, DNS or other Landing deployment;
`AMPLIFY_RELEASE_AUTHORISED` remains absent/false. Preserve the artifact for the
later coordinated Landing promotion described in
[landing integration](landing-integration.md).

The build role can publish ECR images; it cannot change ECS, databases,
networking or the public listener. Reject the release if the workspace lock,
source revisions, RDS bundle evidence or required dependency evidence differs
from the reviewed inputs.

All images are pushed first so their per-repository scans can run concurrently;
the publisher then verifies every result before it can emit/attest a final
manifest. If publication or scanning fails after any immutable tag was pushed,
the release ID is failed and must never be reused. Diagnose it and create a new
release ID; unreferenced images remain subject to the reviewed ECR lifecycle.

## 5. Seed and prepare privately

Supply external credentials one integration at a time with
`put-external-secret.sh` from an owner-only `0400` or `0600` JSON input after
that integration is approved. Do not enable it yet. Core tokens, JWT keys and
seven database-user passwords are generated/idempotently preserved by the
protected release operator; values are never returned in workflow output.

Dispatch `prepare` with the exact build artifact and:

```text
confirmation: PREPARE <release-id>
```

The script deliberately performs these steps in order:

1. scales every application and scanner service to zero and keeps the listener dark;
2. seeds missing core/database secret versions;
3. verifies the expected ECS nodes, `awsvpcTrunking` registration, private
   subnet IP headroom, and registered CPU, memory and branch-ENI capacity;
4. runs an idempotent database bootstrap task to create/repair exactly seven
   roles and logical databases with least-privilege ownership;
5. records the exact database-bootstrap release marker;
6. renders the whole private-fleet plan;
7. starts and proves the isolated no-task-role ClamAV scanner fleet (one per
   reviewed node) before any document path;
8. starts application services one at a time in reviewed dependency/build
   order, waiting for each to stabilise;
9. converges the full private desired-count-one stack;
10. verifies every service's Flyway history over hostname-verified TLS; and
11. runs private health/preflight, then records the exact release marker.

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

Review an `action=plan` dispatch for desired count `1` and public entrypoint
`true`. Verify the exact release ID is both the database-bootstrap and
preflight SSM marker, targets are healthy, alarms are `OK`, backups succeeded,
provider/payment/email approvals remain current and the WAF upload tests pass.
Confirm the Client source/digest and Landing source/static/config/SAM evidence
still match the signed artifact. This activates only the application stack; the
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

The workflow verifies the old build run, attestation, release ID, its own
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
