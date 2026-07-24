# Scripts

## Live and E2E stacks

Use Python entry points for stack operations.

Live stack:

```bash
python -m scripts.docker.start_stack live --build
python -m scripts.docker.stop_stack live
```

- Compose project: `job-seeker-copilot-live`
- Frontend: `http://localhost:3000`
- H2 file-backed state: `authentication-service` at `/app/data/live/authentication`, `user-profile-service` at `/app/data/live/user-profile`
- Environment reset/seed is disabled in the live override.

E2E stack:

```bash
python -m scripts.docker.start_stack e2e --build
python -m scripts.docker.wait_for_stack e2e
python -m scripts.docker.stop_stack e2e
```

- Compose project: `job-seeker-copilot-e2e`
- Frontend: `http://localhost:3100`
- System data service: `http://localhost:9103`
- H2 file-backed state: `authentication-service` at `/app/data/e2e/authentication`, `user-profile-service` at `/app/data/e2e/user-profile`
- In-memory H2 state is isolated by the distinct E2E containers for application tracker, document store, and payment.
- Normal E2E gateway mode is `FIXTURE`.

## Dataset regeneration

Run controlled acquisition only when live provider calls are intended:

```bash
set -a; . ./.env; set +a
python -m scripts.docker.start_stack data-acquisition --build
python -m scripts.data.generate_dataset \
  --service-url http://localhost:9103 \
  --dataset-id uk-software-developer-demo \
  --version 1.0.0 \
  --overwrite \
  --queries "Software Developer" "Java Developer" "Backend Developer" "Full Stack Developer" "Junior Software Developer" "Software Engineer" "Angular Developer" "Spring Boot Developer" \
  --locations Reading London Birmingham Manchester Leeds Bristol \
  --providers ADZUNA JSEARCH REED \
  --maximum-results-per-provider 5 \
  --timeout-seconds 600
python -m scripts.data.inspect_dataset --dataset-path system-data-service/dataset-repository/uk-software-developer-demo/1.0.0
python -m scripts.docker.stop_stack data-acquisition
python -m scripts.docker.start_stack e2e
python -m scripts.demo.check_fixture_modes
```

`--overwrite` is required to replace an existing version. Without it, generation still refuses to overwrite. When overwrite is used, the previous version is moved under `system-data-service/dataset-repository/<dataset-id>/backups/`.

To capture deterministic demo LLM fixtures, temporarily run the data-acquisition stack with `llm-gateway` in live mode and make the explicit two-call capture:

```bash
python -m scripts.data.capture_llm_fixtures \
  --dataset-path system-data-service/dataset-repository/uk-software-developer-demo/1.0.0 \
  --llm-gateway-url http://localhost:9113 \
  --job-id <selected-demo-job-id> \
  --yes
```

This writes `llm-fixtures.json` into the dataset version. Return to fixture mode immediately afterwards with `python -m scripts.docker.start_stack e2e` and verify with `python -m scripts.demo.check_fixture_modes`.

## Demo preparation

One command prepares the fixture-backed demo environment:

```bash
python -m scripts.demo.prepare_demo
```

The command refuses live port `3000`, requires the E2E compose project, checks fixture gateway modes, resets and seeds `DEMO_READY`, and runs fixture smoke tests. Playwright/Cucumber defaults to `E2E_BASE_URL=http://localhost:3100`.

Operational scripts live under this directory and are grouped by responsibility.
Application code, service runtime code, and E2E test implementation stay in their
own project directories.

## Folder Structure

- `clients/`: OpenAPI export, generated client generation, installation, and conformance checks.
- `clients/config/`: generated-client dependency and conformance configuration.
- `data/`: dataset generation, dataset inspection, and environment reset/seed/verify commands.
- `demo/`: fixture and demo-readiness checks.
- `docker/`: Docker stack orchestration helpers.
- `git/`: GitHub Project and repository workflow helpers.
- `lib/`: shared helpers used by multiple script families.
The `app`, `ci`, `database`, and `test` categories are reserved for future
root-level entry points when real scripts exist; empty placeholder directories
are intentionally omitted.

## Invocation Standard

Prefer module invocation from the repository root:

```bash
python -m scripts.clients.generate_all_api_clients
```

Entry-point scripts also support direct invocation when needed:

```bash
python scripts/clients/generate_all_api_clients.py
```

Important old root paths remain as temporary compatibility wrappers. They print a
deprecation warning and delegate to the new module.

## Command Reference

### Generated Clients

```bash
python -m scripts.contracts.validate_lock
python -m scripts.contracts.validate_lock --verify-checkouts .
python -m scripts.clients.export_openapi_contracts
python -m scripts.clients.generate_backend_clients
python -m scripts.clients.install_backend_clients
python -m scripts.clients.generate_frontend_clients
python -m scripts.clients.generate_all_api_clients
python -m scripts.clients.check_backend_client_conformance
python -m scripts.clients.check_no_manual_system_data_fixture_clients
```

Configuration:

- `config/contracts-lock.json` is the reviewed source-revision, checksum,
  generator and immutable-package lock for migrated contracts.
- `scripts/clients/config/service_dependencies.json`
- `scripts/clients/config/backend_client_conformance_exclusions.json`

The export/generate/install commands below the lock validator are legacy
workspace compatibility paths. They are retained until every consumer resolves
producer-owned versioned packages; they are not an approved publication path
for new clients.

### Data

```bash
python -m scripts.data.generate_dataset --help
python -m scripts.data.inspect_dataset --help
python -m scripts.data.reset_environment --help
python -m scripts.data.seed_environment --help
python -m scripts.data.reset_and_seed_environment --help
python -m scripts.data.verify_environment --help
```

Reset commands require explicit confirmation unless `--yes` is supplied.

### Demo And Fixtures

```bash
python -m scripts.demo.check_fixture_modes
python -m scripts.demo.validate_fixture_dataset
python -m scripts.demo.smoke_test_fixtures
python -m scripts.demo.run_fixture_verification
```

These commands verify fixture-provider readiness and deterministic fixture
responses. They do not contain Playwright/Cucumber implementation code.

### Docker

```bash
python -m scripts.docker.rebuild_and_start_stack
```

This helper installs generated backend clients, builds backend services, and
rebuilds/starts the Docker Compose stack. It is intentionally not run by default
during safe verification because it changes the local Docker environment.

### Git

```bash
python -m scripts.git.git_manager --help
./gm doctor
./gm board
```

The `gm` shell wrapper invokes `python -m scripts.git.git_manager`.

## Compatibility Wrappers

Temporary wrappers exist at these old paths:

- `scripts/export_openapi_contracts.py` -> `python -m scripts.clients.export_openapi_contracts`
- `scripts/generate_backend_clients.py` -> `python -m scripts.clients.generate_backend_clients`
- `scripts/install_backend_clients.py` -> `python -m scripts.clients.install_backend_clients`
- `scripts/generate_frontend_clients.py` -> `python -m scripts.clients.generate_frontend_clients`
- `scripts/generate_all_api_clients.py` -> `python -m scripts.clients.generate_all_api_clients`
- `scripts/check_backend_client_conformance.py` -> `python -m scripts.clients.check_backend_client_conformance`
- `scripts/check_no_manual_system_data_fixture_clients.py` -> `python -m scripts.clients.check_no_manual_system_data_fixture_clients`
- `scripts/check_fixture_modes.py` -> `python -m scripts.demo.check_fixture_modes`
- `scripts/validate_fixture_dataset.py` -> `python -m scripts.demo.validate_fixture_dataset`
- `scripts/smoke_test_fixtures.py` -> `python -m scripts.demo.smoke_test_fixtures`
- `scripts/run_fixture_verification.py` -> `python -m scripts.demo.run_fixture_verification`
- `scripts/rebuild_and_start_stack.py` -> `python -m scripts.docker.rebuild_and_start_stack`
- `scripts/git-manager.py` -> `python -m scripts.git.git_manager`

Removal note: wrappers are retained to keep existing developer and CI commands
working during the migration. New automation should use the module commands.

## Adding A Script

- Put the script in the folder that matches its operational purpose.
- Use a snake_case, verb-first filename that describes the operation.
- Provide a `main()` function and useful `--help` output for command entry points.
- Use `pathlib.Path` and shared constants from `scripts.lib.project_paths`.
- Do not resolve repository paths from `os.getcwd()`.
- Keep configuration near the script family that owns it.
- Add shared helpers only when at least two script families or commands reuse them.

## Boundaries

- Scripts orchestrate project operations.
- Service application code remains inside service directories such as `job-service/`.
- E2E feature files, steps, pages, hooks, fixtures, and Playwright/Cucumber config
  remain under `e2e/playwright-cucumber/`.

## Prerequisites

Commands may require Python 3.11+, Maven, Docker Compose, Node/npm,
OpenAPI Generator, Git, GitHub CLI, and running local services depending on the
operation.
