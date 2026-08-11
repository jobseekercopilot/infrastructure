# Real-world validation costs

Report date: **11 August 2026**

| Provider group | Measured use | Spend |
| --- | ---: | ---: |
| OpenAI | 17 calls; 80,012 input / 23,419 output tokens | **$0.069487** |
| Live job providers | bounded Reed, Adzuna, JSearch, NHS Jobs and Apprenticeships requests | $0.00 observable incremental charge |
| Google Maps | disabled | $0.00 |
| Live Stripe | not run; fixture only | $0.00 |
| AWS | no resources created | $0.00 |

Zero monetary charge does not mean a production call is free: job-provider
quota was consumed and production prices remain provider/account dependent.
Secrets, raw prompts, outputs and authorization data are excluded. The
reconciled ledger is in `docs/real-world-validation-costs-2026-08-11.md`.
