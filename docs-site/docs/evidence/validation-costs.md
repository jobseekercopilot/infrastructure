# Real-world validation costs

Report date: **10–11 August 2026**

| Provider group | Calls retained | Cost | Evidence status |
| --- | ---: | ---: | --- |
| Deterministic System Data providers | many local fixture calls | $0.00 | Measured fixture mode |
| Live job providers | 6 searches (2 each: Reed, Adzuna, JSearch) | $0.00 observable incremental charge | Completed in quarantined, non-runtime acquisition |
| Live location/route providers | 0 | $0.00 | Not run in this validation pass |
| Paid LLM quality samples | 6 successful calls; 9,325 tokens | $0.009377 | Completed through the product gateway |

Zero means no paid call was made; it does not imply the production operation is
free. The LLM figure is calculated from provider-reported input/output usage
using the dated public model rates. The internal call-by-call record is maintained in
`docs/real-world-validation-costs-2026-08-10.md`. Credentials, raw request
payloads and applicant content are deliberately excluded from this public page.
