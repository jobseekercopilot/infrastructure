# Runtime and acquisition mode isolation

Infrastructure fails closed before Compose starts a stack. The stack entry
points render the selected model in memory and reject profile crossover,
live-provider credentials in fixture modes, unsafe reset/seed exposure, or a
payment/LLM provider mode that can incur external activity unexpectedly.

## Mode matrix

| Mode | External providers | Environment reset/seed | State and teardown |
| --- | --- | --- | --- |
| `local` | Job, postcode, LLM and Stripe gateways use reviewed System Data fixtures | Disabled | Dedicated `job-seeker-copilot-local` volumes; stop with the matching stack command |
| `e2e` | Fixture-only; live credentials are not injected | Enabled only under the exact `e2e` profile and allowlist | `job-seeker-copilot-e2e` volumes and ports; disposable synthetic state |
| `live-provider` | Reed, Adzuna, JSearch and postcode may be LIVE; LLM is `DISABLED`; Stripe remains `FIXTURE` | Disabled | Dedicated `job-seeker-copilot-live` volumes; not production evidence |
| `data-acquisition` | Only explicitly approved job-provider gateway profiles start | System Data is a non-web `live-acquisition` command; normal environment management and fixtures are disabled | Separate `job-seeker-copilot-data-acquisition` project, network and quarantine; containers/network are removed after every run |

Local and E2E use an internal-only Compose network with no external egress.
They can contain live credentials in an ignored operator file without receiving
them in a container. The rendered-model policy rejects any accidental
injection. E2E additionally requires `SPRING_PROFILES_ACTIVE=e2e`,
`DEPLOYMENT_ENVIRONMENT_CLASS=TEST` for postcode, fixture modes for every
external gateway, and the exact reset/seed allowlists.

The sole security-maintenance exception is the pinned ClamAV container. It
joins a dedicated egress bridge only to refresh public malware signatures and
a separate internal scanner bridge shared only with Document Store. ClamAV
publishes no host port, and uploaded document bytes never traverse the
signature-update network. Rendered-model tests enforce both memberships.

The local live-provider stack deliberately means live **job-provider**
integration only. It does not enable paid LLM content or real Stripe charges.
Production/AWS configuration remains a separate deployment workstream and is
not inferred from these local profiles.

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

Generate an ignored environment and use the stack wrapper:

```bash
python3 scripts/security/generate_profile_env.py --profile local --output .env
python3 -m scripts.docker.start_stack local --build

python3 scripts/security/generate_profile_env.py \
  --profile e2e --output .env.e2e
python3 -m scripts.docker.start_stack e2e --build
```

`start_stack` runs `validate_compose_runtime.py` before `docker compose up`.
The older rebuild helper also requires an explicit `local`, `live` or `e2e`
stack and delegates to this guarded entry point; it can no longer start bare
Compose.
Normal stop preserves that exact project's state. Disposable local/E2E state
can be reset only with an explicit destructive confirmation:

```bash
python3 -m scripts.docker.stop_stack e2e --delete-volumes --yes
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
Normal local, E2E, live job-provider and acquisition modes cannot inject an
OpenAI credential or start an LLM LIVE adapter.
