# Local development

The verified workspace model is sibling repositories, not a monorepo or Git submodule tree.

```text
job-seeker-copilot/
├── infrastructure/
├── job-seeker-copilot-client/
├── authentication-service/
├── job-service/
└── …
```

`infrastructure/config/services.json` is the repository/build/port/dependency catalogue. `config/workspace-lock.json` pins the tested revisions.

## Fresh machine

### Prerequisites

- Git and GitHub CLI authenticated for the private `jobseekercopilot` account
- Docker with Compose v2
- Java 17+, Maven, Node.js, npm
- Python 3.11+, OpenSSL, and curl

### Bootstrap

```bash
mkdir -p job-seeker-copilot
cd job-seeker-copilot
gh repo clone jobseekercopilot/infrastructure infrastructure
cd infrastructure
./scripts/bootstrap.sh --profile basic-fixture
```

Bootstrap validates tools/access, clones missing sibling repositories, verifies remotes and locked revisions, creates an ignored mode-`0600` fixture environment, and builds with workspace-local Maven/npm caches. It refuses unexpected branches/remotes, dirty destructive updates, and silent lock advancement.

## Start and verify

=== "Basic fixture"

    Account, profile, location, fixture-backed job search and the dependencies needed for application-state enrichment.

    ```bash
    ./scripts/start-local.sh --profile basic-fixture --build
    ./scripts/health-check.sh --profile basic-fixture
    ```

=== "Full fixture"

    All composed runtime services, with external job/LLM/Stripe providers replaced by fixtures.

    ```bash
    ./scripts/start-local.sh --profile full-fixture --build
    ./scripts/health-check.sh --profile full-fixture
    ```

Open <http://localhost:3000> after the health check succeeds.

## Daily commands

```bash
./scripts/validate-workspace.sh
./scripts/update-repositories.sh
./scripts/build-all.sh --profile basic-fixture
./scripts/test-all.sh --profile basic-fixture
./scripts/status.sh --profile basic-fixture
./scripts/logs.sh --profile basic-fixture
./scripts/stop-local.sh --profile basic-fixture
```

Replace the profile consistently across lifecycle commands. `update-repositories.sh` refuses dirty work; resolve it deliberately rather than deleting it.

## Real providers

```bash
./scripts/start-local.sh --profile real-job-providers --build
./scripts/health-check.sh --profile real-job-providers
```

The `real-providers` profile additionally enables OpenAI. Both read an owner-only base environment plus `config/.secrets.env`. Never append the legacy live overlay manually; the lifecycle script chooses the reviewed combination.

## Service-level work

Most Java repositories verify with:

```bash
mvn -B clean verify
```

The client and E2E repositories use committed npm locks:

```bash
npm ci
npm test -- --watch=false
npm run build
```

Always follow the repository README because contract generation, Testcontainers, Docker, supply-chain, or provider-specific checks vary.

## Stop and preserve data

```bash
./scripts/stop-local.sh --profile basic-fixture
```

This retains the profile's volumes. The explicit destructive form is intentionally guarded:

```bash
./scripts/stop-local.sh --profile basic-fixture --delete-volumes --yes
```

It removes only that Compose project's local volumes and must not be used for valuable or production data.
