# Unit economics and pricing scenarios — 2026-08-11

## Evidence classes

- **Measured:** the fresh fixture capacity ladder and 17 bounded live OpenAI
  calls through the product gateway.
- **Calculated:** arithmetic using the measured values and dated public rates.
- **Modelled:** example user mixes and candidate commercial packages. These
  are not forecasts or an instruction to change live prices.

## Fixed compute

The bounded-beta compute input is one calculated London On-Demand
`m7i.2xlarge`: **$340.33/month**. It is not total infrastructure cost.

| Modelled use | Sessions/month | Fixed compute/user | Fixed compute/session |
|---|---:|---:|---:|
| 500 MAU × 4 sessions | 2,000 | $0.681 | $0.1702 |
| 2,000 MAU × 8 sessions | 16,000 | $0.170 | $0.0213 |
| 5,000 MAU × 12 sessions | 60,000 | $0.068 | $0.0057 |

These divisions do not imply simultaneous capacity. The measured comfortable
point is about 15 active DISCOVER journeys; 25 passed with only 0.55 seconds of
p95 headroom against the journey timeout. A second node doubles this compute
input before adding any load balancer or managed database.

## AI generation

The configured live model is `gpt-4.1-mini-2025-04-14`. Official OpenAI
documentation lists standard text pricing at
[$0.40 per million input tokens and $1.60 per million output tokens](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

Seventeen bounded calls used 80,012 input and 23,419 output tokens. Summing the
gateway's per-call micro-USD values gives **$0.069487** total validation spend.
The last complete grounded CV-plus-cover-letter operation made two calls,
using 13,729 input and 3,661 output tokens for **$0.011350**.

| Scenario | Basis | Calculated provider cost per CV + cover-letter operation |
|---|---|---:|
| Low | governed 2,100-input / 1,600-output fixture shape | $0.00340 |
| Typical evidence point | final measured two-call grounded operation | $0.01135 |
| Heavy sensitivity | twice the final operation's tokens | $0.02270 |

The live sample is quality and cost evidence, not a usage forecast. Retries,
rejected output, longer evidence libraries, taxes and future model changes can
raise cost. Search-provider and Google Maps production costs remain unknown;
fixture-mode zero spend must not be treated as a zero-price production input.

## Modelled monthly per-user subtotal

This deliberately combines only EC2 compute allocation and LLM usage. It
excludes the material costs listed below.

| Modelled cohort | AI operations/user | LLM cost/user | Fixed compute/user | Partial subtotal/user |
|---|---:|---:|---:|---:|
| Low: 500 MAU | 2 at $0.00340 | $0.0068 | $0.6807 | $0.6875 |
| Typical: 2,000 MAU | 10 at $0.01135 | $0.1135 | $0.1702 | $0.2837 |
| Heavy: 5,000 MAU | 30 at $0.02270 | $0.6810 | $0.0681 | $0.7491 |

## Candidate customer-pricing view

These are transparent product hypotheses, denominated in GBP, while the cost
inputs above are USD. No exchange-rate or gross-margin claim is made.

| Candidate | Example allowance | Typical LLM cost of allowance | Product rationale |
|---|---:|---:|---|
| Free / trial | upload and tracking; 1 AI operation | $0.011 | Demonstrate value without open-ended generation liability. |
| £5/month light | 5 AI operations | $0.057 | Occasional tailored applications. |
| £10/month standard | 20 AI operations | $0.227 | Regular job search with predictable usage. |
| £20/month intensive | 60 AI operations | $0.681 | High application volume with a clear fair-use boundary. |

An “AI operation” here means one combined CV-plus-cover-letter generation for
cost modelling; product credit semantics and separately generated documents
must be aligned before publishing packages. Price is a product decision driven
by customer value, conversion, support and market positioning—not merely AWS
and token arithmetic.

## Missing cost inputs and next measurement

Before approving a public price, add RDS, EBS/object storage, backups, load
balancer, NAT/data transfer, public IPv4, logging, monitoring, support, payment
fees, tax and engineering operations. Measure paid job search and route usage,
generation retries, document storage growth and actual light/typical/heavy user
distributions. Recalculate when the model, prompt policy or AWS topology
changes.
