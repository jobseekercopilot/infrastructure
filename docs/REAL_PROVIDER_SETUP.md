# Real provider configuration

The `real-job-providers` profile runs the complete local application with Reed,
Adzuna, JSearch, NHS Jobs, Find an apprenticeship and the Postcodes.io location
authority in live mode. AWS Bedrock and Stripe remain fixture-backed.
`full-fixture` remains the default deterministic profile and never reads real
provider credentials.

The `real-providers` profile extends `real-job-providers` with real AWS Bedrock
CV and cover-letter generation plus Google Maps Places and Routes. It reuses the
same Compose project so switching the running environment preserves local
application data. Stripe remains fixture-backed. Both profiles also reuse the existing owner-only
`.env.real-job-providers` base environment, so service identities and local
PostgreSQL data do not drift when Bedrock is enabled.

## Local secret boundary

Provider credentials exist only in the workspace-root file:

```text
<workspace>/config/.secrets.env
```

The workspace root is not a Git repository. The file must have mode `0600` and
contain exactly these runtime names:

```dotenv
REED_API_KEY=
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
JSEARCH_API_KEY=
APPRENTICESHIPS_API_KEY=
```

Real AWS Bedrock generation additionally requires the following reviewed values
in the same file:

```dotenv
BEDROCK_MODEL_ID=
BEDROCK_REGION=
GOOGLE_MAPS_API_KEY=
```

Bedrock authenticates with the ambient AWS credential chain (an IAM role, the
standard `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN`
environment credentials, or an AWS SSO session), so there is no static provider
API key. In production the llm-gateway task assumes an IAM role granted
`bedrock:InvokeModel`; locally, supply short-lived AWS credentials in the
environment rather than in this file.

`BEDROCK_MODEL_ID` must be a model that is available in `BEDROCK_REGION`. The
reviewed value is `anthropic.claude-3-7-sonnet-20250219-v1:0` in `eu-west-2`,
which supports direct on-demand invocation and keeps generation in the UK
Region. Bedrock does not retain prompts or completions after a request and does
not use them to train the foundation models. AWS Bedrock foundation-model access
must be enabled for the account/region before first use.

Do not place a populated copy in Infrastructure or any service repository.
Validate selected providers without printing values:

```bash
python3 scripts/security/provider_secrets.py \
  --providers ADZUNA JSEARCH APPRENTICESHIPS \
  --check-repositories
```

Validate the complete real-provider profile without printing values:

```bash
python3 scripts/security/provider_secrets.py \
  --providers REED ADZUNA JSEARCH APPRENTICESHIPS BEDROCK GOOGLE \
  --check-repositories
```

In a clean sibling workspace, first run
`./scripts/bootstrap.sh --profile full-fixture`. That materialises the exact
locked `develop` revisions and builds every runtime source without using live
credentials. Then add the reviewed owner-only provider settings and start the
real profile below.

Once validation passes, start the real providers using the normal lifecycle
command:

```bash
./scripts/start-local.sh --profile real-providers --build
./scripts/health-check.sh --profile real-providers
./scripts/status.sh --profile real-providers
```

The lifecycle always resolves the combined runtime in this exact order:

1. `docker-compose.yml`
2. `docker-compose.real-job-providers.yml`
3. `docker-compose.real-bedrock.yml`
4. `docker-compose.real-google-maps.yml`
5. `docker-compose.low-memory.yml`

The final overlay carries the reviewed resource-constrained settings used for
manual beta validation. The lifecycle also limits Compose to one concurrent
operation, so `start-local.sh --profile real-providers --build` does not depend
on a temporary low-memory file or a caller-provided parallelism setting.

Do not append `docker-compose.live.yml` before or after these files. It is a
separate legacy job-only overlay and, if applied later, resets
`llm-gateway:EXTERNAL_PROVIDER_MODE` to `DISABLED`. The `real-providers`
preflight rejects a resolved model unless all five job providers are live, the
Postcodes.io authority and LLM are `LIVE`, Google Maps is enabled, Stripe is
`FIXTURE`, and each external adapter has only its dedicated egress network.

For isolated Google validation, the fixture-backed `google-maps-smoke` profile
remains available. Follow
[`GOOGLE_MAPS_ACTIVATION.md`](GOOGLE_MAPS_ACTIVATION.md); it enables only Places
API (New) and Routes API while keeping job, LLM and payment providers fixture-backed.

Starting `real-job-providers` validates the five job-provider credential names.
Starting `real-providers` validates those names plus the Bedrock model/region
settings and Google Maps key. Either command fails with only the missing variable name.
`REED_API_KEY` must contain a replacement credential; the previously tracked
value is permanently ineligible for reuse.

Stop the combined runtime without deleting retained local data:

```bash
./scripts/stop-local.sh --profile real-providers
```

Adzuna requires its application ID and key in the query string of the
TLS-encrypted outbound request to `api.adzuna.com`. This is the sole approved
URL exception. The gateway does not retain the provider exception as a cause,
does not enable HTTP-client debug logging, and returns only stable redacted
failure codes.

## Hosted mapping

The beta-hosted equivalent uses an IAM-authorised backend task or service to
resolve AWS Secrets Manager or Systems Manager Parameter Store values at
runtime. Credentials are never supplied to frontend tasks or image builds.

| Local name | Suggested AWS secret/parameter name | Runtime consumer |
| --- | --- | --- |
| `REED_API_KEY` | `/job-seeker-copilot/beta/job-providers/reed/api-key` | Reed Gateway |
| `ADZUNA_APP_ID` | `/job-seeker-copilot/beta/job-providers/adzuna/app-id` | Adzuna Gateway |
| `ADZUNA_APP_KEY` | `/job-seeker-copilot/beta/job-providers/adzuna/app-key` | Adzuna Gateway |
| `JSEARCH_API_KEY` | `/job-seeker-copilot/beta/job-providers/jsearch/api-key` | JSearch Gateway |
| `APPRENTICESHIPS_API_KEY` | `/job-seeker-copilot/beta/job-providers/apprenticeships/api-key` | Apprenticeships Gateway |

Each gateway should receive read permission only for its own secret names.
Production deployment and IAM resources are intentionally outside this
checkpoint.
