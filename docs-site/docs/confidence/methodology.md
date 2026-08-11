# Evidence methodology

## Claim classes

- **Measured:** observed directly in a retained test or benchmark result.
- **Calculated:** arithmetic from measured inputs and dated external prices.
- **Projected:** a scenario beyond tested evidence.
- **Planned / not verified:** necessary work with no supporting result yet.

Dates, environment and provenance accompany evidence-dependent claims. A
fixture result proves repeatable product behaviour, not current provider uptime.
A live sample proves one response shape or generation, not regression stability.

## Public-safety boundary

This site is treated as public because it is deployed by GitHub Pages to a
custom public domain. It includes fictional persona summaries, aggregate test
results, public list prices and architectural decisions. It excludes:

- credentials, tokens and configuration values;
- private service URLs and internal hostnames;
- raw applicant/document content;
- exploitable security findings;
- unreviewed live provider payloads;
- private operational telemetry.

## Provenance

Capacity evidence is retained as reviewed JSON under
`benchmark-results/baseline/2026-08-10/` and rendered into the dated capacity
report. AWS and unit-economics pages cite their dated internal reports and
official public pricing sources. Persona summaries derive from the canonical
System Data persona catalog; detailed internal coverage remains in the E2E
audit.

## Missing data

Missing measurements are displayed as unknown or not validated. They are never
substituted with zero. In particular, fixture-mode provider spend of $0 does
not mean production provider cost is zero.
