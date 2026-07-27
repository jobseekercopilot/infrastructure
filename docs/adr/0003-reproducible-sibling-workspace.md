# ADR 0003: Reproducible sibling-repository workspace

Status: Accepted

Date: 2026-07-27

## Decision

Infrastructure is the sole workspace orchestrator. All application repositories
are siblings of `infrastructure/`. `config/services.json` is the authoritative
inventory and topology; `config/workspace-lock.json` supplies exact repository
revisions; `config/contracts-lock.json` supplies exact contract/client
provenance.

Infrastructure owns catalogue/lock policy, Compose topology, fixture profiles,
safe environment generation, workspace lifecycle commands and cross-service
readiness evidence.

Each service repository owns its application source, API contract, generated
client module, Dockerfile, unit/integration tests and service-specific
documentation. Infrastructure must not contain service source, copied client
JARs, mutable application data, credentials or service build output.

Workspace updates are explicit, clean-checkout-only fast-forwards. A catalogue
or lock change requires review. Ports and health endpoints are assigned in the
catalogue and validated against the rendered Compose model.

## Versioning

The workspace lock pins the tested repository fleet. The contract lock pins
contract bytes, semantic version, generator, Maven coordinate and the Git
revision containing the producer-owned build module. Local builds reconstruct
those coordinates from Git into `<workspace>/.cache/m2`; publication may use
GitHub Packages under ADR 0002.

## Bounded exceptions

| Exception | Owner | Expiry condition | Migration |
| --- | --- | --- | --- |
| Reed and JSearch Compose builds stage their current-workspace JARs into disposable cache contexts and use Infrastructure-owned runtime Dockerfiles because their Docker build stages omit `docs/CREDENTIAL_OPERATIONS.md`, which their tests read. | Infrastructure | Both repository Dockerfiles copy their test inputs and the fixed revisions enter the workspace lock. | Verify each service-owned image build, restore its repository context and `dockerfile: Dockerfile`, then remove both runtime Dockerfiles and staging entries. |
| Document Generation consumes historical 2.x client contracts while producers are now 3.x. | Document Generation + Infrastructure | Gateway is migrated and tested against current producer contracts. | Update gateway code, consumer versions and contract lock in one reviewed vertical change. |
| Its local container stages the JAR produced by `build-all.sh` into a disposable cache context and uses an Infrastructure-owned runtime Dockerfile because the repository Dockerfile requires a package token. | Infrastructure | The gateway Dockerfile can reconstruct pinned clients from source or consume an approved release package credential. | Move the source-client build into the service-owned Docker build, then remove the runtime Dockerfile and staging entry. |
| Release profiles do not yet use digest-pinned GHCR images. | INFRA-05 owner | INFRA-05 is accepted. | Replace source build definitions in release-only profiles; retain source builds for development. |

Exceptions do not relax fixture isolation, secret policy, dirty-worktree
protection or the clean-room acceptance test.

## Consequences

A developer manually clones only Infrastructure and can reproduce the locked
fleet without legacy paths, copied binaries or a populated user Maven cache.
Service histories remain independent. Coordinated contract upgrades require an
explicit lock update instead of an implicit “latest” dependency.
