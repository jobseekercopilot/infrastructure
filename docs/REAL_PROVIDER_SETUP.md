# Real provider configuration

The `real-job-providers` profile runs the complete local application with Reed,
Adzuna and JSearch in live mode. OpenAI and Stripe remain fixture-backed.
`full-fixture` remains the default deterministic profile and never reads real
provider credentials.

The `real-providers` profile extends `real-job-providers` with real OpenAI CV and
cover-letter generation. It reuses the same Compose project so switching the
running environment preserves local application data. Stripe remains
fixture-backed. Both profiles also reuse the existing owner-only
`.env.real-job-providers` base environment, so service identities and local
PostgreSQL data do not drift when OpenAI is enabled.

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
```

Real OpenAI generation additionally requires the following reviewed values in
the same file:

```dotenv
OPENAI_API_KEY=
OPENAI_ENDPOINT=
OPENAI_DATA_REGION=
OPENAI_DATA_CONTROL_MODE=
OPENAI_DATA_SHARING_MODE=
OPENAI_PRIVACY_DECISION_ID=
OPENAI_PRIVACY_OWNER=
OPENAI_PRIVACY_REVIEW_ON=
```

Project-scoped API keys do not require organization or project headers. If an
account uses multiple organizations or a legacy user API key, the optional
`OPENAI_ORGANIZATION_ID` and `OPENAI_PROJECT_ID` values may be added to select
the intended billing boundary explicitly.

Do not guess the required privacy settings. The endpoint must exactly match the
declared data region. The data-control, sharing, decision, owner and ISO-8601
review date must match the recorded privacy decision. The LLM gateway refuses
to start if that decision is absent, invalid or expired.

Do not place a populated copy in Infrastructure or any service repository.
Validate selected providers without printing values:

```bash
python3 scripts/security/provider_secrets.py \
  --providers ADZUNA JSEARCH \
  --check-repositories
```

Validate the complete real-provider profile without printing values:

```bash
python3 scripts/security/provider_secrets.py \
  --providers REED ADZUNA JSEARCH OPENAI \
  --check-repositories
```

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
3. `docker-compose.real-openai.yml`

Do not append `docker-compose.live.yml` before or after these files. It is a
separate legacy job-only overlay and, if applied later, resets
`llm-gateway:EXTERNAL_PROVIDER_MODE` to `DISABLED`. The `real-providers`
preflight rejects a resolved model unless Reed, Adzuna and JSearch are live,
the LLM is `LIVE`, Stripe is `FIXTURE`, and only the four live gateways join
the dedicated provider-egress network.

Starting `real-job-providers` validates the four job-provider credential names.
Starting `real-providers` validates those names plus the complete OpenAI
decision. Either command fails with only the missing variable name.
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

Each gateway should receive read permission only for its own secret names.
Production deployment and IAM resources are intentionally outside this
checkpoint.
