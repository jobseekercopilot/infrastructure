# Job Seeker Copilot Infrastructure

Private workspace orchestration for the Job Seeker Copilot repositories. This
repository owns Docker Compose definitions, operational scripts, the shared
Maven build configuration, safe environment examples, and full-stack operating
documentation. Application source remains in the repositories owned by the
`jobseekercopilot` GitHub account.

## Platform documentation

The searchable, cross-repository documentation site lives in
[`docs-site`](docs-site/README.md) and is published at
[docs.jobseekercopilot.com](https://docs.jobseekercopilot.com/). It explains the product, end-to-end user
journeys, service dependencies, API boundaries, data ownership, configuration,
and local operations. Repository guides below remain the source for
Infrastructure-specific procedures.

## Repository model

This is a workspace orchestrator, not a monorepo or submodule superproject.
Infrastructure and every application repository are siblings:

```text
job-seeker-copilot/
├── infrastructure/
├── authentication-service/
├── job-service/
├── job-seeker-copilot-client/
└── ...
```

[`config/services.json`](config/services.json) is the single repository,
dependency, build-order, startup-profile, port and health catalogue.
[`config/workspace-lock.json`](config/workspace-lock.json) pins its tested
revisions. Service source is never cloned inside Infrastructure.

## Bootstrap

Only Infrastructure needs to be cloned manually. Prerequisites are Git,
GitHub CLI authenticated for the private account, Docker with Compose v2,
Java 17+, Maven, Node.js, npm, Python 3.11+, OpenSSL and curl.

```bash
mkdir -p job-seeker-copilot
cd job-seeker-copilot
gh repo clone jobseekercopilot/infrastructure infrastructure
cd infrastructure
./scripts/bootstrap.sh --profile basic-fixture
```

Bootstrap validates tools and GitHub authentication, clones missing sibling
repositories, checks exact locked revisions without discarding local work,
generates an owner-only fixture environment and builds using workspace-local
Maven/npm caches. Use `./scripts/update-repositories.sh` for an explicit safe
fast-forward to a newly reviewed lock.

## Stack profiles

- `basic-fixture`: registration, profile, location and fixture-backed job
  search.
- `full-fixture`: every private-beta runtime component, with job providers,
  LLM and payments fixture-backed.
- `full-local-ses`: the same complete fixture-backed runtime, with account
  email sent by the Authentication Service production SES adapter to pinned,
  ephemeral LocalStack SES.
- `real-job-providers`: the full application with Reed, Adzuna, JSearch,
  NHS Jobs, Find an apprenticeship and the Postcodes.io location authority
  live while OpenAI and Stripe remain fixture-backed.
- `real-providers`: the same full application with all five job providers and
  Postcodes.io, OpenAI and Google Maps live while Stripe and payments remain
  fixture-backed.

```bash
./scripts/start-local.sh --profile basic-fixture --build
./scripts/health-check.sh --profile basic-fixture
./scripts/status.sh --profile basic-fixture
./scripts/logs.sh --profile basic-fixture
./scripts/stop-local.sh --profile basic-fixture
```

Do not use real provider or payment credentials for fixture/E2E execution.
Both real-provider profiles reuse the owner-only
`.env.real-job-providers` base environment and read provider credentials only
from the workspace-root `config/.secrets.env`, which must have mode `0600`.
The lifecycle applies `docker-compose.yml`, then
`docker-compose.real-job-providers.yml`, then—only for `real-providers`—
`docker-compose.real-openai.yml`, `docker-compose.real-google-maps.yml` and
`docker-compose.low-memory.yml`. The
combined profile uses one Compose operation at a time and checked-in runtime
memory ceilings; it does not require a temporary resource overlay. Never append
`docker-compose.live.yml`: that legacy job-only overlay resets the LLM gateway
to `DISABLED`.

Credentials are never copied into a repository, image or browser bundle.
Start-up fails with a variable name—not its value—when a required provider
credential is missing. Data acquisition is a separate
one-shot, quarantined operator workflow, not a normal stack. It is never run
by automated verification. Mode boundaries are documented in
[`docs/MODE_ISOLATION.md`](docs/MODE_ISOLATION.md). Runtime identity ownership,
rotation, validation and remaining production controls are documented in
[`docs/RUNTIME_ENVIRONMENTS.md`](docs/RUNTIME_ENVIRONMENTS.md).

Full onboarding, update, test, recovery and clean-room instructions are in
[`docs/LOCAL_DEVELOPMENT.md`](docs/LOCAL_DEVELOPMENT.md) and
[`docs/OPERATIONS.md`](docs/OPERATIONS.md).

See `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and
`docs/ROOT_EXTRACTION_AUDIT.md`.

The approved cross-repository Job Search request path and responsibility
boundaries are defined in
[`docs/adr/0001-job-search-architecture-and-ownership.md`](docs/adr/0001-job-search-architecture-and-ownership.md).
The producer-owned contract/package model and current compatible contract pins
are defined by
[`docs/adr/0002-versioned-contract-and-client-publication.md`](docs/adr/0002-versioned-contract-and-client-publication.md)
and [`config/contracts-lock.json`](config/contracts-lock.json).
Local development reconstructs those pinned client packages from the producer
Git histories into `.cache/m2`; it does not use copied JARs, `~/.m2`, or a
GitHub Packages read token.
The fail-closed beta artifact evidence contract and its current delivery
boundaries are documented in
[`docs/RELEASE_EVIDENCE.md`](docs/RELEASE_EVIDENCE.md).

## Licence

Proprietary. See `LICENSE`.
