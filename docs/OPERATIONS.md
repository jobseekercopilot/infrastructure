# Operations

## Safe first run

1. Authenticate `gh` for the private `jobseekercopilot` account.
2. Clone only Infrastructure into `job-seeker-copilot/infrastructure`.
3. Run `./scripts/bootstrap.sh --profile basic-fixture` or `full-fixture`.
4. Start with `./scripts/start-local.sh --profile <profile> --build`.
5. Run `./scripts/health-check.sh --profile <profile>`.

Bootstrap refuses unexpected directories, remotes, branches, revision drift
and dirty checkouts. `./scripts/update-repositories.sh` is the only supported
update path and only fast-forwards clean expected branches.

## Profiles

- `local`: deterministic fixture-backed development on an internal-only
  network; destructive environment endpoints are disabled.
- `e2e`: deterministic fixture-only validation; no real external activity.
- `data-acquisition`: separate one-shot live job-provider acquisition with
  exact approval, quarantine, retention and teardown controls. It is never a
  routine stack or automated test profile.
- `live`: local job-provider integration. LLM remains disabled and Stripe
  remains fixture-backed, so this profile cannot create paid AI content or
  real charges. It is not production deployment evidence.

The document path's current identity matrix, local PostgreSQL/object-storage
boundary, validation commands, rotation procedure and production gaps are in
[`RUNTIME_ENVIRONMENTS.md`](RUNTIME_ENVIRONMENTS.md).
The complete crossover policy and acquisition procedure are in
[`MODE_ISOLATION.md`](MODE_ISOLATION.md).

## Recovery

Inspect first:

```bash
./scripts/status.sh --profile full-fixture
./scripts/logs.sh --profile full-fixture
./scripts/health-check.sh --profile full-fixture
```

Restart without data loss using `stop-local.sh` followed by `start-local.sh`.
For disposable fixture data only, explicitly reset that profile’s volumes:

```bash
./scripts/stop-local.sh --profile full-fixture --delete-volumes --yes
./scripts/start-local.sh --profile full-fixture --build
```

Volume deletion is intentionally double-confirmed and is not a backup
procedure. Preserve any non-fixture data before using it. Production database
and object-storage backup/restore remains deployment-platform work; local
fixture volumes are reproducible and disposable.

If a repository update is interrupted, rerun bootstrap. Existing correct
checkouts are reused and partial unexpected directories fail closed. If a
credential appears in source, logs, screenshots or artifacts, rotate it and
record the response privately.

## Generated-client recovery

`build-all.sh` verifies contract checksums, extracts exact producer-owned client
modules from the Git revisions in `config/contracts-lock.json`, and installs
them only into `<workspace>/.cache/m2`. Delete that cache only when deliberately
testing a clean dependency rebuild. Never copy JARs into service `libs/`
directories and never rely on `~/.m2`.
