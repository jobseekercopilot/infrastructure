# Job Seeker Copilot GitHub organisation migration plan

Status: **recommended future maintenance work; not authorised for execution**

## Decision summary

Job Seeker Copilot should move from the `jobseekercopilot` personal GitHub
account to a dedicated organisation. The proposed organisation slug is
`job-seeker-copilot`, subject to GitHub availability and partner approval at the
time of creation. A public API lookup returned no current account for that slug
on 28 August 2026, but that does not reserve or guarantee it.

No repository should be transferred until every production and package
dependency below has an owner, a rehearsed change, a rollback decision and a
recorded verification result. The current migration safety verdict is **NOT
SAFE as an immediate operation** because those prerequisites are not yet
proven.

## Why an organisation is the correct target

The current personal account has 32 JSC repositories and a personal Project. A
personal-account owner cannot give another person equivalent account ownership
or continuity. Repository-by-repository collaborator write access can cover many
routine development operations, but it does not provide a two-owner governance
model or repository settings administration across Projects, packages, billing,
policy and future teams.

A dedicated organisation provides:

- Bernard and Danny as organisation owners;
- team-based administration across the full repository fleet;
- continuity independent of one personal login;
- central repository/ruleset/security policy;
- clearer onboarding and offboarding for future developers;
- organisation Projects and reusable automation; and
- clearer separation of partner governance from protected production secrets.

## Target ownership and access

- **Bernard:** organisation Owner; repository admin; Product Development Project
  admin; protected-production capability subject to environment safeguards.
- **Danny:** organisation Owner; repository admin; Product Development Project
  admin; the same normal development and management capability as Bernard.
- **Automation identities:** GitHub Apps or OIDC roles with the smallest
  repository/environment permissions required. They are not human owner
  substitutes.

Both partners should use individual GitHub accounts with two-factor
authentication. Shared human credentials are not an acceptable partnership
model. Organisation ownership does not require exposing every production secret
to every workflow or unprotected branch.

## Known migration dependencies

The following owner/name coupling is already evidenced and must be treated as a
change surface, not assumed to redirect safely:

- 32 local repository remotes under `github.com/jobseekercopilot/...`;
- the personal Project at `https://github.com/users/jobseekercopilot/projects/1`;
- `infrastructure/config/services.json` owner, Project and repository catalogue;
- `config/workspace-lock.json` repository identities and revisions;
- the protected AWS build workflow's explicit repository list and GitHub App
  token materialisation;
- AWS OIDC trust defaults and immutable organisation/repository IDs in
  `aws/public-beta/bootstrap/state-and-oidc.yaml`;
- release manifest provenance and repository URL validation;
- contract locks and Maven package URLs under
  `https://maven.pkg.github.com/jobseekercopilot`;
- producer POM/workflow metadata for generated Java clients;
- GitHub Actions environments, secrets and variables;
- repository deploy keys, webhooks, GitHub Apps and collaborators;
- the public generated documentation repository, GitHub Pages and
  `docs.jobseekercopilot.com`;
- Landing/Amplify source-repository bindings and branch gates;
- local remotes, scripts, READMEs, badges, issue/PR links and documentation; and
- any package/image consumer that relies on the old owner rather than a verified
  redirect.

Production images use AWS ECR rather than GHCR in the audited infrastructure,
but GitHub Packages is used for private generated-client distribution. GitHub
redirects reduce some source-link disruption; they are not a substitute for
testing OIDC subjects, packages, Pages, Apps, webhooks or external deployment
bindings.

## Migration stages

### 1. Establish governance without moving runtime dependencies

1. Agree the organisation name, billing owner and recovery contacts.
2. Create the organisation with Bernard and Danny as Owners.
3. Require 2FA and record partner account-recovery procedures.
4. Create teams for Partners, Maintainers and future Contributors, while keeping
   both partners at Owner level.
5. Create an organisation Product Development Project only as a migration target;
   do not discard or recreate personal-Project history.
6. Inventory repository IDs, visibilities, default branches, rulesets, Actions,
   packages, environments, variables, secret **names**, deploy keys, Apps,
   webhooks, Pages and collaborators through an authenticated read-only export.

Exit criterion: two-owner governance exists, but production continues to use the
unchanged personal account.

### 2. Build a dependency and rollback matrix

For every repository record:

- repository ID, old/new URL and visibility;
- redirect behavior and any same-name collision;
- default branch, protections and rulesets;
- Actions workflow and reusable-workflow dependencies;
- environments, reviewers, variables and secret names;
- packages and consuming repositories;
- AWS OIDC subjects plus immutable repository/owner IDs;
- Amplify, Pages, deploy-key, webhook and GitHub App bindings;
- Project items and issue hierarchy;
- local remotes and automation references;
- migration owner, verification command and rollback/forward-fix decision.

Repository transfer rollback is not guaranteed to be a simple transfer back:
names, package ownership and external integrations may already have changed.
Define an explicit point of no return for each pilot.

### 3. Prove non-production behavior

1. Use a non-production, non-Pages, non-package-publishing pilot repository.
2. Export all settings before transfer.
3. Transfer the pilot and confirm Git redirects, PRs, issues, branch protection,
   Actions, Apps, deploy keys and collaborators.
4. Run CI without AWS credentials or production environment access.
5. update and test local remotes.
6. Validate organisation Project linking and both partners' CRUD/admin access.
7. Retain evidence and wait through a defined observation period.

Do not use `infrastructure`, the Client, Landing, public docs, package producers,
or a production integration as the first pilot.

### 4. Migrate low-coupling repositories in waves

Transfer only reviewed repositories whose dependency rows are complete. After
each wave:

- verify redirects and exact repository IDs;
- restore rulesets, environments, teams and Apps;
- run CI on a reviewed branch;
- verify issues, PRs, releases, tags and Project items;
- update local remotes and canonical documentation; and
- stop the wave if any unexpected external integration changes.

### 5. Migrate packages and production-coupled repositories

Treat the following as separate controlled changes:

- GitHub Packages coordinates/access and every consumer credential;
- AWS OIDC trust and environment protection;
- Infrastructure immutable-build repository allowlists/provenance;
- Amplify repository/branch association;
- Pages source, custom-domain ownership and HTTPS;
- GitHub Apps, webhooks and deploy keys; and
- protected secrets and variables.

Prefer dual-trust/overlap windows where the provider supports them. Never delete
the old working credential or trust path until the replacement is proven and a
rollback window has closed. Secret values must not enter migration evidence.

### 6. Move Project history

Preserve issue-backed work in place through repository transfer. For draft items,
fields, workflows and views:

1. export the personal Project schema, options, views, workflows and item field
   values;
2. create the organisation Project with equivalent minimal fields;
3. add the existing transferred issues rather than recreating them;
4. recreate draft items only when no repository-backed issue exists;
5. validate child relationships, comments/links, closed work and v1.1 Release
   classification; and
6. keep the old Project read-only until both partners sign off the new one.

### 7. Post-migration verification

Verify all of the following before closing the maintenance task:

- Bernard and Danny are organisation Owners and Project administrators;
- repository count, IDs, visibility and archive state match the plan;
- default branches, rulesets and required checks match their exports;
- issues, PRs, milestones, releases and tags are intact;
- Actions run with least privilege;
- environment reviewers and administrator-bypass settings remain protected;
- package publication and clean consumer resolution pass;
- AWS OIDC rejects old/unapproved subjects and accepts only reviewed new ones;
- Amplify uses the intended repository/branch without deploying merely for a
  source-control test;
- Pages builds only reviewed public output;
- `https://docs.jobseekercopilot.com` resolves and serves the expected content;
- GitHub Apps, deploy keys and webhooks deliver only to expected endpoints;
- local clean clones, remotes and release scripts use the canonical new owner;
- no runtime image, DNS record or production task changed as a side effect; and
- monitoring shows no repository-integration failure during the observation
  window.

## Rollback and containment

- Stop at the first failed wave; do not continue transfers to make the inventory
  look consistent.
- Preserve the old account, redirects, credentials and trust relationships until
  their replacements are verified.
- Restore settings from the per-repository export when metadata differs.
- Prefer a forward fix for package/OIDC/Pages bindings once transfer-back safety
  is uncertain.
- If production impact is possible, darkening or redeploying production is not a
  GitHub-migration test strategy. Escalate to the normal incident/change process.

## Approval required before execution

Execution requires a separate maintenance issue with:

- the final organisation slug and both partner usernames;
- authenticated current-state export;
- complete dependency matrix;
- pilot result;
- per-wave repository list;
- provider-specific rollback decisions;
- production change window only where actually needed; and
- explicit partner approval.
