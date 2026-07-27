# Script Inventory

This inventory records the root script reorganisation and includes the existing
root scripts/configuration plus service-local operational data scripts that were
moved under the root `scripts/` tree.

## Classification

- `MOVE`: moved to a purpose-based folder.
- `WRAP`: old path retained as a compatibility wrapper.
- `KEEP`: left in place because it is outside the root operational-script move.
- `DELETE_CANDIDATE`: generated or obsolete artifact; not deleted automatically.
- `REVIEW_REQUIRED`: needs a future owner decision.

## Inventory

| Original path | Purpose | Dependencies | Reads | Writes | Known callers | New path | Class | Wrapper | Imported by another script | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `scripts/api_client_config.py` | Compatibility adapter for legacy API client scripts. | Workspace catalogue loader. | `config/services.json`. | None. | Legacy client inspection scripts. | `scripts/clients/api_client_config.py` | MIGRATE | No | Yes | Derives from the authoritative catalogue; the competing dependency manifest was removed. |
| `scripts/backend_client_conformance_exclusions.json` | Documented generated-client conformance exclusions. | JSON consumers. | None. | None. | Backend client conformance checker, docs. | `scripts/clients/config/backend_client_conformance_exclusions.json` | MOVE | No | Config only | Path references updated. |
| `scripts/export_openapi_contracts.py` | Export running service OpenAPI contracts into `docs/contracts`. | Local services exposing `/v3/api-docs`. | Service dependency config, service OpenAPI endpoints. | `docs/contracts/*-openapi.json`. | README, generated-client workflow. | `scripts/clients/export_openapi_contracts.py` | MOVE/WRAP | Yes | No | Wrapper preserves old command. |
| `scripts/generate_backend_clients.py` | Generate Java backend clients from exported OpenAPI contracts. | OpenAPI Generator. | `docs/contracts/*-openapi.json`, service dependency config. | `generated-clients/backend/`. | README, generated-client workflow. | `scripts/clients/generate_backend_clients.py` | MOVE/WRAP | Yes | No | Uses shared project paths. |
| `scripts/install_backend_clients.py` | Retired copied-JAR entry point. | None. | None. | None. | Compatibility wrappers only. | `scripts/clients/install_backend_clients.py` | RETIRE | No | Yes | Fails closed and directs developers to `build-all.sh`. |
| `scripts/generate_frontend_clients.py` | Generate TypeScript frontend API clients. | OpenAPI Generator or openapi-generator-cli. | `docs/contracts/*-openapi.json`, service dependency config. | `job-seeker-copilot-client/src/generated/api/`. | `generate_all_api_clients.py`. | `scripts/clients/generate_frontend_clients.py` | MOVE/WRAP | Yes | No | Not listed in the minimum set but part of client workflow. |
| `scripts/generate_all_api_clients.py` | Orchestrate contract export, backend generation/install, and frontend generation. | Python subprocess, client scripts. | Client script results. | Generated backend/frontend clients and installed backend JARs through child scripts. | README, developer workflow. | `scripts/clients/generate_all_api_clients.py` | MOVE/WRAP | Yes | No | Now invokes modules with `python -m`. |
| `scripts/check_backend_client_conformance.py` | Audit internal HTTP calls against generated-client policy. | Python stdlib, service config, exclusions. | Java source files, POMs, contracts, generated clients, installed JARs. | None. | README, docs. | `scripts/clients/check_backend_client_conformance.py` | MOVE/WRAP | Yes | No | Config paths moved under `clients/config`. |
| `scripts/check_no_manual_system_data_fixture_clients.py` | Guard against manual fixture HTTP clients replacing generated system-data clients. | Python stdlib. | Gateway Java fixture provider clients. | None. | README. | `scripts/clients/check_no_manual_system_data_fixture_clients.py` | MOVE/WRAP | Yes | No | Classified with client conformance tooling. |
| `scripts/fixture_http.py` | Shared HTTP JSON helpers for fixture/demo scripts. | Python stdlib `urllib`. | Fixture service endpoints. | None. | Fixture/demo scripts. | `scripts/lib/http_client.py` | MOVE | No | Yes | Generic enough for demo/data-style HTTP helpers. |
| `scripts/check_fixture_modes.py` | Verify external gateways report expected provider mode. | Running gateways. | `/internal/provider-mode` endpoints. | None. | Fixture verification workflow, README. | `scripts/demo/check_fixture_modes.py` | MOVE/WRAP | Yes | No | Retains `--expect`. |
| `scripts/validate_fixture_dataset.py` | Validate system-data fixture endpoints and deterministic responses. | Running system-data-service. | Fixture internal endpoints. | None. | Fixture verification workflow. | `scripts/demo/validate_fixture_dataset.py` | MOVE/WRAP | Yes | No | Retains dataset/scenario CLI options. |
| `scripts/smoke_test_fixtures.py` | Smoke test gateway fixture responses. | Running fixture-mode gateways. | Gateway API endpoints. | None. | Fixture verification workflow. | `scripts/demo/smoke_test_fixtures.py` | MOVE/WRAP | Yes | No | No destructive behavior. |
| `scripts/run_fixture_verification.py` | Orchestrate fixture provider, dataset, and gateway smoke checks. | Demo fixture scripts. | Child script results. | None. | README, E2E README. | `scripts/demo/run_fixture_verification.py` | MOVE/WRAP | Yes | No | Now invokes moved demo modules. |
| `scripts/rebuild_and_start_stack.py` | Install generated backend clients, build backend services, rebuild/start Docker Compose. | Maven, Docker Compose, client config. | Service dependency config, backend service POMs, generated clients. | Backend build outputs, Docker containers/images. | Developer workflow. | `scripts/docker/rebuild_and_start_stack.py` | MOVE/WRAP | Yes | No | Destructive-ish Docker command retained but not executed in verification. |
| `scripts/git-manager.py` | GitHub Project board and multi-repository workflow helper. | GitHub CLI, Git, service dependency config. | GitHub Project data, local Git repos, config. | Git branches, GitHub Project state, issues/comments when commanded. | `gm`, README. | `scripts/git/git_manager.py` | MOVE/WRAP | Yes | No | Renamed to snake_case; `gm` updated. |
| `system-data-service/scripts/environment_client.py` | Shared HTTP/confirmation helpers for environment scripts. | Python stdlib `urllib`. | System-data environment endpoints. | None. | System-data environment scripts. | `scripts/data/environment_client.py` | MOVE | No | Yes | Operational helper, not service runtime code. |
| `system-data-service/scripts/generate_dataset.py` | Trigger dataset generation through system-data-service. | Running system-data-service. | Generation endpoint responses. | Dataset repository through service-side generation. | `system-data-service/README.md`. | `scripts/data/generate_dataset.py` | MOVE | No | No | Retains all CLI arguments. |
| `system-data-service/scripts/inspect_dataset.py` | Inspect generated dataset manifest/jobs/report JSON. | Python stdlib. | Dataset `manifest.json`, `jobs.json`, `generation-report.json`. | None. | `system-data-service/README.md`. | `scripts/data/inspect_dataset.py` | MOVE | No | No | Works from any CWD when given dataset path. |
| `system-data-service/scripts/reset_environment.py` | Reset non-production environment data. | Running system-data-service. | Environment status/verification endpoints. | Environment data through service endpoint. | `system-data-service/README.md`. | `scripts/data/reset_environment.py` | MOVE | No | No | Existing confirmation behavior preserved. |
| `system-data-service/scripts/seed_environment.py` | Seed non-production environment data. | Running system-data-service. | Environment seed endpoint response. | Environment data through service endpoint. | `system-data-service/README.md`. | `scripts/data/seed_environment.py` | MOVE | No | No | Retains scenario/dataset/reference-date options. |
| `system-data-service/scripts/reset_and_seed_environment.py` | Reset and seed demo-ready environment. | Running system-data-service. | Environment status/reset/verify endpoints. | Environment data through service endpoint. | `system-data-service/README.md`. | `scripts/data/reset_and_seed_environment.py` | MOVE | No | No | Existing confirmation behavior preserved. |
| `system-data-service/scripts/verify_environment.py` | Verify non-production environment data. | Running system-data-service. | Environment verify endpoint. | None. | `system-data-service/README.md`. | `scripts/data/verify_environment.py` | MOVE | No | No | Read-only verification. |
| `scripts/__pycache__/*` and `system-data-service/scripts/__pycache__/*` | Generated Python bytecode cache. | Python runtime. | Source scripts. | Bytecode cache. | Python import machinery. | Removed | DELETE_CANDIDATE | No | No | Clearly generated artifacts; removed after compile checks recreated them. |
| `e2e/playwright-cucumber/scripts/*.sh` | E2E-project local recording/run helpers. | E2E project, npm/Playwright. | E2E project files. | Recordings/artifacts. | E2E README. | Unchanged | KEEP | No | No | Actual E2E project helper area intentionally not moved. |

## Reserved Categories

No root-level scripts currently mapped cleanly to `scripts/app`, `scripts/test`,
`scripts/database`, or `scripts/ci`, so those placeholder directories were not
created.
