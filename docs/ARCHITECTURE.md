# Infrastructure architecture

## Decision

Infrastructure is a private workspace-orchestration repository. Every
application component retains its own Git repository and history. No service is
embedded as a submodule or committed source subtree.

The repository catalog is `config/services.json`. The bootstrap command clones
missing repositories beneath the Infrastructure checkout, where they are
ignored by Infrastructure Git. Existing Compose relative build contexts
therefore remain usable.

## Ownership

Infrastructure owns:

- Compose topology and local profile overlays;
- safe environment templates and secret-handling guidance;
- cross-repository bootstrap, diagnostics, fixture, client, and stack scripts;
- shared Maven build configuration until it is published as a versioned
  package;
- operational and clean-room full-stack evidence.

Service repositories own their source, Dockerfile, tests, API contract, and
service-specific runbook. Generated clients, service JARs, exported contracts,
credentials, test data, and service checkout contents are not Infrastructure
source.

## Target delivery model

Development may build service images from the cloned source layout. Release
profiles should consume digest-pinned images from the account registry.
Each service publishes a versioned API contract; consumers use versioned
generated-client packages. Infrastructure pins the compatible repository,
contract, client package, and eventually image set. Contract and Java package
pins are tracked in `config/contracts-lock.json`; image pins remain future
INFRA-02 work.
