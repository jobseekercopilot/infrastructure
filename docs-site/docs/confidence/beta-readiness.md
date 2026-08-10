# Beta readiness

Reviewed: **10 August 2026**

| Area | Status | Why |
| --- | --- | --- |
| Product regression | Partially validated | Core deterministic journeys pass; full seven-persona browser execution is outstanding. |
| Real-world profiles | Partially validated | Canonical personas and profile contract coverage exist; stress UI/prompt measurements remain incomplete. |
| CV upload | Partially validated | Application PDF/DOCX upload and adverse shapes are covered; CV-to-profile extraction is not confirmed. |
| Documents | Validated in fixture mode | Generated/uploaded lineage, download safety and application references have coverage. |
| Application tracking | Validated in fixture mode | Supported states and persisted mixed histories are covered. |
| Reporting | Partially validated | Empty and populated paths exist; broader persona reconciliation is outstanding. |
| Provider integration | Partially validated | Deterministic providers and failure modes are covered; current live shape sampling is optional/outstanding. |
| LLM generation | Partially validated | Grounded fixture protection exists; six required paid quality samples are outstanding. |
| Payments | Significant defect | Pricing/wallet routes produced four application 404s per measured session. |
| Accessibility | Partially validated | Automated checks exist; the complete real-world persona UI set is not audited. |
| Capacity | Blocked above 10 active sessions | 10 succeeded; 25 failed at the synchronous job-details path. |
| AWS deployment | Not yet validated | Candidate sizing is calculated from local evidence, not load-tested on AWS. |
| Security | Partially validated | Ownership, guarded fixtures and upload controls have evidence; no claim of complete security assurance. |

## Current blockers and gates

1. Resolve the recurring pricing/wallet 404s.
2. Trace and correct the 25-session job-details latency boundary, then rerun
   intermediate 15/20-session points.
3. Complete representative paid LLM grounding/latency/cost sampling.
4. Establish the actual CV-to-profile import capability or keep it explicitly
   out of product and promotional claims.
5. Reproduce the workload on the selected AWS deployment shape before making a
   public capacity claim.
