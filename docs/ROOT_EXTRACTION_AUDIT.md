# Legacy root extraction audit

Date: 2026-07-23

## Source boundary

The standalone baseline was extracted from the legacy mixed root repository.
It includes four Compose definitions, operational scripts and configuration,
`gm`, `openapitools.json`, shared Maven build tools, safe environment examples,
and Infrastructure documentation.

It deliberately excludes service source, generated clients, exported contract
copies, JARs, build output, caches, IDE/Codex state, real environment files,
recordings, datasets, and the vendored Docker installation script.

The legacy root contained an obsolete personal GitHub remote and a large dirty
working tree. Its complete Git history and the selected pre-extraction sources
were backed up before migration. No root service work was committed as part of
this extraction.

## Verified risks carried into backlog

- The service fleet is not yet reproducibly buildable from clean clones because
  several POMs use excluded local generated-client JARs.
- Compose builds from mutable local source and uses unpinned third-party images.
- Environment/profile isolation, secret ownership, health semantics, supply
  chain evidence, and full clean-room E2E require validation.
- Shared Maven checks are currently fail-open and the parent artifact is not
  published. The extraction also separated engine and Maven-plugin version
  coordinates so the parent resolves from Maven Central.
- Cross-repository OpenAPI export/client scripts still assume local source
  checkouts and generated output directories.

This baseline establishes safe ownership and bootstrap mechanics; it does not
close those readiness findings.
