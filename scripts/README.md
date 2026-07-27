# Scripts

## Local, live-provider and E2E stacks

Use Python entry points for stack operations.

Local fixture stack:

```bash
python -m scripts.docker.start_stack local --build
python -m scripts.docker.stop_stack local
```

- Compose project: `job-seeker-copilot-local`
- Frontend: `http://localhost:3000`
- External egress is disabled at the Compose network.
- Job, postcode, LLM and Stripe gateways use deterministic fixtures.
- Environment reset/seed is disabled.

Live job-provider stack:

```bash
python -m scripts.docker.start_stack live --build
python -m scripts.docker.stop_stack live
```

- Compose project: `job-seeker-copilot-live`
- Frontend: `http://localhost:3000`
- PostgreSQL state: dedicated Authentication, Document Store, and Payment
  containers; Document Store bytes use the synthetic filesystem adapter.
- H2 file-backed state: User Profile only, at
  `/app/data/live/user-profile`.
- Environment reset/seed is disabled in the live override.
- LLM is disabled and Stripe remains fixture-backed.
- This is local real-provider integration, not a production deployment.

E2E stack:

```bash
python -m scripts.docker.start_stack e2e --build
python -m scripts.docker.wait_for_stack e2e
python -m scripts.docker.stop_stack e2e
```

- Compose project: `job-seeker-copilot-e2e`
- Frontend: `http://localhost:3100`
- System data service: `http://localhost:9103`
- PostgreSQL state: dedicated Authentication, Document Store, and Payment
  containers; Document Store bytes use the synthetic filesystem adapter.
- H2 file-backed state: User Profile only, at
  `/app/data/e2e/user-profile`.
- Application Tracker retains its isolated H2 E2E state.
- Normal E2E gateway mode is `FIXTURE`.

Normal stop preserves the selected project's state. To permanently reset only
one disposable local/E2E project's named volumes, require both flags:

```bash
python -m scripts.docker.stop_stack e2e --delete-volumes --yes
```

## Quarantined job-provider acquisition

Data acquisition is a separate one-shot project, not an E2E overlay. It can
make real job-provider calls and may incur provider costs. Generate its ignored
environment, record the required approval/reviewer/run metadata, then use the
guarded runner only when those calls are intended:

```bash
python3 scripts/security/generate_profile_env.py \
  --profile data-acquisition \
  --output .env.data-acquisition
python3 -m scripts.data.run_acquisition \
  --env-file .env.data-acquisition \
  --authorize-live-provider-costs
```

The runner validates the rendered boundary, starts only approved gateway
profiles, runs System Data as a non-web command, and always tears down its
containers and network. The governed dataset repository is read-only. Output
is retained under
`system-data-service/quarantined-acquisitions/<run-id>` with a redacted audit
record and is not runtime-eligible.

Reject or remove an expired capture by exact run ID:

```bash
python3 -m scripts.data.purge_acquisition \
  --run-id <run-id> \
  --reason rejected \
  --reviewer <name> \
  --yes
```

The former live LLM capture command is disabled. A future cost-bounded,
quarantined replacement is tracked in
[BACKLOG-LLM-02](https://github.com/jobseekercopilot/infrastructure/issues/29).
No normal stack or acquisition command can inject an OpenAI credential or
create paid AI content. See
[`docs/MODE_ISOLATION.md`](../docs/MODE_ISOLATION.md).

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

### Workspace lifecycle

```bash
./scripts/bootstrap.sh --profile basic-fixture
./scripts/validate-workspace.sh
./scripts/update-repositories.sh
./scripts/build-all.sh --profile full-fixture
./scripts/test-all.sh --profile full-fixture
./scripts/start-local.sh --profile full-fixture --build
./scripts/health-check.sh --profile full-fixture
./scripts/status.sh --profile full-fixture
./scripts/logs.sh --profile full-fixture
./scripts/stop-local.sh --profile full-fixture
```

Authoritative configuration:

- `config/services.json`: repositories, topology, profiles and GitHub Project.
- `config/workspace-lock.json`: exact repository revisions.
- `config/contracts-lock.json`: contract checksum, generator, immutable Maven
  coordinates and producer-owned client build revisions.
- `scripts/clients/config/backend_client_conformance_exclusions.json`

`build-all.sh` reconstructs locked Java clients from producer Git history into
the workspace-local `.cache/m2`. The old
`python -m scripts.clients.install_backend_clients` copied-JAR path is retired
and fails closed.

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
./scripts/start-local.sh --profile basic-fixture --build
```

Use only the tracked lifecycle commands for the reproducible basic/full fixture
profiles. Older stack helpers remain for mode-specific migration work and are
not the onboarding path.

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
