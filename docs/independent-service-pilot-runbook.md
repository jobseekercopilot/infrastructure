# Independent-service pilot runbook

This runbook operates one service in the local, fully fixture-backed Compose
stack. It cannot deploy to AWS or production. Read
[ADR 0004](adr/0004-independent-service-deployment-pilot.md) before changing the
allowlist or interpreting the evidence.

## Safety boundary

The command refuses to run unless all of the following remain true:

- policy environment is `NON_PRODUCTION_COMPOSE_PILOT`;
- profile is exactly `full-fixture`;
- project is exactly `job-seeker-copilot-full`;
- the only Compose base file is `docker-compose.yml`;
- no secret environment file is attached;
- Docker uses a local Unix or Windows named-pipe endpoint;
- neither `DOCKER_HOST` nor `DOCKER_CONTEXT` is inherited;
- the service is present in `config/non-production-service-pilot.json`;
- its port and health path agree with the authoritative service catalogue and
  its smoke caller belongs to the selected runtime; and
- the target is an immutable digest already present on the local engine.

The pilot contains no `aws`, `terraform`, ECS, ECR, Amplify, DNS or GitHub
mutation command. Do not weaken these checks to point it at a remote engine.

## Current pilot scope

`reporting-gateway` is the only allowlisted service. Its caller smoke originates
from `job-seeker-copilot-client` and checks
`http://reporting-gateway:8095/actuator/health` for JSON status `UP`.

This proves container readiness and Compose-network caller reachability. It does
not prove an authenticated reporting journey. Add that semantic test before any
production-eligibility proposal.

## Prerequisites

1. Build and test the candidate in its owning repository.
2. Build or load exactly that candidate image on the local Docker engine.
3. Start and verify the complete fixture stack:

   ```bash
   ./scripts/start-local.sh --profile full-fixture --build
   ./scripts/health-check.sh --profile full-fixture
   ```

4. Resolve the tested image to an immutable local identity. A mutable tag may be
   used only as the lookup input; do not pass the tag to the pilot:

   ```bash
   docker image inspect --format '{{.Id}}' <candidate-tag>
   ```

   The result must be `sha256:` followed by 64 lowercase hexadecimal characters.
   A locally present `repository@sha256:...` reference is also accepted.

5. Ensure `DOCKER_HOST` and `DOCKER_CONTEXT` are unset. The operator independently
   checks the selected context endpoint.

## Deploy one service

```bash
python3 -m scripts.deployment.service_pilot \
  deploy-service \
  reporting-gateway \
  sha256:<64-lowercase-hex>
```

Optional timing controls remain local and positive:

```bash
python3 -m scripts.deployment.service_pilot \
  deploy-service reporting-gateway sha256:<64-lowercase-hex> \
  --timeout-seconds 180 --poll-seconds 2
```

The operator will:

1. prove the local fixture boundary;
2. resolve the target without pulling it;
3. require a complete healthy fixture stack;
4. record before identities;
5. run `docker compose up` for only `reporting-gateway` with `--no-deps`,
   `--no-build`, `--pull never` and `--force-recreate`;
6. wait for the target image to become healthy;
7. prove every unaffected container retained its identity and health;
8. run the caller smoke;
9. repeat the unchanged-service assertion; and
10. finalize the deployment record.

No unrelated container restart is accepted as success, even if it later becomes
healthy.

## Automatic failure handling

After a replacement is attempted, any deployment, health, smoke or continuity
failure automatically uses the selected service's captured prior image ID:

```text
failed candidate
  -> replace selected service with captured prior image ID
  -> wait healthy
  -> caller smoke
  -> unchanged-service assertion
  -> failed-with-rollback record
```

Expected terminal states are:

| Status | Meaning | Operator action |
| --- | --- | --- |
| `SUCCEEDED` | Target is healthy; smoke and continuity passed. | Review and retain the record. |
| `FAILED_ROLLED_BACK` | Candidate failed; prior image was restored and verified. | Diagnose outside the running stack. |
| `FAILED_ROLLBACK_FAILED` | Candidate and automatic restoration failed, or continuity could not be proven. | Stop; inspect the named local project and retained record. Do not claim rollback success. |

The script deliberately does not tear down the stack or delete volumes.
An ordinary Ctrl-C after replacement is treated as failure and invokes the same
automatic restoration. No process can recover from `SIGKILL`, host power loss or
Docker daemon loss: the initial `PREPARED` record retains the prior image ID for
the explicit recovery command below.

## Explicit rollback exercise

Use the `before.reporting-gateway.image_id` value from a successful deployment
record as the immutable target:

```bash
python3 -m scripts.deployment.service_pilot \
  rollback-service \
  reporting-gateway \
  sha256:<prior-image-id>
```

The same allowlist, local-engine guard, health, smoke, continuity and automatic
restore rules apply. If this requested rollback fails, the tool attempts to
restore the image that was running immediately before the rollback command.

## Deployment records

Records are written with mode `0600` below:

```text
<workspace>/.cache/service-deployments/
```

Each record contains:

- operation, service, requested digest and resolved image ID;
- UTC start/completion times;
- safe before/after container identities and health states;
- caller and smoke outcome;
- unchanged-service outcome; and
- automatic rollback target, status, evidence and failure reason when relevant.

The command boundary deliberately excludes container environment and command
stderr from retained records so runtime secrets are not captured.

## Deterministic validation without a running stack

The unit suite uses a fake runtime/command boundary and never invokes Docker:

```bash
python3 -m unittest -v tests.test_service_deployment_pilot
```

It covers immutable-reference rejection, allowlist enforcement, local-engine
guarding, exact `--no-deps` command construction, successful deployment,
unhealthy and smoke-failing candidates, automatic restoration, explicit
rollback, deployment records and unchanged-service detection.

## Production rollout gate

Passing this runbook is necessary local evidence only. Before any production
service deployment exists, complete the account-free plan verifier,
production-shaped non-production ECS exercise, attestation decomposition,
service-specific semantic smoke, protected approval/concurrency design and a
separately approved rollout/rollback maintenance task described in ADR 0004.
