# API map

The central documentation describes APIs in context. Producer-owned OpenAPI files remain the detailed source of truth and are checked for drift by producer tests.

## Browser-facing APIs

| Boundary | Important entry points | Intended consumer |
|---|---|---|
| Client BFF | Same-origin mirrors of the routes below | Angular browser application only |
| User Management Gateway | `/api/auth/csrf`, registration/login/refresh/logout, profile and evidence routes | Client BFF |
| Job Finder Gateway | `/api/jobs/search`, provider detail, saved jobs, tracked applications/status | Client BFF |
| Document Generation Gateway | `/api/v1/document-generation/saved-jobs/{id}/operations`, operation read/approve/cancel, application document upload/status, files, families, lifecycle/replacement | Client BFF |
| Reporting Gateway | `/api/v1/reports/summary`, `/uc-journal`, `/evidence.txt` | Client BFF |
| Location Gateway | `/api/locations`, `/api/postcodes/{postcode}` | Client BFF |
| Payment Gateway | `/api/v1/payment/**` | Future BFF route; currently blocked |

The free application-document upload is
`POST /api/v1/document-generation/applications/{applicationId}/document-uploads`;
its owner-scoped operation status is read under
`/api/v1/document-generation/application-document-uploads/{operationId}`.

The browser calls only its own origin. These gateway endpoints should not be exposed as a flat public API without preserving their identity and CSRF assumptions.

## Domain APIs

| Producer | Important API purpose | Normal callers | Contract |
|---|---|---|---|
| Authentication | Account/session/JWKS/lifecycle | User Management, resource services (JWKS) | [`contracts/openapi.json`](https://github.com/jobseekercopilot/authentication-service/blob/develop/contracts/openapi.json) |
| User Profile | Current profile, evidence, snapshots | User Management, Finder, Doc Gen, Reporting | [`api/openapi.json`](https://github.com/jobseekercopilot/user-profile-service/blob/develop/api/openapi.json) |
| Job Service | Search/detail and saved jobs | Job Finder, Doc Gen | [`api/openapi.yaml`](https://github.com/jobseekercopilot/job-service/blob/develop/api/openapi.yaml) |
| Job Matching | Application-state enrichment | Job Service | [`contracts/openapi.json`](https://github.com/jobseekercopilot/job-matching-service/blob/develop/contracts/openapi.json) |
| Application Tracker | Application lifecycle/history/references/workflows | Finder, Doc Gen, Reporting, lifecycle coordinators | [`contracts/openapi.json`](https://github.com/jobseekercopilot/application-tracker-service/blob/develop/contracts/openapi.json) |
| Document Store | Families/versions/files/activity/lifecycle/uploads | Doc Gen, Export, Reporting, narrow BFF reads | [`contracts/openapi.json`](https://github.com/jobseekercopilot/document-store-service/blob/develop/contracts/openapi.json) |
| CV/Cover Letter | Estimate and generate typed drafts | Document Generation Gateway | [`contracts/openapi.json`](https://github.com/jobseekercopilot/cv-cover-letter-service/blob/develop/contracts/openapi.json) |
| Document Export | Render/export/upload | Document Generation Gateway | [`contracts/openapi.json`](https://github.com/jobseekercopilot/document-export-service/blob/develop/contracts/openapi.json) |
| Reporting | Summary/journal/evidence projection | Reporting Gateway | [`contracts/openapi.json`](https://github.com/jobseekercopilot/reporting-service/blob/develop/contracts/openapi.json) |
| Payment | Wallet/ledger/pricing/reservations | Payment, Stripe, CV, Doc Gen gateways/services | [`contracts/openapi.json`](https://github.com/jobseekercopilot/payment-service/blob/develop/contracts/openapi.json) |

Runtime `/v3/api-docs` and `/swagger-ui/index.html` availability varies. Most services enable it only outside production or behind an explicit configuration switch. Use the committed contract when a service is not running.

## Provider-facing APIs

Provider gateways expose small internal contracts to Job, Location, CV, or Payment services. Their role is to prevent provider schemas, credentials, and error details leaking into domain APIs. Reed additionally supports a detail lookup; Adzuna and JSearch search contracts are provider-specific behind Job Service adapters.

## Non-production APIs

System Data fixture and environment-management endpoints are internal. Authentication, User Profile, Application Tracker, Document Store, and Payment expose guarded `/internal/system-data/**` routes only when the explicit non-production profile and switches permit them. Do not expose or enable these in production.

## Contract update rule

1. Change the producing implementation and producer-owned contract together.
2. Run the producer's semantic drift test.
3. Update the consumer's revision/checksum lock and regenerate its client.
4. Update Infrastructure contract/workspace locks when the fleet combination is reviewed.
5. Update this site only when the workflow or responsibility changed; do not copy every schema here.
