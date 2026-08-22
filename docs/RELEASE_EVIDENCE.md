# Release evidence policy

INFRA-12 defines a fail-closed evidence contract for every artifact proposed
for a Job Seeker Copilot beta release. It does not publish, sign or deploy an
artifact by itself.

## Required chain

Each released artifact must be represented in one immutable manifest with:

- its owning team, private GitHub repository and full 40-character source
  revision;
- the named and versioned builder invocation;
- the artifact reference and SHA-256 digest;
- a checksummed CycloneDX or SPDX SBOM;
- current vulnerability and licence reports;
- checksummed SLSA-compatible provenance;
- signature verification evidence; and
- a non-empty, full-reachable-history secret scan.

The manifest format is documented by
[`config/release-evidence.schema.json`](../config/release-evidence.schema.json).
The enforcement values are deliberately separate in
[`config/release-policy.json`](../config/release-policy.json), so a policy
change is visible and reviewable.

## Fail-closed policy

Validation rejects:

- mutable source revisions or artifact references without a SHA-256 digest;
- missing, symlinked, path-escaping or checksum-mismatched evidence;
- evidence older than seven days or a vulnerability database older than 24
  hours;
- secret scans with a partial scope, zero commits or zero bytes;
- unapproved Critical or High vulnerabilities;
- AGPL-3.0 or SSPL-1.0 dependencies, and unknown/unasserted licences; and
- missing, expired, duplicate or overlong exceptions.

An exception must name the exact finding and include an owner, justification,
expiry and compensating control. Exceptions are limited to 30 days. Policy or
legal owners may shorten that window or reject an exception.

## Validate a candidate release

Place immutable reports in a dedicated directory and reference them with paths
relative to that directory:

```bash
python3 -m scripts.release.validate_evidence \
  release-evidence.json \
  --evidence-root ./release-evidence
```

This local command has no network dependency and does not invoke GitHub
Actions. It is suitable for a future isolated self-hosted runner after that
work is separately approved.

## Delivery boundary

This policy is the aggregation and validation layer. The following remain
separate dependencies:

- INFRA-05: produce immutable service images and registry digests;
- INFRA-06/07: reproducible build tools, contracts and packages;
- service security issues: generate SBOM, vulnerability and licence evidence;
- INFRA-09: production transport and operator controls; and
- INFRA-15: protected release approval, signing identity, attestations and
  deployment-time digest verification.

No manifest may be treated as release approval until those producers supply
real evidence and the protected release process validates it.
