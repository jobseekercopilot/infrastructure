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

## Workspace lifecycle profiles

- `basic-fixture`: registration, profile, location and fixture-backed job
  search.
- `full-fixture`: the complete deterministic private-beta runtime.
- `full-local-ses`: the complete fixture runtime with account email delivered
  to pinned local SES.
- `real-job-providers`: the complete runtime with Reed, Adzuna, JSearch, NHS
  Jobs, Find an apprenticeship and Postcodes.io live; OpenAI and Stripe remain
  fixture-backed.
- `real-providers`: the complete runtime with all five job providers and
  Postcodes.io, OpenAI and Google Maps live; Stripe and payments remain
  fixture-backed.

The two real-provider profiles share the owner-only
`.env.real-job-providers` file and the same Compose project. Provider
credentials are resolved separately from the workspace-root
`config/.secrets.env`; lifecycle output contains variable names and paths, not
credential values.

For `real-providers`, the only supported Compose order is base, real job
providers, real OpenAI, real Google Maps, then the reviewed low-memory runtime
limits:

```text
docker-compose.yml
docker-compose.real-job-providers.yml
docker-compose.real-openai.yml
docker-compose.real-google-maps.yml
docker-compose.low-memory.yml
```

Use the lifecycle wrappers rather than assembling that command manually:

```bash
./scripts/start-local.sh --profile real-providers --build
./scripts/status.sh --profile real-providers
./scripts/health-check.sh --profile real-providers
./scripts/stop-local.sh --profile real-providers
```

The lifecycle limits Compose to one concurrent operation for this profile.
Every runtime container has an explicit memory ceiling, Java and Node heaps are
bounded, and local PostgreSQL instances use reduced buffers and connection
limits. These limits are part of the checked-in profile; no temporary overlay
or shell setting is required. Payment Service retains the small-service
160 MiB Java heap with a 512 MiB container ceiling because retained-ledger
cold-start reconciliation needs additional bounded native-memory headroom.

Secure application uploads depend on the exact ClamAV 1.4.5 base-image digest in
`docker-compose.yml`. Its signature database persists in the
`clamav-signatures` volume and FreshClam refreshes through the scanner-only
egress network. The healthcheck requires both a responsive daemon, alignment
with the persisted database and an embedded signature timestamp within 48
hours; Document Store waits for that health gate and independently rejects
stale signature metadata. The 4 GiB container
ceiling follows the upstream guidance for loading current signature databases.
Do not publish port 3310 or attach another service to either scanner network.

Never add `docker-compose.live.yml` to this sequence. That older job-only
overlay deliberately configures the LLM as `DISABLED` and is rejected by the
combined real-provider trust-boundary validation.

The older `local`, `e2e`, `live` and one-shot `data-acquisition` names belong
to the dedicated isolation/test helpers under `scripts/docker` and
`scripts/data`; they are not workspace lifecycle profile names.

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
