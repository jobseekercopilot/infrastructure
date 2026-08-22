# Real-world validation costs — 2026-08-11

## Paid-call ledger

| Provider | Validation | Measured usage | Usage-calculated spend |
|---|---|---:|---:|
| OpenAI | grounded CV and cover-letter calls through `llm-gateway` | 17 calls; 80,012 input / 23,419 output tokens | **$0.069487** |
| Reed, Adzuna, JSearch, NHS Jobs and Apprenticeships | bounded real search/shape validation | provider requests and quota consumed | $0.00 observable incremental charge |
| Google Maps | disabled for the final validation | 0 calls | $0.00 |
| Stripe | fixture mode only | 0 live calls | $0.00 |
| AWS | no deployable credential/tooling path | no resources created | $0.00 |

**Total usage-calculated paid validation spend: $0.069487.** No GBP-denominated
charge was incurred by the validation runner. Provider dashboards did not
expose a per-request monetary charge for the bounded job-source calls, so their
incremental monetary value is recorded as zero while explicitly acknowledging
quota consumption.

The first six live OpenAI calls used 4,622 input and 4,703 output tokens and
cost $0.009377. Eleven later calls used 75,390 input and 18,716 output tokens
and summed to $0.060110. The final two-call product operation accounted for
$0.011350 of that latter amount. Per-call micro-USD rounding explains why a
single aggregate-token multiplication may differ by a few microdollars.

## Controls

- The live model was `gpt-4.1-mini-2025-04-14`, with synthetic people and
  `store=false`.
- Secrets, authorization headers and full private live outputs are not
  committed.
- Fixture and capacity runs explicitly disabled real providers and paid AI.
- Rejected requests with no provider usage add $0.00.
- No AWS, Google Maps or live Stripe success is inferred from local fixtures.

The cost ledger is validation evidence, not a production forecast. Current
model pricing is sourced from the
[official OpenAI model page](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
