# Real-world validation costs — 2026-08-10 to 2026-08-11

## Evidence boundary

This ledger records billable external calls made specifically for the
real-world product-confidence validation. Deterministic fixture requests and
local Docker/Playwright work are not provider-billed and are listed separately
from optional live verification.

| Provider | Operation | Calls | Tokens/units | Cost | Purpose | Reusable fixture? |
| --- | --- | ---: | ---: | ---: | --- | --- |
| System Data (local) | Job, postcode, Stripe and LLM fixture responses | many | local requests | $0.00 | Repeatable regression and promotional state | Yes; canonical synthetic fixtures |
| Reed | Search sampling | 2 | 2 requests | $0.00 observable incremental charge | Current nullable/salary/description shape | Private quarantined evidence only |
| Adzuna | Search sampling | 2 | 2 requests | $0.00 observable incremental charge | Current empty-result behaviour | Private quarantined evidence only |
| JSearch | Search sampling | 2 | 2 requests | $0.00 observable incremental charge | Current employment/remote/description shape | Private quarantined evidence only |
| Live location providers | Location/route sampling | 0 | 0 | $0.00 | Optional location realism | Not run |
| OpenAI | Six-case CV/cover-letter quality sample through `llm-gateway` | 6 successful; 1 rejected before generation | 4,622 input / 4,703 output | $0.009377 | Grounding, latency, token and quality review | No; private synthetic review evidence only |

**Usage-calculated paid validation spend: $0.009377.** The rejected LLM request
reported no generation usage and adds $0.00. The provider accounts exposed no
per-request monetary charge to the runner, so the six search requests record
$0.00 observable incremental spend while consuming provider quota.

The six successful calls used `gpt-4.1-mini-2025-04-14`, with `store=false`,
data sharing disabled, synthetic personas, a 1,600-token output cap and one
concurrent provider call. Latency ranged from 6,349 to 13,466 ms (9,461 ms
mean). The private, mode-0600 evidence file is
`/tmp/jsc-live-llm-validation-2026-08-11.json`; it is deliberately not a
committed fixture.

## Safety and reproducibility

- Live and paid modes remain disabled by default.
- No API key, token, request authorization header or applicant document is
  recorded in this report.
- All users and documents are fictional.
- Aggregate call/token/cost evidence is committed; credentials and full live
  outputs are not.
