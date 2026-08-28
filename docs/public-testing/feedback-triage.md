# Public tester feedback and bug triage

Status: **implemented and tested on feature branches; deployed/enabled: NO**

This runbook turns public-tester reports into reviewable product evidence without
requiring a tester to use GitHub. It applies to Job Seeker Copilot v1.1 and does
not grant any issue-management workflow permission to deploy production.

Bernard and Danny are partners. The target model lets either partner triage
reports, create or update issues, change classification and priority, link work,
close it, or reopen it. Current Danny repository/Project access is not verified;
the exact username and CRUD check remain access blockers. Production credentials
and protected-environment approvals remain separate controls.

## Sources and system of record

When separately deployed and enabled, the in-product form sends a size-bounded
report to the dedicated feedback store and returns an opaque reference suitable
for a tester to retain. The reference is not a bearer credential: it cannot read,
list, alter or delete a report. Only an authenticated, authorised operator using
least-privilege local AWS credentials can read the private store. The store then
acts as the intake system of record until deliberate triage.

Reports received through a conversation, email or other partner channel must not
be re-entered through the public form: doing so would attach the partner's page,
build, timing and optional device diagnostics rather than the tester's consented
context. Create the minimum safe GitHub issue with the public-tester source, or
use a separately reviewed manual-intake path that suppresses diagnostics. Never
paste a private message or personal data into an issue.

The implemented feedback store does not create GitHub issues or application
releases. The branch-only triage bridge is partner-operated, defaults to a dry
run, uses local AWS and GitHub credentials, and creates one issue only after the
operator supplies an exact reference plus `--apply`. A GitHub credential is never
sent to, embedded in, or returned by the browser application.

## Intake classification

Classify each report as one of:

- **Something is broken**: a candidate Bug beneath the Public Tester Bug Fixes
  Feature.
- **Something is confusing**: retain as feedback; create a Story or Bug only
  when triage evidence supports it.
- **Feature suggestion**: retain as feedback; place resulting work in v1.1 only
  when it directly supports the approved release goals.
- **Other feedback**: retain and classify after review.

Use the tester-provided current page, description and optional reproduction
steps. Coarse diagnostics are included only when the tester opts in. Never ask
for or copy passwords, tokens, cookies, payment data, CV or cover-letter content,
or unnecessary account/application details.

## Triage flow

1. Using authenticated partner tooling, open the report by reference and check
   that it contains no unsafe personal or secret material. The public reference
   alone must never retrieve content. Quarantine and redact before any GitHub
   action if unsafe material is present.
2. Search open and closed issues before creating work. Link the report to an
   existing issue when it describes the same outcome.
3. Attempt reproduction using synthetic or fixture data. Record the tested build,
   area, expected result, actual result and the smallest safe evidence.
4. Decide the outcome: duplicate, needs information, not reproducible, accepted
   feedback, Bug, Story, Research, security escalation, or privacy escalation.
5. For accepted GitHub work, preserve the feedback reference, not the full stored
   submission. Apply `public-tester` and `feedback`; add `bug` only for a verified
   defect.
6. Set Project values when the fields are available: `Source = Public Tester`,
   the evidence-based Priority, the affected Area, and the intended Release.
7. Link verified v1.1 Bugs beneath
   `[Feature] Public Tester Bug Fixes`; link implementation or research for the
   intake mechanism beneath `[Feature] Public Tester Feedback & Issue Reporting`.
8. Let the reviewed CLI mark the stored report `TRIAGED` only after it records the
   exact issue URL. The current CLI does not implement no-issue dispositions;
   that remains child Story #308 work and must not be simulated with an
   unreviewed direct table edit.

The intended state sequence is:

`Report -> Triage -> Reproduce -> Prioritise -> Fix -> Test -> PR -> Review -> Release -> Verify`

## Priority and release decision

- **P0**: an actively exploitable security/privacy incident, widespread data loss,
  or live-product outage. Follow incident controls; do not expose details in a
  public issue.
- **P1**: a serious, reproducible blocker to a core public-testing journey or a
  high-impact reliability defect.
- **P2**: a reproducible defect or usability problem with a viable workaround.
- **P3**: minor, narrow or cosmetic impact.

A public-tester source does not automatically make an item v1.1. Include it only
when evidence and capacity support the release goal. Otherwise use Post-v1.1,
Future or Backlog. A beta-blocker flag requires evidence that meaningful or safe
testing cannot continue.

## Bug traceability

A Bug is ready for implementation when it links, where applicable, to:

- the originating feedback reference and any duplicate references;
- safe reproduction evidence and affected build;
- its parent Feature and release target;
- the fixing pull request;
- a regression test or a recorded reason one is not feasible;
- the release containing the fix; and
- post-release verification evidence.

Close the feedback report and Bug independently. Reopen the Bug if the released
behaviour does not satisfy its acceptance criteria; do not create a duplicate.

## Abuse, security and privacy escalation

The implemented anonymous intake is size-bounded, origin-checked, throttled,
schema-validated, honeypot/timing checked and duplicate-suppressed. These are
abuse controls, not authentication, and the route remains disabled. Triage must
still treat contents as untrusted. Do not follow submitted links or run submitted
commands.
Spam and abusive submissions are closed in the feedback store without a GitHub
issue. Repeated abuse should be addressed at the feedback boundary, not by
weakening unrelated application authentication.

Potential credentials, payment information, personal-data exposure or security
vulnerabilities must not be copied into a normal issue. Never retain or copy a
raw credential as feedback evidence: restrict access, revoke or rotate it where
applicable, delete it under the incident/privacy procedure, and retain only a
redacted incident reference. Follow [SECURITY.md](../../SECURITY.md); the absence
of an actionable public confidential route is tracked in Infrastructure #319.
Production investigation or remediation needs its own authorised task.

## Operator procedure

The implemented operator is
`job-seeker-copilot-landing/infrastructure/waitlist-backend/admin/feedback_triage.py`.
It requires an independently attributable AWS profile limited to the exact table
and status index, plus local `gh` access to the private Infrastructure repository.
Preview is the default:

```bash
python3 infrastructure/waitlist-backend/admin/feedback_triage.py \
  --profile <partner-profile> --region eu-west-2 \
  --table-name <FeedbackTableName>
```

After privacy review, create exactly one issue:

```bash
python3 infrastructure/waitlist-backend/admin/feedback_triage.py \
  --profile <partner-profile> --region eu-west-2 \
  --table-name <FeedbackTableName> \
  --reference FB-A1B2C3D4E5F60708 --apply
```

The CLI conditionally moves `NEW -> TRIAGING -> TRIAGED`, applies only
`public-tester` and `feedback`, stores the validated issue URL, and never infers
`bug`. If issue creation fails it releases the claim. If the issue is created but
recording its URL fails, it leaves `TRIAGING` and prints the URL for manual
reconciliation; do not rerun creation. Detailed storage, encryption, TTL,
retention and recovery constraints are documented in the Landing repository's
`docs/launch/public-tester-feedback.md`. Feedback deletion/recovery/linked-issue
reconciliation is tracked in Landing #74.

## Completion evidence

Branch validation currently proves:

- the client can submit and display a validated reference in tests;
- the browser bundle contains no GitHub credential or privileged endpoint;
- validation, size, origin, spam and rate controls reject unsafe requests;
- a partner can preview a triage operation without creating an issue;
- a mocked explicitly confirmed triage creates a correctly labelled issue; and
- mocked storage records the issue URL without duplicate creation.

Operational readiness still requires a reviewed deployment/change set, a
non-production browser-to-store exercise, an authorised deletion/retention
procedure, and verification that both partners can manage the resulting Project
item. Neither deployment nor partner CRUD verification occurred in this task.
