# AWS public-beta stack

This directory contains a reviewed, non-deployed Terraform stack for a UK
public beta in `eu-west-2`. Its checked-in defaults create no runnable release:
application desired count is zero, the public listener is a fixed `503`, every
external integration is disabled, all image digests are zero placeholders and
all approval attestations are false.

The approved lean topology is one fixed `m7i.2xlarge` ECS/EC2 node, one NAT
Gateway, one shared encrypted `db.t4g.medium` PostgreSQL instance with seven
isolated logical databases, an ALB/WAF edge, private service discovery, S3
document storage and AWS Backup. `high_availability=true` is an explicit,
cost-reviewed upgrade to two nodes, two NAT Gateways and Multi-AZ RDS; it is not
an autoscaling surprise.

Important boundaries:

- `bootstrap/state-and-oidc.yaml` is a separate manual prerequisite for the
  state bucket/KMS key and GitHub OIDC roles. No workflow invokes it.
- Develop/PR CI performs an isolated local-backend plan with dummy credentials
  and has no `id-token: write` permission.
- Only manually dispatched workflows on `main`, protected by required-reviewer
  GitHub environments, can publish images or change AWS.
- Repository build/test code runs in a prepare job with no OIDC permission or
  AWS credentials. Only a separate publisher job can assume the ECR role after
  checksum-loading its short-lived prepared image archive.
- `foundation` is dark infrastructure only; `prepare` keeps the listener dark;
  a separate exact-release `activate` dispatch is the only public transition.
- Break-glass `darken` binds the supplied release ID to applied remote state,
  fixes both public ALB routes at `503`, then drains tasks. It intentionally
  does not depend on an unexpired launch approval or retained build artifact.
- Terraform creates secret containers, never secret versions. Idempotent
  operator scripts seed core/database values and external values are supplied
  independently after commercial/legal approval.
- Credentials do not imply provider approval. Reed, Adzuna, JSearch, Google,
  OpenAI, Stripe and Northern Ireland postcode use have additional manifest
  gates. NHS Jobs and DfE apprenticeships may be approved independently.
- Google additionally needs a true external billing-quota attestation with
  exact quota IDs/limits, 50/75/90/100% alerts and an emergency-disable owner;
  application-local counters and budget alerts are not spending caps.
- The checked-in image manifest pins the complete tested Postcodes NI/BT and
  payment/lifecycle chains, separate test-only signed-settlement acceptance
  provenance, plus exact Client/Landing source-contract evidence. System Data,
  E2E and fixture controls are never production runtime images or public routes.
  Generated Landing static/runtime/SAM hashes remain `PENDING`, and release
  capabilities, source branch, protected-approval hash and image digests remain
  deliberately false/develop/pending/placeholder. No release build succeeds
  until every reviewed source is merged, ancestor-verified, built and scanned.
  The central build creates the Client OCI digest plus checksum-bound Landing
  evidence, while explicitly recording Landing as not deployed.

Start with the [architecture](../../docs/aws-public-beta/architecture.md), then
the [deployment runbook](../../docs/aws-public-beta/deployment-runbook.md) and
[launch checklist](../../docs/aws-public-beta/launch-checklist.md). The checked
in files must never be used as a substitute for a reviewed, refresh-backed
production plan.

Validated toolchain: Terraform `1.15.8`, HashiCorp AWS provider `6.55.0`.
`scripts/aws/validate_public_beta.py` and
`scripts/aws/offline_terraform_plan.sh` are account-free release-contract tests.
