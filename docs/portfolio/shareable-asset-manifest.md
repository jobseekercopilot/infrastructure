# Shareable asset manifest

Reviewed on 11 August 2026. Hashes identify the exact artifacts reviewed during the documentation and portfolio audit.

## Recommended application pack

| Asset | Location | Review status | Provenance and use | SHA-256 |
|---|---|---|---|---|
| Technical portfolio PDF | `infrastructure/docs/portfolio/output/Bernard-McGeever-Job-Seeker-Copilot-Technical-Portfolio-2026.pdf` | Shareable | 16-page, evidence-backed dossier built from the audited HTML source. Contains no personal email address, phone number, credentials or private-repository URLs. | `dbec2270db01ef1dfaf3fcf72addec5c2a42dea14c54257a750b052b7ce97f3a` |
| Master product showcase | `e2e/demo-recordings/final/JOB-SEEKER-COPILOT-SHOWCASE.mp4` | Shareable with fixture disclosure | 204.40-second deterministic showcase recorded from canonical System Data. Useful for demonstrating journeys; it is not evidence of live provider availability. | `5fd8a8b95aaa86812d77aed029ec69a7d417bd0a962abd748c08e05bd0b9c790` |
| Example generated CV | `e2e/demo-recordings/final/downloads/alex-taylor-java-software-developer-cv.pdf` | Shareable as a synthetic example | Fictional Alex Taylor fixture output. Demonstrates export format and workflow only; use a separately reviewed, job-specific real CV for an application. | `f8344bae60253ebb1cd891c1ea071d0675439d49ed0b2c43089ebba89fc3f276` |
| Example generated cover letter | `e2e/demo-recordings/final/downloads/alex-taylor-java-software-developer-cover-letter.pdf` | Shareable as a synthetic example | Fictional Alex Taylor fixture output. Demonstrates export format and workflow only; use a separately reviewed, job-specific real letter for an application. | `a0920d02efcab917adc9a2cda0ac32aeb8733e3f1b4bb78404e16c1053405f51` |

The job-specific CV and cover letter sent to an employer remain private candidate documents. They are not committed to Git or included in this manifest.

## Feature clips

All clips below were recorded from the deterministic fixture environment. They are safe to share when labelled accordingly.

| Clip | Duration | SHA-256 |
|---|---:|---|
| `ONBOARDING.mp4` | 19.28 s | `fd3a119704ae40373ca91b7ab02663f5cd502b8e5d6b5a4b6f7efa08768e2035` |
| `PROFILE.mp4` | 68.92 s | `78a2dc8626a2d6347cc5f87564286fecfe8dae013f559ddb733ba5976cfd14af` |
| `DISCOVER.mp4` | 8.76 s | `37c0e77123d65a63555f8da15d12801516e36cb2ca0aba4517fec6c71d6ee033` |
| `GENERATE.mp4` | 12.84 s | `13e7e1cccb886027a0cba73899c4f6b9b5caed47e6d035271c1c0986d408866e` |
| `DOCUMENTS.mp4` | 34.72 s | `c1d47eaf8126a44b5d63e27b90c4d5f6df01b23e8f189b14b03cb85e5d3d5e70` |
| `TRACKING.mp4` | 27.84 s | `70503db9bbd617bfb0f1058a0c6b5567036e6a114ca8eaec967965ab807566e8` |
| `REPORTING.mp4` | 10.68 s | `a664b8b0a1ed69b5fd5ed75d7c543782c2c29e3ca4809ab8773ad26e67133f1b` |

## Screenshot set

The portfolio embeds reviewed crops from the persistent real-provider manual environment:

- `dashboard-live.png`
- `job-search-live.png`
- `google-location-live.png`
- `generated-documents-live.png`
- `documents-live.png`
- `applications-live.png`
- `reporting-live.png`

They exclude account identity and contact data. Provider-backed vacancy screenshots are point-in-time evidence, not an availability guarantee. `google-location-live.png` uses a generic Reading search and saved no profile change.

## Distribution notes

- Send the dossier with a job-specific CV and cover letter, not the synthetic examples, unless an evaluator explicitly asks to inspect generated fixture output.
- Label the video as a deterministic product demonstration. Do not describe it as a live-provider recording.
- Rebuild and re-review hashes after changing any source, screenshot or artifact.
- Never add the real candidate CV, phone number, email, environment files, API keys, cookies or tokens to this directory.
