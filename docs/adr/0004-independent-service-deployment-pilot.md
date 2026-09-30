# ADR 0004: Production-disabled independent-service deployment pilot

Status: Accepted for non-production proving only

Date: 2026-08-28

## Context

The AWS public-beta module already models each application as a separate,
digest-pinned ECR image, ECS task definition, ECS service, security boundary and
Cloud Map identity. ECS is therefore not the reason a release currently
interrupts every service.

The supported release procedure is fleet-wide because it:

- accepts only foundation, prepare, activate, darken and full rollback phases;
- hashes the complete image manifest and all runtime configuration into one
  release attestation;
- requires database-bootstrap and private-preflight markers for that global
  attestation before application tasks or the public listener may run;
- deliberately scales the complete fleet to zero before its ordered start; and
- provisions the reviewed one-node shape for stop-first `0/100` replacement,
  not simultaneous old and new fleets.

Those controls are fail-closed and must not be bypassed experimentally in
production. However, they also prevent proving that a compatible, stateless
service can be replaced without restarting unrelated services.

## Decision

Introduce a local Compose pilot with the operator interface:

```text
deploy-service <allowlisted-service> <immutable-version>
rollback-service <allowlisted-service> <immutable-version>
```

The executable form is:

```bash
python3 -m scripts.deployment.service_pilot deploy-service \
  <service> <immutable-version>
python3 -m scripts.deployment.service_pilot rollback-service \
  <service> <immutable-version>
```

The pilot is hard-bound in code to the `full-fixture` profile, Compose project
`job-seeker-copilot-full`, base `docker-compose.yml`, no secret environment and
a local Unix/named-pipe Docker endpoint. It rejects inherited `DOCKER_HOST` and
`DOCKER_CONTEXT`, has no AWS or Terraform command boundary, exposes no profile
or environment selector and never pulls an image.

`config/non-production-service-pilot.json` is the reviewed allowlist. The first
and only service is `reporting-gateway`: it owns no database, has no direct ALB
attachment and is not revision-pinned by the current recovery, postcode or
payment evidence chains. The Compose override contains only that service.

An accepted version is either a local `sha256:<64 lowercase hex>` image ID or an
OCI `repository@sha256:<64 lowercase hex>` reference. Tags, including semantic
version tags, are not deployment inputs. The referenced image must already be
present on the local engine; `--pull never` and `--no-build` preserve the tested
artifact.

Before replacement, the operator records every project container's service,
container ID, image ID/reference, state and health. It requires the full fixture
application set to be present and healthy. It then invokes Compose with
`--no-deps --no-build --pull never --force-recreate` for exactly the selected
service.

Success requires:

1. the selected container to run the resolved target image and become healthy;
2. every unaffected container set and stable identity to remain unchanged;
3. every unaffected container to remain running and healthy where a healthcheck
   exists; and
4. a network smoke probe from the reviewed caller container to return Spring
   health status `UP`.

The operator repeats the identity/health assertion after smoke. It writes an
owner-only JSON record under the sibling workspace's
`.cache/service-deployments/`.

Any command, readiness, smoke or unchanged-service failure after replacement
causes an automatic replacement of the selected service with its captured prior
image ID. Rollback repeats readiness, caller smoke and unchanged-service
assertions. Failure of that restoration is retained distinctly as
`FAILED_ROLLBACK_FAILED`; it is never reported as a successful rollback.

## Production eligibility contract

This pilot does not make any service production-eligible. A future service may
enter a separately reviewed production allowlist only when evidence proves:

- it is stateless or uses an approved expand/contract data migration;
- its externally and internally consumed contracts remain compatible;
- the patch does not change ports, CPU/memory, environment, secret bindings,
  IAM, networking, service discovery, listeners or desired count;
- the image is built from protected source, tested, scanned and addressed by
  digest;
- service-specific readiness and at least one meaningful caller journey exist;
- a refresh-backed Terraform plan changes only that service's task definition,
  service reference and append-only deployment evidence;
- the previous digest and task-definition revision are available and tested;
- deployment concurrency, approval and audit controls remain protected; and
- capacity evidence supports the selected rollout envelope.

The initial production exclusion set includes the client/edge, Stripe and the
payment chain, database-owning services, Document Store and recovery-critical
services, release operators, ClamAV, and services whose revisions are pinned by
global launch evidence.

## Attestation decomposition required before production

The current `release_attestation_id` binds the entire image manifest to database
bootstrap, private preflight and public activation. A production service-patch
path must not bypass that precondition or forge new fleet-wide markers.

Instead, decompose it into:

- a **platform attestation** for approved runtime configuration, secret
  specifications, network/IAM/platform inputs and database-bootstrap
  compatibility;
- a **service attestation** for one digest, source revision, contract checksum,
  tests, scan and service-specific probes; and
- an append-only **fleet snapshot** recording the platform attestation and every
  currently deployed service attestation.

Evidence-critical cross-service capabilities remain full-release-only until
their evidence contracts explicitly support compatible component updates.

## Phased rollout

1. **Local proof:** deterministic fake-boundary tests plus a manually approved
   full-fixture Compose exercise. No production or external provider access.
2. **Account-free IaC proof:** synthetic one-digest Terraform plan and an exact
   plan-diff allowlist, with negative tests for second-service, platform and
   destructive changes.
3. **Production-shaped non-production proof:** deploy and roll back an eligible
   canary in a dedicated ECS environment; retain task/digest and continuity
   evidence.
4. **Protected stop-first production pilot:** separately approved maintenance
   task, one service, existing `0/100` replacement and explicit user-impact
   expectations.
5. **Optional rolling replacement:** only after measured spare capacity supports
   a per-service minimum healthy count. The present one-node capacity model does
   not prove zero downtime for the changed service.

## Consequences

The pilot proves the required control flow without claiming that local Compose
evidence is production evidence. Unaffected services must remain available, but
the selected service may have a short stop-first interruption. A local health
probe proves process/readiness and caller reachability, not complete business
semantics; production eligibility requires a stronger service-specific journey.

The existing full release, darkening, rollback, global attestation and AWS
workflows remain unchanged.
