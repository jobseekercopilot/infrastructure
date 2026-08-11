# Product-confidence evidence

Last reviewed: **11 August 2026**

Job Seeker Copilot uses complementary evidence rather than one happy-path demo.
The current confidence work covers deterministic state preparation, browser
journeys, service and contract suites, adverse uploads, provider failures,
returning state, and capacity. It does not yet justify a public-beta-ready claim.

## Current evidence

| Area | Status | Evidence boundary |
| --- | --- | --- |
| Account, session and profile | Partially validated | Registration, login/logout and saved profiles have browser coverage; the new seven-persona state still needs full UI execution. |
| Job search and details | Fixture plus bounded live sample | Reed, Adzuna and JSearch were called through quarantined acquisition; four reviewed records were retained from thirteen raw results. |
| Generated application documents | Partially validated | Six live LLM cases completed; selected fixture output now passes backend generation and approval, but two browser journeys still do not surface completion within 120 seconds. Placeholder identity and weak-claim defects also remain. |
| Uploaded documents | Partially validated | Valid PDF and DOCX application uploads plus adversarial fixtures exist; profile-import/extraction is not a currently exposed end-to-end product flow. |
| Application tracking and reporting | Validated for retained demo state | Source records, mixed statuses, document references and reporting surfaces are checked; persona breadth remains incomplete. |
| Capacity | Bounded measurement | 10 sessions passed; 25 failed. No 50/100-session or registered-user capacity claim is made. |
| AWS | Calculated candidate | The candidate shape is derived from local measurements and dated prices, not an AWS load test. |

## Strongest evidence

- Service-owned state reset/seed/verify boundaries are deterministic and
  cleanup-safe.
- Provider fixtures preserve source-provider identity and deterministic failure
  modes.
- Generated-document evidence, immutable references, downloads and application
  associations have deep integration coverage.
- The retained capacity run exposes both its successful and failed concurrency
  points.

## Weakest evidence

- Live LLM sampling found placeholder identity and weak-claim defects that must
  be corrected before generated documents are used promotionally.
- Successful backend document generation and approval are not yet reflected in
  the expected browser completion state in two focused scenarios.
- CV-to-profile extraction/import is not established as a supported product
  capability, so it must not be implied by promotional material.
- The 25-session synchronous job-details boundary remains unresolved.
- The local Compose result has not been reproduced on the proposed AWS shape.

Continue with [testing and coverage](testing.md), [personas](personas.md) or the
[beta-readiness evidence](beta-readiness.md).
