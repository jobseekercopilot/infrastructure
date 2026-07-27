# Job Seeker Copilot Infrastructure

Private workspace orchestration for the Job Seeker Copilot repositories. This
repository owns Docker Compose definitions, operational scripts, the shared
Maven build configuration, safe environment examples, and full-stack operating
documentation. Application source remains in the repositories owned by the
`jobseekercopilot` GitHub account.

## Repository model

This is a workspace orchestrator, not a monorepo and not a submodule
superproject. `scripts/workspace/bootstrap.py` clones the repositories listed
in `config/services.json` into ignored sibling directories beneath this
checkout. That preserves the existing `./service-name` Compose build contexts
without mixing service histories into Infrastructure.

## Bootstrap

Prerequisites: Git, GitHub CLI authenticated for the private account,
Docker with Compose v2, Java 17, Maven, Node.js, npm, and Python 3.11+.

```bash
python3 scripts/workspace/doctor.py
python3 scripts/workspace/bootstrap.py
python3 scripts/workspace/bootstrap.py --apply
```

The first two commands are read-only. `--apply` clones only missing
repositories; it does not pull, switch branches, or rewrite an existing
checkout.

## Stack profiles

Generate a fresh ignored environment for the selected profile:

```bash
python3 scripts/security/generate_profile_env.py --profile local --output .env
python3 scripts/security/generate_profile_env.py --profile e2e --output .env.e2e
python3 scripts/security/generate_profile_env.py \
  --profile live-provider --output .env.live
python3 scripts/security/generate_profile_env.py \
  --profile data-acquisition --output .env.data-acquisition
```

Then use the existing stack commands documented in `scripts/README.md`, or
validate directly:

```bash
docker compose --env-file .env -f docker-compose.yml config
docker compose --env-file .env.e2e -f docker-compose.yml -f docker-compose.e2e.yml config
```

Do not use real provider or payment credentials for fixture/E2E execution.
The live-provider overlay permits job-provider integration only: LLM is
disabled and Stripe stays fixture-backed. Data acquisition is a separate
one-shot, quarantined operator workflow, not a normal stack. It is never run
by automated verification. Mode boundaries are documented in
[`docs/MODE_ISOLATION.md`](docs/MODE_ISOLATION.md). Runtime identity ownership,
rotation, validation and remaining production controls are documented in
[`docs/RUNTIME_ENVIRONMENTS.md`](docs/RUNTIME_ENVIRONMENTS.md).

## Current readiness

This extraction creates a safe, independently versioned baseline. It does not
claim that the whole application builds from fresh clones today. Several
service repositories still depend on unversioned local generated-client JARs,
and the Compose/image, secrets, contract, CI, and clean-room release work is
tracked by the Infrastructure epic.

See `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and
`docs/ROOT_EXTRACTION_AUDIT.md`.

The approved cross-repository Job Search request path and responsibility
boundaries are defined in
[`docs/adr/0001-job-search-architecture-and-ownership.md`](docs/adr/0001-job-search-architecture-and-ownership.md).
The producer-owned contract/package model and current compatible contract pins
are defined by
[`docs/adr/0002-versioned-contract-and-client-publication.md`](docs/adr/0002-versioned-contract-and-client-publication.md)
and [`config/contracts-lock.json`](config/contracts-lock.json).
The fail-closed beta artifact evidence contract and its current delivery
boundaries are documented in
[`docs/RELEASE_EVIDENCE.md`](docs/RELEASE_EVIDENCE.md).

## Licence

Proprietary. See `LICENSE`.
