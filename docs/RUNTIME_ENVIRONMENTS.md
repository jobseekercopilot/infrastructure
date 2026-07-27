# Runtime environments and document-path identities

This is the first bounded INFRA-08 delivery. It wires the authenticated
document path for local, E2E, and local live-provider validation. It does not
claim that a production secret manager, managed database, private object
bucket, key rotation, backup, or restore drill has been provisioned.

The machine-readable ownership and consumer allowlist is
[`config/runtime-environment.schema.json`](../config/runtime-environment.schema.json).
Compose validation fails when an approved producer and consumer do not receive
the same credential, when unrelated credentials are reused, when a credential
is shorter than 32 bytes, or when the legacy `JWT_SECRET` boundary returns.

## Profiles

| Profile | External activity | Local data boundary | Credential source |
| --- | --- | --- | --- |
| `local` | Fixture-only job, postcode, LLM and Stripe adapters | Dedicated local PostgreSQL containers and synthetic filesystem objects | Fresh ignored `.env` |
| `e2e` | Fixture-only; live job, LLM, and payment providers are forbidden | Dedicated Compose project data and synthetic filesystem objects | Fresh ignored `.env.e2e` |
| `live-provider` | Explicit live job-provider integration; LLM disabled and Stripe fixture-only | Local PostgreSQL/filesystem only; not production | Fresh ignored `.env.live`, then operator-injected job-provider credentials |
| `data-acquisition` | Explicit approved live job-provider calls only | Separate project/network; read-only fixture source and quarantined run output | Fresh ignored `.env.data-acquisition`, then operator approval and provider credentials |
| production | Outside these Compose profiles | Managed PostgreSQL plus private S3-compatible object storage and SSE-KMS | Approved deployment secret manager |

The `live-provider` name is deliberate: it means local integration against a
real external provider. It is not a production deployment profile and does not
satisfy Document Store's managed-storage attestation.

## Generate local credentials

Do not copy or populate the tracked example directly. Generate fresh values:

```bash
python3 scripts/security/generate_profile_env.py --profile local --output .env
python3 scripts/security/generate_profile_env.py --profile e2e --output .env.e2e
python3 scripts/security/generate_profile_env.py \
  --profile live-provider --output .env.live
python3 scripts/security/generate_profile_env.py \
  --profile data-acquisition --output .env.data-acquisition
```

The generator creates a new RSA-3072 signing pair and independently random
credentials, writes nothing sensitive to stdout, refuses to overwrite by
default, and sets mode `0600`. All generated files are ignored by Git.

For local validation:

```bash
docker compose --env-file .env -f docker-compose.yml config --quiet
python3 scripts/security/validate_compose_runtime.py \
  --profile local --env-file .env
```

The E2E and live-provider commands add their matching Compose overlay and
validator `--overlay` argument. Data acquisition uses only its standalone
Compose file and dedicated runner. The validator renders the Compose model in
memory and reports only pass/fail; it never prints credential values. See
[`MODE_ISOLATION.md`](MODE_ISOLATION.md) for the exact matrix and one-shot
acquisition controls.

## Trust relationships

- Authentication owns the RSA signing key, issuer/audience, its database
  credential, `AUTH_SERVICE_TOKEN`, and the System Data environment identity.
- Application Tracker owns its dedicated PostgreSQL credential plus separate
  producer and reader credentials. Document Generation and CV/Cover Letter
  receive producer access; Job Matching and Reporting receive reader access.
- Reporting Service owns a dedicated Gateway-to-Service identity. Reporting
  Gateway validates the platform access token, derives the report owner from
  its subject and supplies that identity only to Reporting Service.
- Document Store owns separate producer and reader credentials. CV/Cover
  Letter receives producer access; Export receives both because it reads and
  writes; Document Generation receives both for its current direct operations.
- Document Export and CV/Cover Letter each own a dedicated Gateway credential.
- Payment Service owns separate credentials for Payment Gateway, Stripe
  Gateway, and CV/Cover Letter. Payment Gateway and Stripe Gateway also have
  dedicated pair credentials, and the browser BFF has its own Payment Gateway
  identity. These are included because CV/Cover Letter startup and generation
  depend on the payment authorization boundary.
- System Data owns one environment-management credential shared only with the
  approved environment-data endpoints.
- Browser containers receive none of these service credentials. Job Finder
  uses the end-user bearer/JWKS boundary rather than a document service token.

The exact consumer list is tested from the schema and the rendered Compose
graph. A new consumer requires producer review, schema update, focused negative
tests, and a rotation decision; copying an existing token into an unrelated
service is forbidden.

## Rotation

For disposable synthetic local/E2E data, stop the selected Compose project and
remove its named volumes before removing the ignored environment file,
generating a replacement, and restarting all producer/consumer pairs. Removing
volumes deletes that profile's local databases and objects; never use this
sequence for data that must be retained.

When local data must be retained, rotate database roles in PostgreSQL first,
update the matching ignored environment, restart and prove health, then revoke
the former database credential. Service-to-service values can be regenerated,
but every producer/consumer pair must restart together. Do not change a
PostgreSQL container password environment value and retain an already
initialised volume: the image applies that value only during database
initialisation, and the service will fail authentication.

Production rotation remains an INFRA-08 dependency. It must use a secret
manager, staged credential support where necessary, least-privilege access,
deployment health evidence, revocation of the former value, and redacted
records. The RSA key path must retain the previous public key only for the
approved overlap needed to validate already-issued short-lived tokens.

## Storage boundary

Local and E2E use separate PostgreSQL containers for Authentication, Document
Store, Application Tracker, and Payment. Document bytes use the isolated
filesystem adapter, and the Document Store, Application Tracker, and Payment
production attestations are explicitly disabled. This is valid only for
synthetic local evidence.

The E2E overlay must not replace Authentication's PostgreSQL URL with an H2
file target. The rendered trust-graph validator rejects any Authentication
database URL that does not use the isolated `authentication-postgres` service.

Production must re-enable the attestation and supply verified-full database
TLS, managed database and backup encryption references, a private
S3-compatible bucket, managed SSE-KMS, least-privilege credentials, public
access blocking, versioning/backup or replication, and a paired
database/object restore drill. Those deployed controls remain unfinished
INFRA-08 work.

## Incident response

If a credential, signing key, environment file, request body, or token appears
in Git, an image layer, CI output, logs, screenshots, or issue text:

1. stop using the affected profile and preserve access/audit evidence;
2. revoke or rotate the exposed value at its owning producer;
3. rotate every consumer binding for that trust pair;
4. search source history, artifacts, images, logs, and Project content without
   copying the value into the incident record;
5. restore service with a newly generated/injected value and prove positive and
   negative paths; and
6. record containment, revocation, validation, and follow-up privately.

Deleting a value from the current Git tree is not revocation. Never paste a
suspected value into a GitHub issue.
