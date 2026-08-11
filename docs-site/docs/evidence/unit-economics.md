# Pricing and unit economics

Model date: **11 August 2026**

This combines a narrow cost model with transparent commercial hypotheses. It
is not an instruction to change live pricing.

## Fixed compute allocation

| Modelled use | Sessions/month | Compute/user | Compute/session |
| --- | ---: | ---: | ---: |
| 500 MAU × 4 sessions | 2,000 | $0.681 | $0.1702 |
| 2,000 MAU × 8 sessions | 16,000 | $0.170 | $0.0213 |
| 5,000 MAU × 12 sessions | 60,000 | $0.068 | $0.0057 |

The input is one calculated $340.33/month `m7i.2xlarge`. These divisions do not
imply simultaneous capacity.

## Measured and modelled AI cost

Seventeen bounded GPT-4.1 mini calls used 80,012 input and 23,419 output tokens
and cost **$0.069487**. The last complete CV-plus-cover-letter operation cost
**$0.011350**.

| Scenario | CV + cover-letter provider cost |
| --- | ---: |
| Low fixture shape | $0.00340 |
| Typical measured evidence point | $0.01135 |
| Heavy two-times-token sensitivity | $0.02270 |

## Candidate pricing scenarios

| Candidate | Example AI allowance | Typical LLM cost of allowance |
| --- | ---: | ---: |
| Free/trial | 1 operation | $0.011 |
| £5 light | 5 operations | $0.057 |
| £10 standard | 20 operations | $0.227 |
| £20 intensive | 60 operations | $0.681 |

The packages are GBP hypotheses while cost inputs are USD; no exchange-rate or
gross-margin claim is made. Customer value, conversion, support and market
positioning matter more than token arithmetic. Database, storage, networking,
observability, payment, tax, external-provider and operating costs remain to be
added. Full assumptions are in `docs/unit-economics-2026-08-11.md`.
