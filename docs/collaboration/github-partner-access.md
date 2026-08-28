# GitHub partner access

Status: **target partner model documented; Danny access not yet verified**

Bernard and Danny are Job Seeker Copilot partners. The intended model gives
both partners full normal management and development capability across the
repositories and Product Development Project; the Promotion workstream is
Danny's primary focus, not an access boundary. Protected production secrets,
environment approvals and billing-sensitive operations remain separate safety
controls.

The current repositories and Project are owned by the personal
`jobseekercopilot` account. The audit found only that generic owner with
repository admin access and found no distinct Danny collaborator or pending
invitation. GitHub usernames must be confirmed before access is granted, and a
personal private repository cannot make an invited collaborator a second
owner/repository admin. Consequently this page records the intended operating
model and exact working links; it does **not** claim that Danny's current CRUD
or administration access has passed verification.

## Partner Access Pack

- [JSC GitHub landing area](https://github.com/jobseekercopilot)
- [Product Development Project](https://github.com/users/jobseekercopilot/projects/1)
- [v1.1 Board](https://github.com/users/jobseekercopilot/projects/1/views/8)
- [v1.1 Roadmap](https://github.com/users/jobseekercopilot/projects/1/views/15)
- [User Feedback](https://github.com/users/jobseekercopilot/projects/1/views/9)
- [Bugs](https://github.com/users/jobseekercopilot/projects/1/views/10)
- [Infrastructure](https://github.com/users/jobseekercopilot/projects/1/views/12)
- [Promotion](https://github.com/users/jobseekercopilot/projects/1/views/11)
- [Promotion & Public Testing — Danny Feature](https://github.com/jobseekercopilot/infrastructure/issues/306)
- [Live product](https://app.jobseekercopilot.com/)
- [Public product website](https://www.jobseekercopilot.com/)
- [Public documentation](https://docs.jobseekercopilot.com/)

Additional operating views:

- [Release Readiness](https://github.com/users/jobseekercopilot/projects/1/views/13)
- [Full Product Backlog](https://github.com/users/jobseekercopilot/projects/1/views/14)

## Project conventions

`v1.1` is the `Release` value, not an Epic. The four release workstreams are
Features with native child issues. New v1.1 work must be added to the existing
Project and receive the relevant `Status`, `Type`, `Release`, `Priority`,
`Area`, `Source`, `Service`, `Workstream`, `Effort` and `Beta blocker` values.
Issue-form answers are body text and do not set Project fields automatically.

The built-in Project automation currently auto-adds native sub-issues only.
Until separately reviewed automation exists, either partner must manually:

1. search before creating a Bug, Story, Research or backlog item;
2. add or confirm the issue in the Product Development Project;
3. set `Status = Backlog` initially unless work has genuinely started;
4. set `Release = v1.1` only for approved release work;
5. set `Source = Public Tester` for originating feedback and `Area = Promotion`
   for Promotion children; and
6. move completed work to `Done` only after its acceptance and evidence are
   complete.

Project metadata automation must never call a deployment workflow or receive a
production credential.

## Access verification checklist

After Bernard and Danny provide their individual GitHub usernames:

1. verify each account, two-factor authentication and account-recovery owner;
2. export current repository and Project collaborators before mutation;
3. grant the broadest safe personal-Project role and repository access without
   replacing existing collaborators;
4. verify Danny can create/read/update/close/reopen issues, edit Project fields
   and views, create branches and PRs, review/merge where policy allows, and
   manage labels/releases where the personal-account permission model permits;
5. record separately what remains owner-only, especially repository settings;
6. preserve environment protections, OIDC, AWS roles and production secrets;
   and
7. perform the staged organisation migration before claiming two equivalent
   owner/admin partners.

The long-term correction is a dedicated JSC GitHub organisation with Bernard
and Danny as organisation Owners and Project/repository administrators. See the
[organisation migration plan](../plans/jsc-github-organisation-migration.md).
