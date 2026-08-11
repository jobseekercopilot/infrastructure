# Beta readiness

Reviewed: **11 August 2026**

| Area | Status | Why |
| --- | --- | --- |
| Product regression | Validated for intended beta path | 32/32 scenarios and 244/244 steps pass, including all seven personas and the authoritative 26-step journey. |
| Real-world profiles | Validated within documented boundary | Minimal through plausible 18-engagement very-rich profiles pass purpose-sized browser journeys; this is not a maximum transport claim. |
| CV upload | Validated beta scope | The supported product promise is application CV upload/manage/version/download. Automatic CV-to-profile import is not exposed or promised and is outside beta scope. |
| Documents | Validated focused flow | Upload, lineage and backend generation/approval have evidence; the rebuilt seven-scenario selection feature passes 65/65 steps. |
| Application tracking | Validated in fixture mode | Supported states and persisted mixed histories are covered. |
| Reporting | Validated in deterministic scope | Empty, small and rich-history source records reconcile to API totals, buckets and displayed values. |
| Provider integration | Bounded live validation | Reed, Adzuna, JSearch, NHS and apprenticeship paths were sampled live; bounded evidence does not prove provider reliability. |
| LLM generation | Validated with bounded limitations | Policy 2.24.0, deterministic suites and the live domain/gateway path cover grounding, rejection, repair, quarantine replay and approved downloads. The 17-call sample is not a reliability forecast. |
| Payments | Validated in fixture mode | Same-origin session-derived pricing/wallet routes return 200 for authenticated browser sessions and fail closed for invalid sessions. Live Stripe remains separately gated. |
| Accessibility | Automated regression validated | Both accessibility scenarios and 22 steps pass; this is not a claim of a complete manual accessibility audit. |
| Capacity | Validated to 25; latency-limited | 1/5/10/15/20/25 all completed. At 25, p95 reached 59.45 seconds, so 15 is the cautious operating point and no 50-session claim exists. |
| AWS deployment | Not yet validated | Candidate sizing is calculated from local evidence, not load-tested on AWS. |
| Security | Partially validated | Ownership, guarded fixtures and upload controls have evidence; no claim of complete security assurance. |
| Promotional showcase | Validated deterministic journey | The gated 26-step journey produced a 1920×1080, 204.4-second master and seven clips from one coherent fixture-backed timeline. |

## Remaining gates and limitations

1. Reproduce the workload on the selected AWS deployment shape before making a
   public capacity claim.
2. Run live Google and Stripe validation only when intentionally configured.
3. Enable the repository's public Pages deployment through its required
   GitHub administration/integration step; the strict local build already passes.
