# Repository inventory

Audit date: **11 August 2026**. Revisions are the fetched `origin/develop`
heads used for the audit, not local feature-branch heads. Every listed
repository has a README. Test-file counts are structural evidence, not a claim
that every test was re-run during this documentation task; verified fleet and
E2E results are recorded separately in the confidence documentation.

## Frontend, orchestration and test repositories

| Repository | Purpose/runtime responsibility | Technology | Public boundary | Dependencies / consumers | Persistence and external systems | Test evidence | Develop SHA |
|---|---|---|---|---|---|---|---|
| `job-seeker-copilot-client` | Angular product UI plus Express SSR/same-origin BFF | Angular 21, TypeScript, Node SSR | Allowlisted `/api/**` browser routes | Calls UMG, Location, Job Finder, Document Generation/Store, Reporting and Payment Gateway | HttpOnly session cookies only; no server DB | 38 spec files plus reproducible contract/build gates | `a4833a4f6729` |
| `job-seeker-copilot-landing` | Separate public landing, waitlist and contact application | Angular 21; AWS SAM/Python backend | Public pages and waitlist/contact HTTP APIs | AWS API Gateway, Lambda, SES, DynamoDB; no runtime dependency on the authenticated app | AWS-managed state in deployed landing stack | 22 spec files plus launch/security runbooks | `dd3fc5972a05` |
| `infrastructure` | Fleet catalogue, Compose profiles, locks, bootstrap, operations and Pages docs | Docker Compose, Python, shell, MkDocs | Operator scripts; no user API | Coordinates all sibling repositories | Persistent named volumes; runtime-only secret files | Rendered-model, policy, capacity and clean-room evidence | `ddc02da0ea03` |
| `e2e` | Authoritative cross-service journeys, accessibility checks, capacity browser workload and promo automation | TypeScript, Playwright, Cucumber, Node 24 | Browser plus guarded System Data test APIs | Runs against Client and System Data | Disposable traces/screenshots/reports; generated media ignored | 38 spec/feature files; 32-scenario/244-step regression evidence | `983b63caa66a` |

## Identity, profile and location

| Repository | Purpose/runtime responsibility | Technology | Public contract | Dependencies / consumers | Persistence / providers | Test files | Develop SHA |
|---|---|---|---|---|---|---:|---|
| `authentication-service` | Accounts, password/session lifecycle and RS256 JWT issuer | Java 17, Spring Boot 4.1 | OpenAPI 1.1; `/api/auth/**`, JWKS | Called by UMG and lifecycle consumers; calls Profile/Tracker/Store for account lifecycle | PostgreSQL + Flyway; optional SES adapter | 43 | `727a3b6e4799` |
| `user-profile-service` | Subject-owned profile, preferences, Evidence Library and immutable snapshots | Java 17, Spring Boot 4.1 | OpenAPI 2.2; `/api/profiles/me`, `/api/evidence/**` | Called by UMG, Finder, Document Generation and Reporting | PostgreSQL + Flyway | 36 | `13ced1c7e913` |
| `user-management-gateway` | Browser auth/session/profile/evidence facade | Java 17, Spring Boot 3.5.16 | `/api/auth/**` | Calls Authentication and User Profile; called by Client BFF/Finder identity resolution | Stateless | 31 | `698d45b0eb83` |
| `location-gateway` | Browser-facing v1 compatibility and v2 location facade | Java 17, Spring Boot 4.1 | `GET /api/locations`, `/api/postcodes/**`; `POST /api/v2/locations/**` | Calls Location Service; called by Client BFF | Bounded in-memory rate/cache state | 27 | `0805848be15f` |
| `location-service` | Provider-neutral autocomplete, canonical resolution and commute orchestration | Java 17, Spring Boot 4.1 | Internal OpenAPI 1.0 | Calls Postcodes.io and Google Maps gateways; called by Location Gateway and Job Matching | Bounded transient suggestion sessions; no DB | 8 | `04ccdffe5e95` |
| `postcode-io-gateway` | Postcodes.io place/postcode provider boundary | Java 17, Spring Boot 4.1 | `/api/places`, `/api/postcodes`, provider mode | Calls Postcodes.io LIVE or System Data FIXTURE; consumed by Location Service | Bounded in-memory cache; no DB | 20 | `53ccda00705d` |
| `google-maps-gateway` | Sole Google Places/Routes credential and DTO boundary | Java 17, Spring Boot 4.1 | Internal OpenAPI 1.0 | Calls Google when explicitly enabled; consumed only by Location Service | Transient bounded session tokens; no provider-content DB | 6 | `bd45bda74040` |

## Job discovery, providers and matching

| Repository | Purpose/runtime responsibility | Technology | Public contract | Dependencies / consumers | Persistence / providers | Test files | Develop SHA |
|---|---|---|---|---|---|---:|---|
| `job-finder-gateway` | JWT-protected search, saved-job and application facade | Java 17, Spring Boot 3.2 | OpenAPI 1.12; `/api/jobs/**` | Calls Auth JWKS, Job, User Profile and Tracker; called by Client BFF | Stateless | 10 | `104aec5af310` |
| `job-service` | Provider fan-out, normalisation, dedupe, canonical jobs and saved snapshots | Java 17, Spring Boot 3.2 | Provider-neutral Job OpenAPI | Calls five provider gateways and Job Matching | PostgreSQL + Flyway for saved jobs; bounded search cache | 28 | `8daa37e62ed7` |
| `job-matching-service` | Reconciles jobs to application state and attaches advisory commute results | Java 17, Spring Boot 3.2 | OpenAPI `POST /api/v1/job-matches/enrich` | Calls Application Tracker and Location Service; called by Job Service | Stateless | 8 | `47826c19a744` |
| `reed-gateway` | Reed search/detail mapping | Java 17, Spring Boot 3.2 | Provider OpenAPI; search/detail/mode | Reed LIVE or System Data FIXTURE; called by Job Service | Stateless | 4 | `5437e759329b` |
| `adzuna-gateway` | Adzuna credentialed search and mapping | Java 17, Spring Boot 3.2 | Provider OpenAPI; search/mode | Adzuna LIVE or System Data FIXTURE; called by Job Service | Stateless | 6 | `d57fb6c37c34` |
| `jsearch-gateway` | OpenWeb Ninja JSearch search and mapping | Java 17, Spring Boot 3.2 | Provider OpenAPI; search/mode | OpenWeb Ninja JSearch LIVE or System Data FIXTURE; called by Job Service | Stateless | 6 | `5ba33c1b3cfb` |
| `nhs-jobs-gateway` | Official NHS Jobs Self-Serve advert mapping | Java 17, Spring Boot 3.2 | Internal provider search OpenAPI | NHS Jobs live XML API or in-service fixture; called by Job Service | Stateless | 3 | `e65efa0dc73c` |
| `apprenticeships-gateway` | DfE Display Advert API v2 snapshot and search | Java 17, Spring Boot 3.2 | Internal provider search OpenAPI | DfE live API or in-service fixture; called by Job Service | Atomic in-memory vacancy snapshot | 3 | `73daae862189` |

## Applications, documents and AI generation

| Repository | Purpose/runtime responsibility | Technology | Public contract | Dependencies / consumers | Persistence / providers | Test files | Develop SHA |
|---|---|---|---|---|---|---:|---|
| `application-tracker-service` | System of record for applications, lifecycle/events and exact document references | Java 17, Spring Boot 3.2 | OpenAPI 4.9 | Called by Finder, Document Generation, Reporting and lifecycle services; verifies Store references | PostgreSQL + Flyway | 25 | `d4b438ed81e3` |
| `document-generation-gateway` | Durable browser-facing generation, approval, export, upload, selection and recovery coordinator | Java 17, Spring Boot 3.2 | OpenAPI 2.6 | Calls Auth, Profile, Job, CV, Payment, Store, Export and Tracker | PostgreSQL operation ledger + Flyway; no document bytes retained | 25 | `f8bc05869d6a` |
| `cv-cover-letter-service` | Evidence selection projection, prompting, parsing, repair, grounding, fallback and rendered drafts | Java 17, Spring Boot 3.2 | OpenAPI 4.1 | Calls LLM and Payment; legacy Store/Tracker adapter remains | No DB; optional encrypted ≤24h rejected-output quarantine | 27 | `acc3e623c8d1` |
| `llm-gateway` | Typed provider-neutral LLM transport, bounds, audit and cost evidence | Java 17, Spring Boot 3.2 | OpenAPI 2.0 | OpenAI LIVE or System Data FIXTURE; called by CV service | Stateless circuit/admission state | 17 | `0a9dfdc1b9e2` |
| `document-store-service` | System of record for families, immutable versions, lineage, files and retention | Java 17, Spring Boot 3.2 | OpenAPI 4.1 | Called by Document Generation/BFF, Export, Tracker, Reporting; calls ClamAV/Tracker workflows | PostgreSQL + Flyway; filesystem locally or S3-compatible object provider | 41 | `205c69983c62` |
| `document-export-service` | Stateless DOCX/PDF renderer and bounded DOCX ingestion | Java 17, Spring Boot 3.2, Apache POI, OpenPDF | OpenAPI 3.0 | Calls Document Store; called by Document Generation | No DB | 15 | `e253b56bfdee` |

## Reporting, payments and deterministic tooling

| Repository | Purpose/runtime responsibility | Technology | Public contract | Dependencies / consumers | Persistence / providers | Test files | Develop SHA |
|---|---|---|---|---|---|---:|---|
| `reporting-gateway` | JWT-protected reporting facade | Java 17, Spring Boot 3.5.16 | OpenAPI 2.0; summary, journal, evidence text | Calls Reporting Service; called by Client BFF | Stateless | 8 | `721e1b980eff` |
| `reporting-service` | Read-only application/profile/document projection | Java 17, Spring Boot 3.5.16 | OpenAPI 2.1 | Calls Tracker, Store and Profile; called by Reporting Gateway | No DB; transient projection/cache state | 6 | `835f507cb02e` |
| `payment-service` | AI-credit wallet, append-only ledger and reservations | Java 17, Spring Boot 3.2 | OpenAPI 3.1 | Called by Payment/Stripe/Document Generation/CV | PostgreSQL + Flyway | 15 | `1cc75e84847e` |
| `payment-gateway` | Wallet/pricing/checkout facade; BFF boundary composed while ordinary purchasing UI remains unavailable | Java 17, Spring Boot 3.2 | OpenAPI 2.0 | Called by Client BFF; calls Payment and Stripe gateways | Stateless | 6 | `711841743fb5` |
| `stripe-gateway` | Stripe checkout and signed-webhook provider boundary | Java 17, Spring Boot 3.2 | OpenAPI 2.0 | Stripe LIVE code or System Data FIXTURE; calls Payment Service | Stateless | 7 | `3427c9999e9c` |
| `system-data-service` | Versioned synthetic fixtures, personas and guarded named-state orchestration | Java 17, Spring Boot 3.5.16 | Fixture OpenAPI 1.1 plus guarded environment APIs | Calls service-owned non-production reset/seed/verify endpoints | Versioned source-controlled synthetic datasets; bounded in-memory indexes | 30 | `ba02aeca3047` |

## Scope notes

- Repository count is an ownership/topology fact, not a quality claim.
- PostgreSQL, ClamAV, LocalStack, Portainer and Dozzle containers are runtime
  dependencies rather than application repositories.
- `main` was not used as a source of application truth. The audited integration
  branch is `develop`; the landing repository is assessed separately from the
  authenticated application stack.
- Public/private API labels describe who may call the boundary, not whether the
  source repository is publicly accessible.
