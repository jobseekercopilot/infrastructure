# Job Seeker Copilot Infrastructure

Private workspace orchestration for the Job Seeker Copilot repositories. This
repository owns Docker Compose definitions, operational scripts, the shared
Maven build configuration, safe environment examples, and full-stack operating
documentation. Application source remains in the repositories owned by the
`jobseekercopilot` GitHub organisation.

## Repository model

This is a workspace orchestrator, not a monorepo and not a submodule
superproject. `scripts/workspace/bootstrap.py` clones the repositories listed
in `config/services.json` into ignored sibling directories beneath this
checkout. That preserves the existing `./service-name` Compose build contexts
without mixing service histories into Infrastructure.

## Bootstrap

Prerequisites: Git, GitHub CLI authenticated for the private organisation,
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

Copy only the example needed for the profile:

```bash
cp .env.example .env
cp .env.e2e.example .env.e2e
cp .env.live.example .env.live
```

Then use the existing stack commands documented in `scripts/README.md`, or
validate directly:

```bash
docker compose --env-file .env -f docker-compose.yml config
docker compose --env-file .env.e2e -f docker-compose.yml -f docker-compose.e2e.yml config
```

Do not use real provider or payment credentials for fixture/E2E execution.

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

## Licence

Proprietary. See `LICENSE`.
