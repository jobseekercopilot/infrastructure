# Real job-provider configuration

The `real-job-providers` profile runs the complete local application with Reed,
Adzuna and JSearch in live mode. OpenAI and Stripe remain fixture-backed.
`full-fixture` remains the default deterministic profile and never reads real
provider credentials.

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

Do not place a populated copy in Infrastructure or any service repository.
Validate selected providers without printing values:

```bash
python3 scripts/security/provider_secrets.py \
  --providers ADZUNA JSEARCH \
  --check-repositories
```

Starting `real-job-providers` validates all four variables and fails with only
the missing variable name. `REED_API_KEY` must contain a replacement credential;
the previously tracked value is permanently ineligible for reuse.

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
