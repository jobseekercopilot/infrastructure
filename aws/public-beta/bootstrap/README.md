# Public-beta bootstrap boundary

`state-and-oidc.yaml` is a manual, reviewed CloudFormation bootstrap for the
otherwise circular prerequisites of Terraform state and GitHub OIDC. It is not
called by CI or release automation and it does not deploy the application.

Before creating a change set, an account administrator must verify the target
account, `eu-west-2`, the unique state bucket name, the existing Route 53 hosted
zone ARN, exact application hostname (used to constrain record mutations),
whether a GitHub OIDC provider already exists, and the current GitHub
OIDC certificate thumbprint from authoritative AWS/GitHub guidance. Review the
complete change set; then execute it manually only after approval.

Record the outputs as protected GitHub environment variables. Create three
GitHub environments with required reviewers and no self-approval:

| Environment | Branch policy | Role output | Purpose |
|---|---|---|---|
| `production-aws-plan` | `main` only | `PlanRoleArn` | refresh-backed release plan; never apply |
| `production-build` | `main` only | `BuildRoleArn` | credential-free source preparation followed by isolated immutable ECR publication |
| `production-aws` | `main` only | `ApplyRoleArn` | reviewed infrastructure apply and one-shot release operations |

Develop and pull-request CI is account-free and receives no OIDC token. A merge
to `develop` therefore cannot plan against or mutate AWS. The protected main
workflow also requires an explicit dispatch and confirmation phrase; the
environment reviewer is a separate human control.

ECR repositories deliberately remain owned by the normal Terraform state, not
split between CloudFormation and Terraform. They are created by the protected
`foundation` apply only after this backend/OIDC bootstrap is complete, while
the listener and task counts remain dark. The immutable build/publisher is a
later phase and cannot publish successfully before those exact repositories
exist. This ordered boundary avoids both an uninitialised-backend cycle and an
unreviewed import/split-ownership cycle. GitHub production environments are
also human-created prerequisites: this AWS template cannot create or claim
their branch/reviewer protection.

The service-bound apply role deliberately is not an account administrator, but
Terraform control-plane APIs sometimes cannot be resource-scoped. Its broad
resource actions are contained to the services this stack owns and protected by
the exact repository/environment OIDC subject. Re-review this policy whenever a
new AWS service is added.

## Protected environment inputs

Bootstrap outputs establish only the trust boundary. An owner separately
records these non-secret variables and protected inputs; no bootstrap template
or workflow invents their values.

| Environment | Name | Kind | Purpose |
|---|---|---|---|
| all three | `AWS_ACCOUNT_ID` where used | variable | exact 12-digit target account |
| `production-build` | `AWS_BUILD_ROLE_ARN` | variable | `BuildRoleArn` output |
| `production-build` | `RELEASE_READER_APP_ID` | variable | contents-read-only cross-repository GitHub App |
| `production-build` | `RELEASE_READER_APP_PRIVATE_KEY` | secret | GitHub App private key; never an AWS key |
| `production-build` | `POSTGRES_IMAGE_BY_DIGEST` | variable | reviewed PostgreSQL 15 Alpine digest |
| `production-build` | `RDS_CA_BUNDLE_URL` / `RDS_CA_BUNDLE_SHA256` | variables | official trust bundle and reviewed checksum |
| `production-build` | `LANDING_RUNTIME_ENV_B64` | protected secret | exact reviewed non-secret Landing generation JSON |
| build, plan and apply | `LAUNCH_APPROVALS_B64` | protected secret | byte-identical reviewed approval JSON; signed hash must match |
| `production-aws-plan` | `AWS_PLAN_ROLE_ARN` | variable | `PlanRoleArn` output |
| `production-aws` | `AWS_APPLY_ROLE_ARN` | variable | `ApplyRoleArn` output |
| plan and apply | `TF_STATE_BUCKET` / `TF_STATE_KMS_KEY_ARN` | variables | bootstrap state outputs |
| plan and apply | `PUBLIC_BETA_TFVARS_B64` | protected secret | reviewed non-secret Terraform input file |

GitHub secrets are used for access control/redaction even where the payload is
not a credential. Runtime service credentials do not belong in any item in this
table. Rotate the GitHub App key independently, require environment review for
every change, and record only checksums in release evidence.

The workflow's prepare job deliberately has no OIDC permission. It may use the
environment's read-only GitHub App and non-secret protected configuration, then
passes a one-day checksum-bound Docker archive to a second job. Only that
publisher job requests `BuildRoleArn`, and it runs no repository build/test
code.
