# Reproducible local development

## First checkout

The parent directory must not be inside another Git repository.

```bash
mkdir -p /path/to/job-seeker-copilot
cd /path/to/job-seeker-copilot
git rev-parse --show-toplevel   # expected to fail
gh auth status
gh repo clone jobseekercopilot/infrastructure infrastructure
cd infrastructure
./scripts/bootstrap.sh --profile basic-fixture
```

Bootstrap is resumable and non-destructive. It validates prerequisites and
GitHub access, reads the catalogue and lock, clones all missing repositories as
siblings, verifies their remotes/branches/revisions, creates an ignored
owner-only environment, validates Compose and builds the selected profile.

It will not discard local changes, replace an existing directory, switch an
unexpected branch, accept a different remote or silently advance a lock.

## Daily commands

```bash
./scripts/validate-workspace.sh
./scripts/update-repositories.sh
./scripts/build-all.sh --profile basic-fixture
./scripts/test-all.sh --profile basic-fixture
./scripts/start-local.sh --profile basic-fixture --build
./scripts/health-check.sh --profile basic-fixture
./scripts/status.sh --profile basic-fixture
./scripts/logs.sh --profile basic-fixture
./scripts/stop-local.sh --profile basic-fixture
```

Replace `basic-fixture` with `full-fixture` for the complete private-beta
runtime. Basic covers account registration/login, profile/location and
fixture-backed job search. Full adds document, tracking, reporting, AI and
payment components while retaining fixture providers.

## Two safe workstreams

Create feature branches in the individual repository being changed. Keep
Infrastructure on its reviewed lock unless the change intentionally updates
the fleet. `update-repositories.sh` refuses dirty work, so beta-hardening and
feature branches cannot silently overwrite each other.

The catalogue may temporarily declare a reviewed feature branch and exact
revision when an Infrastructure checkpoint depends on an unmerged service PR.
After that dependency is merged, update both the declared branch and lock back
to `develop` in the same Infrastructure change.

A service change that affects a contract must update its producer-owned
OpenAPI file and client module first. A reviewed Infrastructure change then
updates the contract lock and workspace lock together.

## Local state and secrets

- Generated environments are `.env.<profile>`, ignored and mode `0600`.
- Lifecycle commands remove every application variable in the runtime schema from
  their inherited shell environment. Compose receives application configuration
  only from the selected generated environment file; tool settings such as
  `PATH`, `HOME` and `DOCKER_HOST` remain available.
- Where a service intentionally excludes `target/` from its Docker context, the
  build stages that checkout's current artifact into
  `<workspace>/.cache/runtime-images`. These disposable contexts contain no
  artifact from another workspace or from the user's Maven cache.
- Maven and npm caches live at `<workspace>/.cache`; `~/.m2` is not used.
- Generated clients are rebuilt from pinned producer Git history.
- Fixture profiles forbid real job-provider, LLM and Stripe credentials.
- Docker Compose project names differ by profile.
- Operator tools are opt-in and are not part of readiness.

## Troubleshooting

Run `doctor.py`, `validate-workspace.sh`, `status.sh`, then `logs.sh` in that
order. Failures name the repository or service that violated the lock/readiness
contract. Do not resolve a dirty-checkout error by deleting work; commit,
stash, or move that work deliberately, then rerun.

The destructive fixture reset requires both flags:

```bash
./scripts/stop-local.sh --profile basic-fixture --delete-volumes --yes
```

It removes only that Compose project’s local volumes. It is not appropriate for
valuable or production data.
