# Infrastructure architecture

## Decision

Infrastructure is a private workspace-orchestration repository. Every
application component retains its own Git repository and history. No service is
embedded as a submodule or committed source subtree.

The repository catalogue is `config/services.json`. The bootstrap command
clones missing repositories beside Infrastructure. Compose contexts resolve
from `infrastructure/` to `../service-name`.

## Ownership

Infrastructure owns:

- Compose topology and local profile overlays;
- safe environment templates and secret-handling guidance;
- cross-repository bootstrap, diagnostics, fixture, locked-client build, and
  stack scripts;
- shared Maven build configuration until it is published as a versioned
  package;
- operational and clean-room full-stack evidence.

Service repositories own source, Dockerfiles, tests, API contracts,
producer-owned client modules and service-specific runbooks. Infrastructure
does not own service source, credentials, mutable data, generated source,
client JARs or service build output.

## Target delivery model

Development builds service images from the sibling source layout. Release
profiles should consume digest-pinned images from the account registry.
Each service publishes a versioned API contract; consumers use versioned
generated-client packages. Infrastructure pins the compatible repository,
contract, client package, and eventually image set. Local builds reconstruct
the locked packages from the recorded producer Git revisions into the
workspace-local cache. Contract and Java package pins are tracked in
`config/contracts-lock.json`; image pins remain INFRA-05 work.

See [ADR 0003](adr/0003-reproducible-sibling-workspace.md) for boundaries,
exceptions and migration rules.
