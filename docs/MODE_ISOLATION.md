# Runtime and acquisition mode isolation

Infrastructure fails closed before Compose starts a stack. The stack entry
points render the selected model in memory and reject profile crossover,
live-provider credentials in fixture modes, unsafe reset/seed exposure, or a
payment/LLM provider mode that can incur external activity unexpectedly.

## Supported profile matrix

| Profile | External providers | Environment reset/seed | State and teardown |
| --- | --- | --- | --- |
| `basic-fixture` | Job, postcode and Google/LLM paths are deterministic or disabled | Disabled in normal runtime | Dedicated `job-seeker-copilot-basic` volumes; normal stop preserves state |
| `full-fixture` | Complete application; job, postcode, LLM and Stripe provider boundaries use reviewed fixtures and Google is disabled | Disabled in normal runtime; guarded E2E tooling uses explicit named-state APIs | Dedicated `job-seeker-copilot-full` volumes; reproducible fixture data |
| `full-local-ses` | Same provider boundary as `full-fixture`; account email uses the production SES adapter against LocalStack | Same as full fixture | Dedicated project/volumes; LocalStack mail is ephemeral |
| `google-maps-smoke` | Google Places/Routes may be LIVE; every other external provider remains fixture-backed | Disabled | Dedicated `job-seeker-copilot-google-maps` state; bounded live validation only |
| `real-job-providers` | Reed, Adzuna, JSearch, NHS Jobs, Find an apprenticeship and Postcodes.io may be LIVE; LLM and Stripe remain `FIXTURE`; Google remains disabled | Disabled | Dedicated `job-seeker-copilot-real-jobs` persistent volumes; not production evidence |
| `real-providers` | The same real jobs plus OpenAI and Google Maps LIVE; Stripe remains `FIXTURE` | Disabled | Reuses the persistent manual project intentionally; stop without deleting volumes |
| `data-acquisition` | Only explicitly approved job-provider gateway profiles start | System Data is a non-web `live-acquisition` command; normal environment management and fixtures are disabled | Separate quarantined project/network removed after each run |

Fixture and E2E use an internal-only application network and do not inject live
provider credentials. The rendered-model policy rejects accidental crossover.
E2E additionally requires `SPRING_PROFILES_ACTIVE=e2e`,
`DEPLOYMENT_ENVIRONMENT_CLASS=TEST` for postcode, fixture modes for every
external gateway, and the exact reset/seed allowlists.

The sole security-maintenance exception is the pinned ClamAV container. It
joins a dedicated egress bridge only to refresh public malware signatures and
a separate internal scanner bridge shared only with Document Store. ClamAV
publishes no host port, and uploaded document bytes never traverse the
signature-update network. Rendered-model tests enforce both memberships.

`real-job-providers` deliberately means live **job-provider** integration only.
`real-providers` separately opts into paid OpenAI and Google calls. Neither
profile enables real Stripe. Production/AWS configuration remains a separate
deployment workstream and is not inferred from local evidence.

## Application fixture boundary

The isolated E2E model pairs the merged Application Tracker producer at
`a217182` with the System Data consumer at `b0f79a6`. System Data pins producer
OpenAPI `3.0.0`, sends seed envelope `2.0.0`, and supplies exact immutable CV
and cover-letter document evidence.

Compose exposes the producer only as
`http://application-tracker-service:8088` on the internal stack network. Both
services receive the same generated environment-data identity, both use the
exact `e2e` profile, and Application Tracker allows fixture operations only in
that profile. The rendered-model policy rejects an external producer target,
identity mismatch, profile mismatch, or fixture enablement in local/live
modes before Compose starts.

## Runtime start

Generate the selected ignored environment through the supported lifecycle:

```bash
./scripts/bootstrap.sh --profile basic-fixture
./scripts/start-local.sh --profile basic-fixture --build
./scripts/health-check.sh --profile basic-fixture

./scripts/start-local.sh --profile real-providers --build
./scripts/health-check.sh --profile real-providers
```

The wrapper validates the rendered Compose model before `docker compose up`.
Normal stop preserves that exact project's state. Disposable fixture state can
be reset only with an explicit destructive confirmation:

```bash
./scripts/stop-local.sh --profile full-fixture --delete-volumes --yes
```

The command targets the selected fixed Compose project; it does not use a
directory glob or affect another mode's volumes.

## One-shot job-provider acquisition

This path can make real provider calls and may incur provider costs. It is not
part of routine beta verification and must not be run in CI.

```bash
python3 scripts/security/generate_profile_env.py \
  --profile data-acquisition --output .env.data-acquisition
```

Populate the ignored file only after terms and costs are approved. Required
gates include:

- a unique lowercase run ID;
- the exact confirmation `I UNDERSTAND LIVE PROVIDERS WILL BE CALLED`;
- a terms/change reference and named provenance reviewer;
- an exact approved-provider list with matching enable flags and credentials;
- a new semantic dataset version; and
- retention between 1 and 30 days.

Then an operator can deliberately run:

```bash
python3 -m scripts.data.run_acquisition \
  --env-file .env.data-acquisition \
  --secrets-env-file ../config/.secrets.env \
  --authorize-live-provider-costs
```

Only approved gateway Compose profiles start. They publish no host ports and
share only the acquisition network. System Data mounts the governed fixture
repository read-only and writes into
`system-data-service/quarantined-acquisitions/<run-id>`. A redacted
authorization/status record is written before the first provider call.
Containers and the acquisition network are removed in a `finally` path.

Output is `runtimeEligible=false` and `redistributionApproved=false`. Promotion
into the governed fixture repository is a separate reviewed task. Reject or
delete an expired run with an exact target and named reviewer:

```bash
python3 -m scripts.data.purge_acquisition \
  --run-id <run-id> \
  --reason rejected \
  --reviewer <name> \
  --yes
```

Deletion is permanent and leaves a redacted deletion record in the quarantine
root. `retention-expired` deletion is refused before the recorded date.

## Live LLM capture

The former `capture_llm_fixtures` helper is fail-closed because it could make
paid calls and write responses directly into a runtime dataset. The governed
replacement is tracked in
[BACKLOG-LLM-02](https://github.com/jobseekercopilot/infrastructure/issues/29).
Fixture, E2E, job-only live-provider and acquisition modes cannot inject an
OpenAI credential or start an LLM LIVE adapter. Only the explicit
`real-providers` overlay can enable it.
