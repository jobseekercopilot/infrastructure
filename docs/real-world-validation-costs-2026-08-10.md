# Real-world validation costs — 2026-08-10

## Evidence boundary

This ledger records billable external calls made specifically for the
real-world product-confidence validation. Deterministic fixture requests and
local Docker/Playwright work are not provider-billed and are listed separately
from optional live verification.

| Provider | Operation | Calls | Tokens/units | Cost | Purpose | Reusable fixture? |
| --- | --- | ---: | ---: | ---: | --- | --- |
| System Data (local) | Job, postcode, Stripe and LLM fixture responses | many | local requests | $0.00 | Repeatable regression and promotional state | Yes; canonical synthetic fixtures |
| Live job providers | Current response-shape sampling | 0 | 0 | $0.00 | Optional provider realism | Not run |
| Live location providers | Location/route sampling | 0 | 0 | $0.00 | Optional location realism | Not run |
| OpenAI | Six-case CV/cover-letter quality sample | 0 | 0 | $0.00 | Grounding, latency, token and quality review | Outstanding |

**Exact paid validation spend recorded so far: $0.00.**

Zero here means no paid call was made; it does not mean a production operation
is free. The six required LLM samples remain an explicit coverage gap until a
bounded live run records model, call count, input/output tokens, latency and
calculated cost.

## Safety and reproducibility

- Live and paid modes remain disabled by default.
- No API key, token, request authorization header or applicant document is
  recorded in this report.
- All users and documents are fictional.
- A later paid run must add one row per provider/operation and retain aggregate
  token/unit evidence without committing credentials or raw personal content.
