# Detailed engineering portfolio evidence map

Internal traceability for the v2 detailed dossier. Public prose deliberately avoids private-repository links; this map records the supporting repository, source/report and selected historical change. All evidence was reviewed on 11 August 2026.

| Claim or dossier section | Current implementation/runtime evidence | Historical evidence |
|---|---|---|
| 31 meaningful repositories form the reviewed workspace | `docs/portfolio/repository-inventory.md`; `config/services.json` | Infrastructure PR #95 documentation audit |
| 28 application services are healthy in the persistent manual environment | `scripts/health-check.sh --profile real-providers`; dated runtime check | Infrastructure PR #94 enabled resilient live manual provider/AI testing |
| Browser identity uses HttpOnly cookies and a same-origin BFF | Client `src/server.ts`, `src/server/bff-boundary.ts`; UMG browser-session contract | Client PRs #15–18 removed browser token storage and hardened the BFF |
| Authentication owns durable account/session state and RS256/JWKS | Authentication controllers, migrations and security configuration | Authentication PRs #16, #18 and #24 |
| Profile data is structured, revisioned evidence rather than one biography string | User Profile evidence models, migrations, `EvidenceLibraryService`, `EvidenceSnapshotService` | Client PR #58; User Profile/Doc Generation/CV PR sequence on 29 July |
| Evidence snapshots are purpose-bound, immutable and digested | User Profile `EvidenceSnapshot*`, `ProfileDigestCalculator`; OpenAPI 2.2 | CV PR #25; Document Generation PRs #71 and #73 |
| Five provider domains are integrated | Job Service adapters and provider coordinator; provider gateway OpenAPI/contracts | Feature #36 PRs across NHS, apprenticeships, Job Service, Finder, Client, E2E and Infrastructure |
| Live/fixture/disabled provider state is explicit | Compose profiles; provider mode endpoints; `docs-site/docs/infrastructure/external-integrations.md` | Infrastructure PRs #48, #51, #83, #88 and #94 |
| Job Service canonicalises heterogeneous provider records | `CanonicalJobMappingSupport`, provider adapters and Job OpenAPI | Job Service PRs #13, #17, #24, #29 and #30 |
| Deduplication retains provider/source provenance | `JobDeduplicationService`, `CanonicalUrlPolicy`, saved snapshot entities/tests | Job Service PR #35 preserved commute eligibility through dedupe |
| “Matching” is application reconciliation plus advisory commute, not skill scoring | Job Matching controller/service and Location client | Job Matching PR #15; corrected central documentation in Infrastructure PR #95 |
| Applications own lifecycle and immutable activity | Application Tracker entities, migrations and `ApplicationRecordService` | Application Tracker PRs #26, #39 and #42 |
| Applications select exact document versions atomically | Application Tracker atomic selection controller/service and verifier | Tracker PRs #29–#31; Client PRs #71–#74; Document Generation PRs #90–#95 |
| Generation could complete while application association was missing | E2E failure evidence and recovery tests | Document Generation PR #120; Client #97; E2E #36; System Data #38 |
| Document families contain immutable versions and explicit pointers | Document Store entities/migrations/OpenAPI; central document journey | Document Store/Tracker/Client version-history stories and PRs on 7–9 August |
| Uploaded documents cross a bounded scanner boundary | Document Store upload/scanning source; Compose ClamAV service | Document Store PR #37; Infrastructure PR #71; Tracker #40; Generation #114 |
| Export is stateless, replay-safe and produces DOCX/PDF | Document Export renderers, OpenAPI and tests | Export PR #17; PR #21 restored hierarchy and pagination |
| Generation starts from saved-job and evidence snapshots | Durable Generation Service and central sequence diagram | Generation PRs #71/#73; CV PRs #25/#26 |
| Model output is parsed as a strict typed response | CV parsing services/schemas and parser tests | CV PRs #27–#32 and #60–#63 |
| Claims must resolve to approved evidence paths | `ClaimEvidenceValidator`, `ClaimEvidenceCatalogFactory`, validated ledger DTOs/tests | CV PRs #20, #25, #26, #37, #45 and #46 |
| Harmless duplicate structure can be repaired without semantic invention | CV structural-repair path and duplicate-normalisation tests | CV PR #69 and production-safe recovery PR #71 |
| Unknown paid outcomes are reconciled before retry | Generation operation state, durable checkpoints and recovery controller/tests | Document Generation PR #122 |
| LLM retry is bounded and classified | LLM Gateway retry/audit policy and tests | LLM Gateway PR #27 |
| Deterministic fallback can complete a safe CV after model rejection | `DeterministicCvFallbackService` and fallback contract/tests | CV PRs #69 and #71 |
| Wallet reservations protect paid generation from duplicate charging | Payment reservation entities/repositories/service; Generation stable operation keys | Payment authorisation work; Generation recovery PRs #75, #79, #101, #104 and #122 |
| Google provider credentials and DTOs remain isolated | Google Maps Gateway source/OpenAPI; Location Service clients; Compose secret mount | Feature 34 PR sequence; Infrastructure PRs #67–#79 |
| Reporting reads owner-scoped upstream truth and does not mutate it | Reporting clients/controllers and evidence endpoint | Reporting Service PR #21; Infrastructure PR #55 |
| System Data provides governed deterministic personas/named states | System Data datasets, controllers and non-production guards | System Data PRs #9–#19; E2E PRs #8/#9 |
| Product-showcase media is executable test output | E2E recorder, product-showcase feature/steps and recording report | Current final recording dated 11 August; E2E README correction PR #41 |
| Regression evidence is 32 scenarios / 244 steps | `docs-site/docs/confidence/testing.md`; retained E2E reports | Private-beta closure PR set on 11 August |
| Capacity ladder completed 1/5/10/15/20/25 | `docs/capacity-report-2026-08-11.md`; raw benchmark results | Infrastructure capacity correction and closure work |
| The earlier 0/25 result was a frontend identity-stability defect | `docs/aws-capacity-decision-2026-08-10.md` and `2026-08-11.md`; E2E capacity feature | Stable provider-job tracking correction before final benchmark |
| 25 sessions were functional but not comfortable capacity | Session p95 59.449 s, response p95 546 ms, peak Docker memory 8.64 GiB | Capacity decision selected 15 as cautious local point; no 50-session run |
| Live LLM validation spend was $0.069487 for 17 calls | `docs/real-world-validation-costs-2026-08-11.md`; LLM usage evidence | Controlled paid validation under Infrastructure PR #94 profile |
| Rich-profile testing exposed duplicate structure and output/deadline limits | Real-manual incident evidence, CV/Gateway/LLM tests and current recovery source | CV PR #69; LLM #27; Generation #122; Export #21; CV #71 |
| Contracts are producer-owned and generated reproducibly | ADR 0002; contract lock/checksum scripts; producer OpenAPI and consumer build plugins | Migration PRs from 20–27 July; Infrastructure PRs #20/#24/#25 |
| Seven services own PostgreSQL state | Compose database services and `docs-site/docs/architecture/data-ownership.md` | Persistence migrations across identity/profile/job/app/document/payment/generation |
| Main authenticated application is not deployed or load-tested on AWS | AWS capacity decision documents and current runtime docs | Deployment blocker `infrastructure#38` remains blocked |
| Live browser Stripe purchasing remains disabled | Client BFF payment route and Payment Gateway README/runtime profile | Client PR #19 fail-closed route; payment epic remains post-beta |
| Bernard’s role is product conception, engineering direction, integration and evaluation with AI assistance | Git/PR/issue history, architectural decision records, real-user audits and iterative acceptance feedback | Portfolio brief and documented delivery history; no claim that every line was manually typed |

## Evidence-handling rules

- Dated reports support only the environment and revisions named in those reports.
- A live-provider sample proves a current path and response shape, not provider reliability.
- Structural test-file counts are not represented as executed totals unless a retained result records execution.
- Private URLs are useful internally but omitted from the public dossier.
- Bernard’s runtime profile, CV, contact details, credentials and provider secrets remain outside Git and portfolio assets.
