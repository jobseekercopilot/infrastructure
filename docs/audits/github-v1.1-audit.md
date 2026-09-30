# GitHub v1.1 audit

Audit date: **28 August 2026**

Scope: Job Seeker Copilot only

Production changed: **NO**

This audit combines authenticated GitHub REST metadata, local repository and
workflow evidence, and prior Project documentation. Secret values were neither
requested nor printed. GitHub Project V2 GraphQL data is called out separately
because the account's GraphQL quota was exhausted during the first audit pass.

## Executive verdicts

### Current ownership

**Personal account**

`https://github.com/jobseekercopilot` reports GitHub account type `User`, not
`Organization`. Every discovered JSC repository is owned by that account.

### Repository migration safety

**NOT SAFE as an immediate operation**

Repository identities are coupled to AWS OIDC trust, protected release
workflows/environments, GitHub Packages, a GitHub App, an Amplify connection,
GitHub Pages and its custom domain, release provenance, contract pins and local
automation. GitHub App installation and live package inventories were not fully
observable with the current token. Transfers require a separate staged
maintenance plan.

### Partner access

**The required two-partner model is not currently evidenced.**

The only collaborator returned on all 32 repositories is the generic owner
account `jobseekercopilot`, with `admin`. No pending invitations and no distinct
Bernard or Danny account were returned. A personal account cannot grant two
people equivalent account ownership: a private personal repository can grant an
invited collaborator write access, not a second owner/admin role.

## Repository inventory

The audit discovered **32 active repositories**: 31 private and one public. No
repository is archived, disabled or a fork.

| Repository | Visibility | Default branch |
|---|---|---|
| `adzuna-gateway` | Private | `develop` |
| `application-tracker-service` | Private | `develop` |
| `apprenticeships-gateway` | Private | `develop` |
| `authentication-service` | Private | `develop` |
| `cv-cover-letter-service` | Private | `develop` |
| `document-export-service` | Private | `develop` |
| `document-generation-gateway` | Private | `develop` |
| `document-store-service` | Private | `develop` |
| `e2e` | Private | `develop` |
| `google-maps-gateway` | Private | `develop` |
| `infrastructure` | Private | `develop` |
| `job-finder-gateway` | Private | `develop` |
| `job-matching-service` | Private | `develop` |
| `job-seeker-copilot-client` | Private | `develop` |
| `job-seeker-copilot-docs` | **Public** | `main` |
| `job-seeker-copilot-landing` | Private | `main` |
| `job-service` | Private | `develop` |
| `jsearch-gateway` | Private | `develop` |
| `llm-gateway` | Private | `develop` |
| `location-gateway` | Private | `develop` |
| `location-service` | Private | `develop` |
| `nhs-jobs-gateway` | Private | `develop` |
| `payment-gateway` | Private | `develop` |
| `payment-service` | Private | `develop` |
| `postcode-io-gateway` | Private | `develop` |
| `reed-gateway` | Private | `develop` |
| `reporting-gateway` | Private | `develop` |
| `reporting-service` | Private | `develop` |
| `stripe-gateway` | Private | `develop` |
| `system-data-service` | Private | `develop` |
| `user-management-gateway` | Private | `develop` |
| `user-profile-service` | Private | `develop` |

All local `origin` URLs are
`https://github.com/jobseekercopilot/<repository>.git`. Local `origin/HEAD`
matches the GitHub default except for `nhs-jobs-gateway`, whose local symbolic
remote HEAD still names `main` while GitHub names `develop`. This is a local
metadata discrepancy, not evidence that GitHub's default is wrong.

## Repository controls

### Branch protection and rulesets

- The public docs repository returned no repository rulesets and `main` was not
  protected.
- A representative private repository (`infrastructure`) returned GitHub's plan
  limitation: rulesets/branch protection require GitHub Pro or a public
  repository for this personal account.
- No effective private-fleet default-branch protection was therefore proven.

Private production repositories currently depend on process, protected Actions
environments and workflow guards rather than enforced branch rules. This is a
material reason to evaluate an organisation plan that supports the required
controls.

### Actions

- 41 active workflows exist across the 32 repositories.
- Actions is enabled everywhere and allowed actions is `all`.
- Default workflow token permission is `read` everywhere.
- Workflows cannot approve pull-request reviews.
- 31 repositories' most recent workflow run passed at audit time.
- The most recent `document-generation-gateway` run failed on PR workflow run
  `33019509686`; this audit did not alter or rerun it.
- Infrastructure's most recent run was a successful, manually dispatched
  protected production release from `main` on 27 August.
- The latest docs Pages run passed on 28 August.

Special Infrastructure workflows cover immutable build, protected release,
provider-secret seeding, isolated restore and semantic verification, CI and
Pages. Three producer repositories publish Maven clients:
`cv-cover-letter-service`, `document-export-service` and
`user-profile-service`.

### Issues, PRs and hierarchy

At the audit snapshot:

- open issues: **328**;
- closed issues: **302**;
- open PRs: **7**; and
- closed PRs: **941**.

The existing hierarchy uses title conventions/labels and native sub-issues,
including cross-repository children. GitHub Issue Types are not configured; the
REST issue `type` was `null`. Existing conventions include `[Epic]`, `[Feature]`,
`[Story]`, `[Backlog]`, native blocked-by links and labels such as `epic`,
`enhancement`, `bug`, `P0`–`P3`, `beta-blocker`, `quick-win`, `frontend`,
`backend`, `security`, `privacy`, `testing` and `devops`.

`document-generation-gateway#134`, `[Epic] Public Beta User Feedback and Product
Learning`, already has five native children across four repositories. The
standing improvement parent exists as
`document-generation-gateway#2`, `[Epic] Product Backlog and Continuous
Improvements`.

No milestone or GitHub Release exists. There are 46 tags across nine
repositories, all archive/migration tags rather than semantic v1.0/v1.1 release
tags. v1.1 should therefore be represented in the existing Project's `Release`
classification; it must not be introduced as another Epic.

Open PRs at the snapshot were:

- `document-generation-gateway#133` — OpenSSL CVE patch;
- `postcode-io-gateway#26` — postcode coordinates (draft);
- `infrastructure#101` — portfolio documentation (draft);
- `job-service#38` — matching failure degradation (draft);
- `location-service#7` — outcode autocomplete (draft);
- `job-matching-service#20` — provider timestamp offsets (draft); and
- `adzuna-gateway#12` — repository documentation.

They remain untouched and are not automatically part of v1.1.

## Existing Product Project

Strong repository evidence identifies:

- title: `Job Seeker Copilot`;
- owner: personal account `jobseekercopilot`;
- number: `1`; and
- URL: `https://github.com/users/jobseekercopilot/projects/1`.

The local Project tool expects these existing `Status` options:

- Ideas
- Backlog
- Ready
- In Progress
- Review
- Bugs
- Done

It expects Priority values `Critical`, `High`, `Medium`, `Low`. Prior audit
evidence also records a `Dependencies` field. This structure predates the v1.1
request and must be migrated deliberately; `Bugs` should not silently retain
its historical dual use as a workflow state when Bug is a work type/view.

The first live Project query could not read current fields, items, views,
collaborators or built-in workflows because GitHub reported an exhausted
GraphQL quota with reset time 17:43:22 Europe/London on the audit date. No
Project mutation was attempted before a fresh read. A later validation section
must record any changes made after quota recovery.

### Second-pass live Project validation

After quota recovery on 28 August 2026, an authenticated GraphQL read showed the
private, open Project contained **609 items**, 20 fields, seven views and six
built-in workflows before v1.1 classification. No item, field, option or view was
deleted. The requested safe metadata changes then:

- renamed the existing Project to `Job Seeker Copilot — Product Development`;
- replaced its user-management-specific short description and added a concise
  operating readme;
- retained all 609 historical items and all seven historical views;
- added `Release`, `Area` and `Source` as the only new fields;
- added eight focused views; and
- added/classified the approved v1.1 issues and evidenced improvement items.

The live Project already had the requested modern Status and Priority options;
the local tool evidence above was stale. No risky option migration was needed.
The validated fields/options are:

- `Status`: Backlog, Ready, In Progress, In Review, Blocked, Done, Post-beta;
- `Priority`: P0, P1, P2, P3;
- `Type`: existing Bug, Security, Hardening, Testing, Documentation, Build,
  Architecture, Operational, Provider Compliance, Epic, AI Safety, Privacy,
  Cost Control, Feature, Story, Research and Task;
- `Release`: Live / v1.0, v1.1, Post-v1.1, Future;
- `Area`: Frontend, Authentication, User Profile, Jobs, Matching, Application
  Tracker, Documents, CV / Cover Letter, Payments, Reporting, Location,
  Infrastructure, Documentation, Public Testing and Promotion;
- `Source`: Internal, Public Tester, Danny, Bernard, Production, Automated Test
  and Technical Debt; and
- existing `Workstream`, `Service`, `Beta blocker`, `Effort`, `Dependencies`
  plus GitHub built-in identity, relationship and date fields.

Start/target date fields were not invented because no evidence-backed v1.1 dates
were approved. The Roadmap still gives a release-focused planning surface; dates
can be added when the partners approve a schedule.

| View | Layout | Filter | URL |
|---|---|---|---|
| v1.1 Roadmap | Roadmap | `release:"v1.1"` | `https://github.com/users/jobseekercopilot/projects/1/views/15` |
| v1.1 Board | Board, vertically grouped by Status | `release:"v1.1"` | `https://github.com/users/jobseekercopilot/projects/1/views/8` |
| User Feedback | Table | `source:"Public Tester"` | `https://github.com/users/jobseekercopilot/projects/1/views/9` |
| Bugs | Table | `type:Bug -status:Done` | `https://github.com/users/jobseekercopilot/projects/1/views/10` |
| Promotion | Table | `area:Promotion` | `https://github.com/users/jobseekercopilot/projects/1/views/11` |
| Infrastructure | Table | `area:Infrastructure` | `https://github.com/users/jobseekercopilot/projects/1/views/12` |
| Release Readiness | Table | `release:"v1.1" -status:Done` | `https://github.com/users/jobseekercopilot/projects/1/views/13` |
| Full Product Backlog | Table | `-release:"v1.1"` | `https://github.com/users/jobseekercopilot/projects/1/views/14` |

The v1.1 Board exposes Title, Status, Release, Type, Priority, Area, Source,
parent/sub-issue progress, assignees and linked PRs. GitHub automatically made
Status its vertical board grouping. The current GraphQL view API can set layout,
filter and visible fields but not table sorting/grouping, so the Bugs view was
not falsely claimed to have an API-configured priority sort; partners can set
that presentation preference in the UI after individual access is verified.

Post-change query counts proved that the filters resolve to exactly 17 v1.1
items, seven public-tester-source items, six Promotion items, four Infrastructure
items and 17 non-Done release-readiness items. The 17 v1.1 items are the four
Features and 13 native child issues documented in the release plan. No unrelated
legacy item was assigned `Release = v1.1`; similarly named older client and
authentication issues were deliberately left unclassified.

The Project now contains 624 items. Seven of the 17 v1.1 items had already been
auto-added before the 609-item baseline; the final increase is the other ten
v1.1 items plus five evidenced improvement items. The original 609-item history
remains intact. The continuous-improvement parent currently has GitHub's maximum
100 native sub-issues, so newer improvement issues retain a textual parent link
and full Project classification rather than removing an existing child or
creating a duplicate Epic.

### Project automation

The live Project has six built-in workflows. Only `Auto-add sub-issues to
project` is enabled. `Item closed`, `Pull request merged`, `Auto-close issue`,
`Pull request linked to issue` and `Item added to project` are disabled. The
enabled workflow preserved native cross-repository children during this task.

GitHub's exposed Project API does not configure the desired conditional field
defaults or view sorting. No repository workflow was added that would require a
new PAT. New issues therefore use the documented manual checklist: add the item,
set Backlog, and assign Release/Type/Priority/Area/Source. Closing/DONE remains a
deliberate evidence-based action. Project/issue automation has no AWS, Amplify,
Pages or production deployment credential and cannot deploy production.

### Project access result

The authenticated generic owner returned `viewerCanUpdate: true`. GitHub's
Project V2 GraphQL object exposed no collaborator read connection, and the
current-version personal-Project collaborator REST path returned 404 with the
available token. The update mutation accepts a complete replacement list, so it
was not used blindly. Repository reads still found no distinct Danny account or
invitation. Because Danny's exact username was not supplied, no access grant or
CRUD test was possible; current partner-level access remains unverified.

## Pages and documentation

The public documentation site is live and healthy:

- repository: `jobseekercopilot/job-seeker-copilot-docs`;
- URL: `https://docs.jobseekercopilot.com/`;
- CNAME: `docs.jobseekercopilot.com`;
- source: `main`, repository root;
- build type: legacy;
- status: built;
- HTTPS enforced: true;
- latest built commit at audit: `bed959b93f2b231138a389d6d259baaa65aa7e5a`;
- latest build completed successfully at `2026-08-28T14:16:38Z`.

The public docs repository has Issues disabled. Infrastructure contains the
reviewed source/publication workflow. This task did not alter Pages, the CNAME,
DNS or the generated repository.

## Environments and production controls

Only Infrastructure and the public docs repository returned environments.

Infrastructure environments:

- `github-pages`
- `production-aws`
- `production-aws-plan`
- `production-aws-restore`
- `production-aws-restore-cleanup`
- `production-aws-restore-observe`
- `production-build`

The six production environments use custom branch policies allowing `main`.
The returned protection metadata contained a branch policy only; it did not
return required reviewers or wait timers. Repository evidence includes a
fail-closed environment-protection verifier, but the API result does not prove
the desired two-person reviewer model is configured.

The docs repository has `github-pages`, with custom branch policy entries for
`main` and `gh-pages`.

### Secret and variable names

Values were not accessed or printed.

Repository secret:

- `document-generation-gateway`: `JSC_PACKAGE_READ_TOKEN`

No repository-level Actions variables were found.

Environment inputs by name:

| Environment | Secrets | Variables |
|---|---|---|
| `production-aws` | `LAUNCH_APPROVALS_B64`, `PUBLIC_BETA_TFVARS_B64` | `AWS_ACCOUNT_ID`, `AWS_APPLY_ROLE_ARN`, `BACKUP_PERMISSIONS_BOUNDARY_ARN`, `BACKUP_RESTORE_PERMISSIONS_BOUNDARY_ARN`, `RDS_MONITORING_PERMISSIONS_BOUNDARY_ARN`, `RESTORE_SEMANTIC_BROKER_PERMISSIONS_BOUNDARY_ARN`, `TF_STATE_BUCKET`, `TF_STATE_KMS_KEY_ARN`, `WORKLOAD_PERMISSIONS_BOUNDARY_ARN` |
| `production-aws-plan` | `LAUNCH_APPROVALS_B64`, `PUBLIC_BETA_TFVARS_B64` | `AWS_ACCOUNT_ID`, `AWS_PLAN_ROLE_ARN`, `TF_STATE_BUCKET`, `TF_STATE_KMS_KEY_ARN` |
| `production-aws-restore` | None returned | `AWS_ACCOUNT_ID`, `AWS_BACKUP_RESTORE_ROLE_ARN`, `AWS_DATA_KMS_KEY_ARN`, `AWS_RESTORE_DRILL_ROLE_ARN`, `AWS_RESTORE_SEMANTIC_START_ROLE_ARN` |
| `production-aws-restore-cleanup` | None returned | `AWS_ACCOUNT_ID`, `AWS_BACKUP_RESTORE_ROLE_ARN`, `AWS_RESTORE_CLEANUP_ROLE_ARN` |
| `production-aws-restore-observe` | None returned | `AWS_ACCOUNT_ID`, `AWS_DATA_KMS_KEY_ARN`, `AWS_RESTORE_SEMANTIC_OBSERVE_ROLE_ARN` |
| `production-build` | `LANDING_RUNTIME_ENV_B64`, `LAUNCH_APPROVALS_B64`, `RELEASE_READER_APP_PRIVATE_KEY` | `AWS_ACCOUNT_ID`, `AWS_BUILD_ROLE_ARN`, `POSTGRES_IMAGE_BY_DIGEST`, `RDS_CA_BUNDLE_SHA256`, `RDS_CA_BUNDLE_URL`, `RELEASE_READER_APP_ID` |

No secrets or variables were returned for either `github-pages` environment.

## Webhooks, deploy keys, Apps and packages

- One active push webhook exists on `job-seeker-copilot-landing`. Its endpoint
  and configuration were deliberately not printed. Local operational evidence
  associates the repository with Amplify app `d3gd9ezfa3aujn`; the webhook alone
  does not prove its destination.
- No deploy keys were found.
- GitHub App installation inventory was not observable with the current token.
  Environment names prove a Release Reader App dependency through
  `RELEASE_READER_APP_ID` and `RELEASE_READER_APP_PRIVATE_KEY`.
- The current token lacks `read:packages`, so live Maven/GHCR inventory was not
  available.
- Local release evidence confirms private Maven Packages under
  `https://maven.pkg.github.com/jobseekercopilot` and three active publisher
  workflows. `JSC_PACKAGE_READ_TOKEN` corroborates cross-repository consumption.
- Live GHCR package existence/visibility was not proven. Production runtime
  images in the audited AWS design use ECR.

## Repository presentation and labels

Authenticated REST validation after the safe metadata pass returned non-empty,
specific descriptions and at least four relevant topics for all 32 repositories.
Twelve missing or stale descriptions were corrected: Application Tracker,
Payment Gateway, Payment Service, Reporting Gateway, Reporting Service, Stripe
Gateway, CV/Cover Letter Service, Document Export, Document Generation Gateway,
Document Store, LLM Gateway and Landing. All repositories received concise
technology/component topics, including `job-seeker-copilot`; names, visibility,
default branches, integrations and runtime settings were unchanged.

Only the public docs repository has a GitHub homepage value, correctly set to
`https://docs.jobseekercopilot.com/`. Homepage fields on private services were
deliberately left untouched rather than assuming that a repository should link
to a public runtime. Existing README/header/architecture content was preserved.
The workspace check found canonical docs links absent from five READMEs
(`adzuna-gateway`, `apprenticeships-gateway`, the generated docs repository,
Landing and NHS Jobs Gateway), SECURITY guidance absent in three, and
CONTRIBUTING guidance absent in four. Those cross-fleet content changes were not
mixed into the three v1.1 implementation branches.

Before this work no repository supplied central issue forms or a pull-request
template. Infrastructure now contains reviewed Bug, Feature, Story, Research,
Promotion and evidence-complete backlog forms plus a PR template. They are the
central work-intake forms for this release; a personal account does not make
them inherit automatically across the other 31 repositories. Fleet-wide
community-health inheritance after organisation migration is tracked in
Infrastructure #318. The missing actionable confidential public security route
is tracked in Infrastructure #319; the template's existing private SECURITY
link must not be represented as usable by an unauthenticated tester.

The Infrastructure label audit confirmed `bug`, `enhancement`, P0–P3,
`beta-blocker`, `privacy`, `security`, `testing`, `documentation`, `technical-debt`
and `quick-win`; this task added `public-tester`, `feedback` and `promotion` for
the fixed intake repository. Client and E2E retain bug/P0–P3 labels; Landing has
a smaller legacy label set. Feature/Story/Research and cross-repository routing
use native parent links plus Project `Type`, not a new fleet of duplicate labels.
Issue-form Source/Severity/Release answers are body text: triage must map reported
severity Critical/High/Medium/Low to Project Priority P0/P1/P2/P3 and set Project
fields explicitly.

## Production dependencies on GitHub structure

The current owner/repository names participate in the live delivery boundary:

1. AWS OIDC trust subjects include the owner, repository and protected
   environment.
2. Production Actions environments and role variables belong to the current
   `infrastructure` repository.
3. Immutable build workflows enumerate the `jobseekercopilot` owner and explicit
   repository fleet.
4. Release manifests, schemas, workspace locks and contract pins record exact
   owner/repository provenance.
5. Maven package coordinates and consumer authentication use the current owner.
6. A Release Reader GitHub App has unknown installation/repository selection.
7. Amplify is connected to the current Landing repository and an active push
   webhook.
8. GitHub Pages serves the live docs custom domain from the current public
   repository.
9. The Product Project is user-owned and will not become an organisation Project
   merely because repositories transfer.
10. Every local remote plus many issue, PR, source, clone and documentation links
    embed the current owner.

Representative files include:

- `config/services.json`
- `config/workspace-lock.json`
- `config/contracts-lock.json`
- `config/release-evidence.schema.json`
- `.github/workflows/aws-public-beta-build.yml`
- `scripts/aws/build_release_images.sh`
- `scripts/aws/build_landing_artifact.py`
- `aws/public-beta/config/image-manifest.json`
- `aws/public-beta/bootstrap/state-and-oidc.yaml`
- `aws/public-beta/versions.tf`
- producer/consumer POMs and contract source/pin files across the fleet.

This is why repository transfer is not a safe administrative tidy-up.

## Collaboration limitations

### Bernard

The generic `jobseekercopilot` owner has full personal-account and repository
admin capability. The audit cannot attribute that shared/generic account safely
to Bernard or prove that Bernard has a separate individual collaborator account.

### Danny

No distinct Danny collaborator or pending invitation was found on any
repository. The Project owner can update it, but GitHub exposed no readable
personal-Project collaborator list through the available GraphQL/REST boundary.
There is therefore no evidence that Danny can currently create, edit or manage
repository/Project work.

### Required correction

Short term, add each partner's individual account with the broadest safe
repository and Project administration available, without sharing human
credentials or weakening protected secrets. The final GitHub username must be
confirmed before an invitation is sent.

Long term, create a dedicated Job Seeker Copilot organisation and make Bernard
and Danny organisation Owners. Use teams for the repository fleet and retain
protected environment, least-privilege workflow and production-secret controls.
The staged plan is in
[`docs/plans/jsc-github-organisation-migration.md`](../plans/jsc-github-organisation-migration.md).

## Audit limitations and next verification

- Obtain the two partners' individual GitHub usernames before invitations.
- Export and preserve the Project collaborator list through an owner/UI session
  before using the complete-list collaborator mutation.
- Audit GitHub App installations with an authorised owner session.
- Audit Maven/GHCR packages with `read:packages` without printing credentials.
- Query AWS and Amplify control planes read-only before any migration task.
- Export exact branch/environment settings before any organisation pilot.

Until those gaps close, migration remains **NOT SAFE** and partner access remains
**not proven**.

## Backlog discipline result

- Created: Infrastructure #317 (dark defaults versus current AWS status), #318
  (fleet-wide community-health templates), #319 (confidential public security
  reporting), Landing #74 (feedback deletion/recovery/issue reconciliation),
  and Landing #75 (Amplify runbook versus main-only publication gate).
- Updated instead of duplicating: Client #51 with the measured five-kilobyte
  v1.1 shell-budget evidence; existing Infrastructure #54 already covers the
  worktree-path full-suite failures.
- Quick wins: #317, Landing #75 and existing #54 are evidence-backed S/low-risk
  candidates; none was implemented inside this v1.1 work.
- The 100-child native limit on the existing improvement Epic prevented new
  native links; every new item links it textually and is classified in the
  Product Project.
- No unrelated backlog code was implemented and no non-blocking discovery was
  allowed to delay the approved vertical slices.
