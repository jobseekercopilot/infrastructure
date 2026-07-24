# ADR 0002: Versioned contract and client publication

Status: Accepted for the User Profile pilot

Date: 2026-07-24

## Context

Several consumers historically built generated Java clients in a shared local
workspace and copied JARs into service `libs` directories. A clean clone could
therefore compile only after an unversioned, machine-local setup step. Exporting
contracts from running services also made the runtime environment, rather than
the producer repository, the apparent source of truth.

`jobseekercopilot` is a personal GitHub account. The design cannot depend on
organisation-only sharing of private reusable workflows or organisation
secrets.

## Decision

The producer repository owns its reviewed OpenAPI source and publishes each
generated client. Infrastructure owns the release conventions and compatible
fleet lock, but never republishes or silently edits another service's contract.

The initial Java convention is:

- private Maven packages in GitHub Packages;
- group `com.jobseekercopilot.clients`;
- artifact `<producer-service>-client`;
- version `<contract-semver>-rev.<first-12-characters-of-contract-source-sha>`;
- full producer revision and contract SHA-256 retained in
  `config/contracts-lock.json`;
- OpenAPI Generator `7.5.0`, Java `resttemplate`, with generation timestamps
  disabled;
- generated source and binaries remain disposable build output;
- producer-local workflows use `GITHUB_TOKEN` with only `contents: read` and
  `packages: write`;
- consumer workflows use `packages: read` and must be explicitly authorised
  for the package.

The version identifies contract bytes, not merely the workflow commit. A
release must fail when the file at the locked source revision does not match
the release checkout and recorded SHA-256.

The User Profile client is the first pilot. Its repository-local workflow is a
deliberate personal-account compatibility choice, not a precedent for copying
uncontrolled configuration: the POM metadata, version scheme and lock
validator remain governed here.

## Publication gates

Before a package is published, its producer must:

1. verify the producer-specific contract policy and checksum;
2. prove that the recorded revision contains the same contract bytes;
3. run a breaking-change check against the previous published contract, except
   for the explicitly recorded initial release;
4. generate twice with the pinned generator and compare canonical generated
   source manifests;
5. compile and test the client from a clean Maven repository;
6. reject a coordinate that already exists with different bytes;
7. publish from a protected reviewed revision.

A consumer may migrate from generated source or `systemPath` only after a
fresh, authorised environment resolves the immutable package and its normal
build and container gates pass.

## Consequences

Contract provenance and package versions become reviewable across repositories,
and a consumer no longer needs sibling checkouts or copied binaries. GitHub
package access must be configured explicitly for each private consumer. The
pilot does not by itself complete the TypeScript/npm convention, migrate every
producer, or remove the legacy workspace scripts; those remain within INFRA-07
and DOCGEN-03.

Rollback pins the prior immutable package version and matching contract lock.
Published versions are never replaced.
