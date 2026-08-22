# Product-confidence evidence

Last reviewed: **11 August 2026**

Job Seeker Copilot uses complementary evidence rather than one happy-path demo.
The current confidence work covers deterministic state preparation, all seven
purpose-sized persona journeys, the authoritative beta path, service and
contract suites, adverse uploads, provider failures, returning state, bounded
live integrations and capacity. It supports the intended private-beta journey;
it does not establish AWS-scale or public-beta operational readiness.

## Current evidence

| Area | Status | Evidence boundary |
| --- | --- | --- |
| Account, session and profile | Validated intended path | Registration, onboarding, login/logout, persistence and all seven purpose-sized persona journeys pass. |
| Job search and details | Fixture plus bounded live sample | Reed, Adzuna and JSearch were called through quarantined acquisition; four reviewed records were retained from thirteen raw results. |
| Generated application documents | Bounded live path validated | Policy 2.24.0 and the live domain/gateway path cover grounded generation, rejection/repair, approval and downloadable output; the small paid sample is not a reliability forecast. |
| Uploaded documents | Validated beta scope | Valid PDF/DOCX, adverse shapes, private download and lineage pass; profile import is explicitly out of scope. |
| Application tracking and reporting | Validated deterministic scope | Exact job/document relationships persist and empty/small/rich reporting reconciles to source records. |
| Capacity | Bounded measurement | Every required level through 25 passed, but 25-session p95 was 59.45 seconds. No 50/100-session or registered-user capacity claim is made. |
| AWS | Calculated candidate | The candidate shape is derived from local measurements and dated prices, not an AWS load test. |

## Strongest evidence

- Service-owned state reset/seed/verify boundaries are deterministic and
  cleanup-safe.
- Provider fixtures preserve source-provider identity and deterministic failure
  modes.
- Generated-document evidence, immutable references, downloads and application
  associations have deep integration coverage.
- The retained capacity run exposes all required stages and the latency-limited
  25-session boundary without presenting it as an operating recommendation.

## Weakest evidence

- The paid LLM sample is intentionally small and cannot establish provider
  reliability or all-profile quality.
- CV-to-profile extraction/import is deliberately outside the current product
  promise and is not implied by promotional material.
- The 25-session journey has almost no timeout headroom, so it is not the
  recommended operating point.
- The local Compose result has not been reproduced on the proposed AWS shape.

Continue with [testing and coverage](testing.md), [personas](personas.md) or the
[beta-readiness evidence](beta-readiness.md).
