# README audit

Audit date: **11 August 2026**
Scope: all 31 sibling repositories in the Job Seeker Copilot workspace.
Authority order: source/runtime → current contracts/config/tests → central docs
→ repository README → historic material.

The audit used each README in full, fetched `origin/develop`, producer OpenAPI
where present, controllers, application configuration, persistence migrations,
consumer clients, `config/services.json`, Compose profiles, test trees and the
running `real-providers` environment. The runtime check reported **28 healthy
application services**. A normal browser flow also returned five suggestions
with required `GOOGLE_MAPS` attribution; no profile change was saved.

## Material discrepancies

| Repository | README claim | Actual implementation/evidence | Class / severity | Correction |
|---|---|---|---|---|
| `google-maps-gateway` | Repository skeleton; no API, configuration, port or Compose entry on `develop`. | Spring Boot service, internal OpenAPI, Places/Routes client, service-token filter, transient session store, port 8105, Compose/catalogue entries and a bounded live browser result all exist on `develop`. | Incorrect / critical | Replaced the skeleton warning with implemented-but-disabled-by-default status and bounded-live evidence limits. |
| `location-service` | Skeleton outside the runtime; no callable API or Google path. | Internal OpenAPI exposes autocomplete, resolve, postcode and commute matrix; source calls Postcodes.io/Google gateways; service is composed and healthy on port 8104. | Incorrect / critical | Documented current ownership, runtime inclusion and safe default. |
| `location-gateway` | Does not call Location Service; calls Postcode.io Gateway only. | V2 autocomplete/resolve uses a generated Location Service client. Compatibility GET routes use the same `LOCATION_SERVICE_URL`; the gateway never receives the Google key. | Incorrect / high | Corrected role, dependencies, environment variables and API list. |
| `job-matching-service` | Application-state enrichment only; flow omits Location Service. | Application reconciliation remains the primary “matching” meaning, but source also shortlists ≤5 eligible destinations and requests advisory commute matrices from Location Service. It still does **not** calculate suitability/skill scores. | Incomplete / high | Added commute dependency and explicitly preserved the no-suitability-score boundary. |
| `e2e` | Default URL 4200; default recorder produces legacy `REGISTER/APPLY/...` clips. | Configuration defaults to loopback port 3100. `npm run record` calls `record-product-showcase.js`, producing a 204.4s master and `ONBOARDING`, `PROFILE`, `DISCOVER`, `GENERATE`, `DOCUMENTS`, `TRACKING`, `REPORTING`. | Obsolete / high | Corrected variables, outputs and current-vs-legacy recording guidance. |
| `system-data-service` | “Not operationally or beta ready”; describes only an initial migration baseline. | The governed datasets, persona catalogue and guarded named-state APIs are the active deterministic fixture path used by cross-service regression and promotional automation. It remains strictly non-production. | Obsolete / high | Reframed as operational non-production tooling; retained migration exclusions as history. |
| `document-generation-gateway` | Runtime database and cross-user E2E evidence remain outstanding. | PostgreSQL operation ledger is composed and persisted; selection, generation, approval, export, linking and recovery paths have focused cross-service/browser evidence. | Obsolete / high | Documented controlled-beta exercise while retaining production availability limits. |
| `cv-cover-letter-service` | Gateway still needs to adopt pure draft workflow; safe use forbids any real profile or paid model request while “pre-beta.” | Current gateway consumes selected-output drafts. The authorised manual environment uses real OpenAI with durable operation identity, bounded retry/recovery and deterministic CV fallback. Automated tests remain fixture-only. | Obsolete/misleading / high | Corrected delivery state and separated CI safety from explicitly authorised private manual use. |
| `llm-gateway` | Automatic retries remain disabled pending idempotency/quota controls. | Current approved document flow supplies stable operation identity, wallet reservation and bounded retry/audit fields; retry remains limited to classified safe failures. | Obsolete / high | Documented bounded retry and explicitly withheld reliability/production claims. |
| `document-export-service` | Gateway still has to adopt its identity contract. | Current Document Generation Gateway supplies the dedicated authenticated export identity and operation-derived idempotency. | Obsolete / medium | Removed the completed adoption blocker; retained replacement/production limitations. |
| `document-store-service` | Approved consumers/Infrastructure have not completed identity rollout, implying the ordinary local path is unavailable. | Controlled-beta consumers are composed with distinct tokens; local Store uses persistent PostgreSQL, filesystem bytes and ClamAV. Managed S3/KMS/backups remain production work. | Misleading / high | Split demonstrated local beta state from uncompleted production storage rollout. |
| `job-seeker-copilot-client` | Normal application has fixture-backed document generation. | Fixture remains default, but the supported `real-providers` profile routes the same UI through real OpenAI. | Incomplete / medium | Added explicit optional real-OpenAI mode without implying it is default. |
| `reporting-gateway` | Exposes two operations. | Contract/controller also expose `GET /api/v1/reports/evidence.txt`. | Incomplete / medium | Added the third operation. |
| `reporting-service` | Describes summary/activity/journal but omits text evidence endpoint. | OpenAPI 2.1 and controller expose summary, journal and evidence text. | Incomplete / medium | Added evidence export to scope and API wording. |
| `reed-gateway` | Migration candidate; not beta-ready. | Producer contract, fixture/live adapters and bounded resilience are implemented and composed; live path was sampled through the product. | Obsolete / medium | Reframed as controlled-beta, default-fixture provider boundary; no reliability claim. |
| `adzuna-gateway` | Migration candidate; not beta-ready. | Same current delivery boundary as Reed, with credential/paging differences. | Obsolete / medium | Corrected status and evidence limits. |
| `jsearch-gateway` | Migration candidate; not beta-ready. | Same current delivery boundary as Reed/Adzuna via RapidAPI. | Obsolete / medium | Updated the existing documentation PR rather than creating a duplicate. |
| `authentication-service` | Generic “not beta-ready” warning obscures the implemented account/session path. | Registration/login/refresh/logout/reset/JWKS, PostgreSQL persistence and session-cookie journey are composed and exercised. Production lifecycle/security assurance remains separate. | Misleading / medium | Replaced with controlled-beta delivery wording and preserved production gaps. |
| `user-profile-service` | Generic “not beta-ready” warning. | Profile, preferences, evidence revisions/snapshots and PostgreSQL persistence are active in manual/E2E journeys. | Misleading / medium | Corrected status; retained production assurance caveat. |
| `user-management-gateway` | Generic “not beta-ready” warning. | Browser session, CSRF, auth/profile/evidence facade is composed and exercised. | Misleading / medium | Corrected status; retained audit references. |
| `job-finder-gateway` | “Not yet beta-ready.” | JWT-protected search/saved job/application facade is the active BFF downstream boundary. | Misleading / medium | Corrected controlled-beta status. |
| `job-service` | “Not beta-ready.” | Five-provider bounded fan-out, canonicalisation, dedupe, saved snapshots and degradation are active in the controlled beta path. | Misleading / medium | Corrected controlled-beta status. |
| `postcode-io-gateway` | Only Location Gateway consumes it; generic “not beta-ready.” | Location Service is the primary consumer; live/fixture provider boundary is composed and exercised. | Incorrect/misleading / medium | Corrected caller and status. |
| `application-tracker-service` | “Sanitised audit baseline, not a beta-ready system.” | PostgreSQL application lifecycle and exact document reference path are active in browser/E2E/manual journeys. | Misleading / medium | Corrected current delivery status; retained production caveat. |

## Audited with no material correction required

| Repository | Finding |
|---|---|
| `apprenticeships-gateway` | Purpose, Display Advert API v2, bounded snapshot, configuration and in-memory persistence agree with source. |
| `nhs-jobs-gateway` | Official NHS Self-Serve XML boundary, fixture/live modes and search contract agree with source. |
| `payment-service` | PostgreSQL wallet/reservation ledger description is accurate; controlled fixture validation does not imply live payments. |
| `payment-gateway` | Correctly says backend is composed while browser path remains unavailable. |
| `stripe-gateway` | Correctly describes implemented fixture/backend boundary and lack of an approved standard live profile. |
| `job-seeker-copilot-landing` | Correctly separates the public Angular/AWS stack from the authenticated application and withholds launch-ready claims. Existing documentation PR remains separate. |
| `infrastructure` | Current supported profiles and bootstrap model are accurate. The separate central-doc drift is recorded in `documentation-audit.md`. |

## Corrections deliberately not made

- Historical `docs/BETA_READINESS_AUDIT.md` files were not rewritten. They are
  valuable evidence of the hardening baseline; current status now sits in each
  README and central confidence pages.
- Payment and Stripe warnings were retained because real checkout is still not
  a supported browser capability.
- “Job Matching” was not renamed and no suitability score was invented. The
  documentation explicitly explains application reconciliation plus advisory
  commute enrichment.
- No product code was changed to make documentation claims easier.
