# Pricing and unit economics

Model date: **10 August 2026**

This is a cost-input model, not a customer-price recommendation.

## Fixed compute allocation

Using the calculated $340.33/month single-node candidate:

| Illustrative use | Sessions/month | Compute per active user | Compute per session |
| --- | ---: | ---: | ---: |
| Low: 500 users × 4 sessions | 2,000 | $0.681 | $0.1702 |
| Typical: 2,000 users × 8 sessions | 16,000 | $0.170 | $0.0213 |
| Heavy aggregate: 5,000 users × 12 sessions | 60,000 | $0.068 | $0.0057 |

These divisions do not imply that all users can be active concurrently; demand
must remain within a separately validated concurrency boundary.

## AI input

The fixture-shaped combined CV/cover-letter operation records 2,100 input and
1,600 output tokens. At the dated GPT-4.1 mini standard text rates, the
**calculated** provider cost is **$0.00340 per combined generation**. Six live
synthetic samples cost $0.009377 in total by provider-reported usage, or
$0.001563 mean; the sample is too small to replace the scenario model. Retries,
tax and failed outputs are excluded.

## Contribution model

```text
price
- VAT/payment processing where applicable
- observed AI usage
- allocated compute
- databases/storage/networking/observability
- support and other variable service cost
= contribution before broader operating cost
```

The complete assumptions and limitations are in
`docs/unit-economics-2026-08-10.md`.
