# Landing-site and application integration contract

The landing site is a separate repository and release unit. This infrastructure
work consumes its reviewed artifact contract but does not deploy it or mutate
its AWS resources.

The authoritative application artifact contract is
`job-seeker-copilot-client/docs/release-artifact-contract.md`; the authoritative
landing static/SAM contract is
`job-seeker-copilot-landing/docs/launch/release-artifact-contract.md`. Central
infrastructure consumes those contracts and owns deployment, while each source
repository owns verify/build only.

The checked-in manifest pins the reviewed Client/Landing source revisions and
artifact-contract checksums. The builder still refuses them until each commit
is an ancestor of protected `main`. Landing's static/runtime-config/SAM hashes
remain `PENDING` because those values exist only after the central protected
build; that template state cannot start a release. The immutable build produces:

- one Client SSR/BFF OCI image and records its exact source SHA, contract
  checksum, scan result and ECR digest;
- `landing-static.tar`, built from exactly
  `dist/job-seeker-copilot-landing/browser` without post-build editing;
- `landing-artifact.json`, binding the landing source SHA, contract checksum,
  static tar checksum, embedded `config/app-config.json` checksum and selected
  SAM checksum; and
- `landing-waitlist-backend-template.yaml`, an unchanged copy of the single
  selected landing SAM template.

All four are one release-evidence unit. The signed image manifest transitively
binds their checksums and the exact protected launch-approval manifest. Both
plan and mutation workflows verify those relationships before requesting an AWS
OIDC token. The Landing record remains `deploymentStatus=NOT_DEPLOYED`; artifact
creation is not publication permission.

## Ownership

| Resource/decision | Owner |
|---|---|
| landing source, static artifact and reviewed SAM templates | landing repository; verify/build only |
| Amplify/static promotion and reviewed SAM change-set execution | central landing release orchestration, outside this app Terraform root |
| waitlist/contact API, tables/functions and landing SAM outputs | centrally deployed landing SAM stack |
| SES domain identity, DKIM and landing configuration-set resources | landing SAM/email stack |
| existing public Route 53 hosted zone | shared account prerequisite |
| `app.<domain>` A alias, app ACM certificate, ALB/WAF and application tasks | this Terraform stack |
| application account-email use of verified SES identity/configuration set | this stack consumes the landing-owned identifiers |

Do not import, recreate, delete or rename landing-owned SES/SAM resources from
Terraform. Terraform receives the existing hosted-zone ID, SES identity domain
and configuration-set name as reviewed inputs. Its Authentication task role is
allowed to send only through that identity/configuration contract.

## Coordinated release

1. Promote and verify the landing and application changes in their own
   `develop` environments. Keep the public landing CTA on waitlist/beta wording
   while the app listener is dark.
   `develop` and ordinary `main` verification have no AWS credentials and no
   deployment trigger. The legacy Amplify path additionally requires both
   `AWS_BRANCH=main` and `AMPLIFY_RELEASE_AUTHORISED=true`; central orchestration
   leaves the latter absent/false until a separately approved landing release.
2. Verify the landing SAM stack, domain, DKIM, contact/waitlist flows and
   business-email delivery independently. Record outputs without exposing
   tokens or subscriber data.
3. Prepare the app privately and complete its launch checklist. DNS may exist
   while the ALB returns `503`; it must not be presented as live.
4. Activate the exact app release through its separate protected dispatch.
5. Only after the application smoke test succeeds, publish the landing release
   whose CTA/runtime configuration targets
   `https://app.jobseekercopilot.com` (or the reviewed `application_base_url`).
6. If the app is darkened or rolled back, immediately restore safe landing CTA
   copy or a waitlist destination. The landing backend remains independently
   operable.

Landing and app CORS/auth boundaries remain distinct: the public waitlist/contact
API must not become an authentication bypass or proxy into the application,
and app cookies/tokens must not be exposed to landing functions. Route 53/SES
changes need owners from both release units because a destroy/rename in either
stack can affect the other.

Before production, record the exact landing `main` revision, its static/config/
SAM checksums, selected hosting deployment, SAM stack outputs, app release ID,
hosted-zone ID, SES configuration set and rollback destinations in one
non-secret release record.

The landing `dist/job-seeker-copilot-landing/browser` artifact must publish
`config/app-config.json` with `no-store`. Its `PUBLIC_BETA_ENABLED`, submission,
analytics and indexing switches remain independently false until their own
release steps. Landing and application must expose the same reviewed legal
version/entity/tax/contact/ICO/retention facts; neither may publish placeholder
seller data. The client is one immutable non-root `1000:1000` OCI image on port
3000 with a read-only root and bounded `/tmp`; its
`BFF_TO_PAYMENT_GATEWAY_TOKEN` remains server-only.

## Protected Landing build input

`LANDING_RUNTIME_ENV_B64` is an owner-reviewed base64 encoding of one JSON
object. Its exact allowed keys are enforced by
`scripts/aws/build_landing_artifact.py`; duplicate, omitted or extra keys fail.
The build supplies `AWS_BRANCH=main` only to the repository's offline generation
scripts and never supplies `AMPLIFY_RELEASE_AUTHORISED`.

The generated public JSON contains no secrets, but the input is kept in a
protected GitHub environment to prevent an unreviewed endpoint, legal identity
or public switch entering a candidate. The candidate must use the canonical
production origin and must exactly match the reviewed legal version, entity,
tax, contact, ICO and retention fields in `LAUNCH_APPROVALS_B64`. It must also
point registration, sign-in and pricing at the same HTTPS app origin as that
legal record. The release refuses a different approval-manifest checksum.

`PUBLIC_BETA_ENABLED`, live submissions, analytics and indexing remain four
independent booleans. Their values in an immutable artifact do not deploy or
enable the landing backend. A human still reviews the selected SAM change set,
hosting promotion, email/CORS/abuse controls and post-app-smoke timing.
