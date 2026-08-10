# Configuration reference

Infrastructure generates profile-specific, mode-`0600` environment files and validates them against `config/runtime-environment.schema.json`. This page summarises the operationally significant variables; the schema and each repository README remain exhaustive.

## Identity and service secrets

| Variable | Consumer/owner | Local requirement | Purpose | Secret? |
|---|---|---|---|---|
| `JWT_PRIVATE_KEY_BASE64` | Authentication | Generated; required | RSA signing key | Yes |
| `JWT_PUBLIC_KEY_BASE64` | Authentication | Generated; required | JWKS verification key | No |
| `JWT_ISSUER`, `JWT_AUDIENCE` | Authentication + JWT services | Defaulted to platform values | Token trust contract | No |
| `AUTH_SERVICE_TOKEN` | Authentication, UMG, Doc Gen | Generated; required | Authentication-service caller identity | Yes |
| `APPLICATION_TRACKER_PRODUCER_TOKEN` | Tracker and producers | Generated; required | Application mutation identity | Yes |
| `APPLICATION_TRACKER_READER_TOKEN` | Tracker and readers | Generated; required | Read-only application identity | Yes |
| `DOCUMENT_STORE_PRODUCER_TOKEN` | Store and producers | Generated; required | Document mutation identity | Yes |
| `DOCUMENT_STORE_READER_TOKEN` | Store and readers | Generated; required | Document read identity | Yes |
| `DOCUMENT_STORE_RETENTION_ADMIN_TOKEN` | Store | Generated; required | Restricted retention/purge administration | Yes |
| `DOCUMENT_EXPORT_GATEWAY_TOKEN` | Export and Doc Gen | Generated; required | Export caller identity | Yes |
| `CV_COVER_LETTER_GATEWAY_TOKEN` | CV service and Doc Gen | Generated; required | Draft caller identity | Yes |
| `REPORTING_GATEWAY_SERVICE_TOKEN` | Reporting pair | Generated; required | Reporting Gateway identity | Yes |
| `BFF_TO_PAYMENT_GATEWAY_TOKEN` | BFF/Payment Gateway | Generated for fleet; route disabled | Future payment caller identity | Yes |
| `*_TO_PAYMENT_SERVICE_TOKEN` | Payment callers | Generated; required | Caller-specific ledger identity | Yes |
| `ENVIRONMENT_DATA_TOKEN` | System Data + managed services | Generated; required but management disabled by base Compose | Guarded fixture management | Yes |
| `SYSTEM_DATA_INTERNAL_CALLER_KEY` | System Data/operator | Generated; required | Fixture/query boundary | Yes |

Service tokens must normally contain at least 32 bytes and caller roles that require separation reject duplicate values.

## Database secrets

| Variable | Database/service | Required locally | Secret? |
|---|---|---|---|
| `AUTH_DB_PASSWORD` | Authentication | Yes | Yes |
| `USER_PROFILE_DATABASE_PASSWORD` | User Profile | Yes | Yes |
| `JOB_SERVICE_DATABASE_PASSWORD` | Job Service | Yes | Yes |
| `DOCUMENT_GENERATION_DATABASE_PASSWORD` | Document Generation | Yes | Yes |
| `DOCUMENT_STORE_DATABASE_PASSWORD` | Document Store | Yes | Yes |
| `APPLICATION_TRACKER_DATABASE_PASSWORD` | Application Tracker | Yes | Yes |
| `PAYMENT_DATABASE_PASSWORD` | Payment | Yes | Yes |

Compose supplies internal JDBC URLs/usernames. Direct JVM development can override the corresponding `*_DATABASE_URL`/username properties documented in each repository.

## Provider modes and credentials

| Variable | Consumer | Default/requirement | Purpose | Secret? |
|---|---|---|---|---|
| `EXTERNAL_PROVIDER_MODE` | Provider gateways | `FIXTURE` in base stack | `FIXTURE`, `LIVE`, or `DISABLED` boundary | No |
| `REED_API_KEY` | Reed | Forbidden in fixture; required live | Reed API credential | Yes |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Adzuna | Forbidden fixture; required live | Adzuna application credentials | ID: sensitive; key: Yes |
| `ADZUNA_ENABLED` | Adzuna | Base `true`; environment example `false` | Provider kill switch | No |
| `ADZUNA_RESULTS_PER_PAGE` | Adzuna | 50 in Compose; bounded 1–50 | Result fan-out | No |
| `ADZUNA_PAGES_PER_SEARCH` | Adzuna | 1; bounded 1–2 | Provider pagination | No |
| `JSEARCH_API_KEY` | JSearch | Forbidden fixture; required live | RapidAPI credential | Yes |
| `JSEARCH_ENABLED` | JSearch | Base `true` | Provider kill switch | No |
| `JSEARCH_COUNTRY`, `JSEARCH_LANGUAGE` | JSearch | `gb`, `en` | Market/language | No |
| `JSEARCH_PAGES_PER_SEARCH` | JSearch | 1 | Bounded pagination | No |
| `NHS_JOBS_ENABLED`, `NHS_JOBS_RESULTS_PER_PAGE` | NHS Jobs | Enabled in reviewed live overlay; page size 1–100 | Kill switch and bounded Self-Serve request size | No |
| `APPRENTICESHIPS_API_KEY` | Apprenticeships | Forbidden fixture; required live | DfE subscription key | Yes |
| `APPRENTICESHIPS_SYNC_PAGE_SIZE`, `APPRENTICESHIPS_SYNC_MAX_PAGES` | Apprenticeships | 100 and 150; override for bounded smoke tests | Bounded Display Advert API v2 snapshot refresh | No |
| `APPRENTICESHIPS_INITIAL_SYNC_DELAY_MS`, `APPRENTICESHIPS_SYNC_DELAY_MS` | Apprenticeships | 1000 and 900000 | Initial and recurring refresh cadence | No |
| `OPENAI_API_KEY` | LLM Gateway | Forbidden fixture; required by real OpenAI overlay | Model credential | Yes |
| `GENERATION_MODEL_ID` | LLM Gateway | Fixture model ID in base | Model audit identity | No |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Stripe Gateway | Forbidden in standard profiles | Live checkout/webhook authentication | Yes |
| `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL` | Stripe Gateway | Local `/payment/success|cancel` | Redirect targets | No |

Fixture gateways also receive `SYSTEM_DATA_SERVICE_URL`, dataset ID/version, and scenario. Infrastructure owns their consistent values.

## Client/BFF

| Variable | Default | Required? | Purpose | Secret? |
|---|---|---|---|---|
| `PORT` | 3000 | Optional | SSR listen port | No |
| `USER_MANAGEMENT_GATEWAY_URL` | `http://localhost:8083` | Optional locally | Auth/profile origin | No |
| `JOB_FINDER_GATEWAY_URL` | `http://localhost:8080` | Optional locally | Job origin | No |
| `LOCATION_GATEWAY_URL` | Container/default varies | Optional locally | Location origin | No |
| `DOCUMENT_GENERATION_GATEWAY_URL` | `http://localhost:8092` | Optional locally | Generation origin | No |
| `DOCUMENT_STORE_SERVICE_URL` | `http://localhost:8089` | Optional locally | Narrow document reads/downloads | No |
| `REPORTING_GATEWAY_URL` | Configured by Compose | Required for reporting | Reporting origin | No |
| `BFF_SESSION_COOKIE_PROFILE` | `local` | Production must set `production` | Fixed cookie-name/security profile | No |
| `BFF_JSON_BODY_LIMIT_BYTES` | 65536 | Optional | Bounded JSON body | No |
| `BFF_DOWNSTREAM_TIMEOUT_MS` | 5000 | Optional | Gateway deadline | No |

Provider/API keys must never be placed in client configuration; SSR variables are server-side, but the Angular bundle is not a secret store.

## Document controls

| Variable | Base behaviour | Purpose | Secret? |
|---|---|---|---|
| `DOCUMENT_STORE_OBJECT_PROVIDER` | `filesystem` | Object-byte provider | No |
| `DOCUMENT_STORE_FILESYSTEM_ROOT` | `/app/data/objects` | Local object root | No |
| `DOCUMENT_STORE_RECOVERY_DAYS` | 30 | Recoverable delete window | No |
| `DOCUMENT_STORE_RETENTION_MAINTENANCE_ENABLED` | `false` | Scheduled retention actions | No |
| `DOCUMENT_STORE_PURGE_ENABLED` | `false` | Irreversible content purge | No |
| `REJECTED_GENERATION_QUARANTINE_ENABLED` | `true` in full Compose | Short-lived encrypted rejected output | No |
| `REJECTED_GENERATION_QUARANTINE_KEY_BASE64` | Generated | Quarantine encryption | Yes |
| `REJECTED_GENERATION_OPERATOR_TOKEN` | Generated | Recovery operator identity | Yes |

## Safe defaults

- Environment-data mutation switches are false in the base stack.
- Document purge and scheduled retention maintenance are false.
- Document Store local filesystem encryption-at-rest flags are false; this is local-development behaviour, not a production recommendation.
- Fixture provider mode is the default and real credentials are forbidden there.
- Payments remain browser-disabled regardless of composed backend configuration.
