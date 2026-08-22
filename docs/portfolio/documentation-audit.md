# Central documentation audit

Audit date: **11 August 2026**
Scope: Infrastructure operator documentation and the generated MkDocs/Pages
site. Historic dated evidence was checked for context but not rewritten when it
truthfully describes the conditions of that dated run.

## Drift findings and corrections

| Document | Documented claim | Current implementation/runtime | Class / severity | Action |
|---|---|---|---|---|
| Pages `reference/implementation-status.md` | Location/commute repositories are skeletons; Google/commute absent. | Both services are merged, catalogued, composed and healthy; client v2 routes and job-card commute UI exist. | Incorrect / critical | Corrected capability matrix, discrepancy notes and evidence boundary. |
| Pages `services/catalogue.md` | Location Service/Google Maps Gateway are non-runtime skeletons; Location Gateway calls Postcodes.io only; Matching calls Tracker only. | Catalogue/source show active Location/Google services; v2 flow and commute dependency exist. | Incorrect / critical | Corrected rows, ports, callers, dependencies and storage. |
| Pages `journeys/location.md` | Only two-gateway Postcodes.io flow; explicit warning that Google/commute do not exist. | V2 autocomplete/resolve and bounded route matrix are implemented; v1 compatibility path remains. | Incorrect / critical | Reconstructed current location and commute sequences from controllers/clients/Compose. |
| Pages `architecture/system-overview.md` | Omits Location Service/Google boundary and commute dependency. | These are active runtime domains. | Incomplete / high | Added Location domain, Google provider, v1 compatibility edge and Matching commute edge. |
| Pages `architecture/principles.md` | Says Location Service is unimplemented. | Implemented; responsibility is now deliberately split. | Obsolete / high | Replaced with current gateway/service/provider ownership. |
| Pages `services/frontend-gateways.md` | Location Gateway does not call unimplemented Location Service. | V2 BFF and gateway calls are live; Google key stays behind provider gateway. | Incorrect / high | Corrected route allowlist and Location Gateway description. |
| Pages `journeys/job-search.md` | Matching sequence omits commute assessment. | Job Matching calls Location Service for bounded eligible destinations while still avoiding suitability scoring. | Incomplete / high | Added optional sequence and semantic boundary. |
| Pages `infrastructure/runtime.md` | Omits Location/Google ports and describes `real-providers` as jobs + OpenAI only. | Services run internally on 8104/8105; profile also enables Google. | Incomplete / high | Added ports, Google smoke profile and exact real-provider state. |
| Pages `infrastructure/external-integrations.md` and `services/provider-integrations.md` | Google absent from integration matrices. | Google Places/Routes boundary exists and is opt-in. | Incomplete / high | Added provider, modes, credentials, retention and attribution boundary. |
| Pages `operations/configuration.md` | Omits operational Google variables. | Google key, enable switch, deadlines and bounded session controls are used by Compose/source. | Incomplete / medium | Added variables without secret values. |
| Pages `confidence/beta-readiness.md` | Lists live Google validation as future work. | A bounded five-result Google-attributed autocomplete was exercised through the current browser path. | Obsolete / medium | Recorded dated bounded evidence; retained reliability/production caveat. |
| `docs/MODE_ISOLATION.md` | Uses retired `local`, `e2e`, `live-provider` lifecycle names and claims normal live mode cannot enable OpenAI. | Supported catalogue profiles are `basic-fixture`, `full-fixture`, `full-local-ses`, `google-maps-smoke`, `real-job-providers`, `real-providers`; only the last enables OpenAI/Google. | Obsolete / critical | Replaced matrix/start commands while preserving acquisition safety rules. |
| `docs/location-and-commute-capability-design.md` | Header says proposed/research only. | Core design was accepted and implemented. | Misleading / high | Added a status/provenance banner; preserved original future-tense design as decision history. |
| `config/services.json` | Omits Payment from Document Generation dependencies and Document Store from Reporting Service dependencies. | Source clients and Compose use both relationships. | Incorrect / high | Corrected catalogue dependencies. |
| `config/workspace-lock.json` | Pins pre-fix revisions for LLM, Export, CV, Document Generation and Client. | Newer reviewed fixes are merged to `develop` and power the current manual runtime. | Obsolete / high | Reconciled the five revisions to fetched `origin/develop`. |

## Checked and retained as accurate

- Dated capacity reports accurately state fixture-only workload conditions and
  do not claim AWS performance.
- Dated cost reports accurately retain their own call counts and the fact that
  Google was disabled during those particular runs. A later bounded Google
  check does not rewrite historical evidence.
- AWS decision material correctly separates measured local resource use from
  modelled cloud cost and says AWS deployment is not validated.
- Document-generation journey accurately describes immutable saved-job/profile
  snapshots, selected outputs, reservation/commit, approval, export and exact
  application references. Current recovery implementation adds bounded retry,
  retained-response reconciliation and deterministic CV fallback without
  changing the ownership model.
- Data ownership/model pages correctly identify seven PostgreSQL state owners,
  local filesystem document bytes, explicit version pointers and read-only
  reporting.
- Account, application, reporting/payment and development journeys remain
  consistent with controllers and client routes. Payment wording correctly
  distinguishes the fixture-backed wallet path from unavailable live checkout.
- Runtime/operations pages correctly state that local Compose is not AWS or
  production evidence.

## Documentation model after reconciliation

```text
Repository README
  concise service ownership, API, configuration, persistence and verification

Infrastructure / Pages
  cross-service journeys, system ownership, modes, evidence and operations

Dated audits/designs
  historical decision and evidence records with an explicit current-status link
```

The audit did not remove cautious production language. It removed statements
that incorrectly described existing controlled-beta code as absent, while
retaining limits around reliability, public deployment, security assurance,
AWS and live Stripe.
