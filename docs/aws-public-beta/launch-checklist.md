# AWS public-beta launch checklist

Every checkbox needs dated evidence and an owner. A credential, passing
Terraform plan or AWS credit award alone is not launch approval.

## Business and release authority

- [ ] The owner explicitly approves launch, target date and maintenance window.
- [ ] AWS Activate outcome and usable credit balance are recorded; launch is
      still explicitly approved if credits are absent or lower than expected.
- [ ] The functioning website, matching-domain business email, privacy notice,
      terms, support route, pricing and cancellation/refund wording are public.
- [ ] Public pricing and release evidence use the reviewed non-renewing
      10/£4.99, 25/£11.99 and 60/£19.99 credit catalog plus two free credits.
      The dated 11 August £5/£10/£20 scenarios are marked historical/superseded;
      checkout is described as implemented but release-gated, with no live
      charges claimed before settlement evidence exists.
- [ ] The protected public-legal record names the real reviewed sole trader or
      limited company (as applicable), explicit VAT/ICO status, contacts,
      effective date, published URLs, exact immutable Client/Landing legal-
      artifact checksums and retention/deletion decisions. The protected build
      recomputed both checksums from the exact locked source files. The
      Authentication service receives `AUTH_LEGAL_DOCUMENTS_REVIEWED=true`
      only from that reviewed contract. The same non-placeholder
      `LEGAL_VERSION` is proven through Client,
      Authentication registration requirements and Payment; account/document
      deletion promises do not understate the 35-day recovery-copy window.
- [ ] `develop` has the tested landing, application, service and infrastructure
      changes; each reviewed release was subsequently promoted to `main`.
- [ ] `config/workspace-lock.json` pins every exact `main` revision used by the
      immutable build, including Location Service
      `4d8d09a79018c3f281cfead84348d14ed84be851`, Location Gateway
      `86b2805c8430ede14a53a7320b87f0eeb2797b17`, LLM Gateway
      `d84427061766244ec10e367fb3a7a6587809612c` and Client
      `5e923c815e585e433573f50ba0395e71302785ca`.
- [ ] The release ID/build run/image manifest and reviewer are recorded.
- [ ] The pinned Client/Landing source revisions and artifact-contract checksums
      are ancestors of protected `main`; the protected build replaced only the
      generated Landing static/runtime-config/SAM `PENDING` hashes. Client is
      the complete SSR/BFF OCI image; its legal artifact is SHA-256
      `040e208e49e9b12d8504fc3fe2b4f9ccd864f6a0d209475b77881e8b44b77b30`.
      Landing is still explicitly `NOT_DEPLOYED`.

## Account, identity and supply chain

- [ ] AWS account root MFA is enabled and recovery access is held by the named
      account owner; no routine workload or billing task uses root credentials.
- [ ] AWS security, operations and billing alternate contacts are current,
      independently reachable and recorded without putting personal contact
      details in repository evidence.
- [ ] Named least-privilege IAM owners can view bills, budgets, credits, Cost
      Explorer and payment methods; root is not the day-to-day billing owner.
- [ ] CloudTrail management-event coverage, encrypted retention destination,
      retention period and an evidence-access test are reviewed. This stack does
      not claim to create the account-wide audit trail.
- [ ] GuardDuty and Security Hub have an explicit dated enable/defer decision,
      accountable owner, cost impact and compensating controls. A defer decision
      is not represented as an enabled control.
- [ ] The bootstrap CloudFormation change set was independently reviewed and
      manually executed in the intended account/`eu-west-2`.
- [ ] The exact `app.<domain>` certificate is validated in eu-west-2 and its
      reviewed ARN is supplied as `existing_certificate_arn`; the Terraform
      apply role has no ACM write/delete access.
- [ ] State bucket public-access block, versioning, KMS encryption and native
      lock file are verified; a state recovery exercise is recorded.
- [ ] `production-build`, `production-aws-plan`, `production-aws`,
      `production-aws-restore`, `production-aws-restore-observe` and
      `production-aws-restore-cleanup` allow only `main`, disable administrator
      bypass, and have no unsupported reviewer rule. The paid reviewer control
      is unavailable for the current private
      repository plan; the explicitly approved fallback requires
      `jobseekercopilot` to be the workflow actor before OIDC is issued, in
      addition to the exact manual confirmation phrase.
- [ ] The manually executed bootstrap change set exposes the plan, build,
      apply, restore-initiator, semantic start, semantic read-only observer and
      restore-cleanup role outputs. Each protected
      environment has only its matching role ARN and required non-secret
      inputs; there are no static AWS access keys in GitHub or tasks. The
      restore initiator can start/observe AWS Backup but not delete, semantic
      start can only start/describe the fixed Standard state machine, semantic
      observe is read-only, the cleanup role can delete exact drill resources
      but cannot stop the state machine or start a restore, and only the boundary-
      constrained `jsc-public-beta-backup-restore` service role is passed to
      AWS Backup.
- [ ] The source-build job has no OIDC permission/AWS credentials; only the
      separate publisher loads the checksum-bound prepared archive and assumes
      the build role. No repository build/test code runs in that publisher.
- [ ] The live refresh-backed plan was reviewed with no unexpected replacement,
      deletion, provider enablement, HA change or cost-scope change.
- [ ] Every image is digest-pinned and passed the release scan/health check;
      application/operator images have 40-character source revisions, while
      ClamAV records its reviewed LTS version and exact upstream digest.
      Centrally derived PostgreSQL-trust and ClamAV build provenance is attached.
- [ ] ClamAV is a separate ECS service with no `task_role_arn`, no static AWS
      credentials and its own security group. Only Document Store reaches
      `3310`; Document Store no longer has broad public HTTPS egress; scanner
      signatures match and are no more than 48 hours old. The preloaded image,
      initial update/reload and subsequent idempotent health pass were exercised;
      signatures remain ephemeral cache data and are never a backup dependency.
- [ ] The downloaded final release artifact's GitHub attestation, successful
      build run, manifest digest and workspace-lock digest all match, and its
      provenance says `buildPurpose=release` rather than `restore-candidate`.
      A forward release uses the exact current `main` SHA; a rollback
      additionally proves the historical build SHA is an ancestor and hashes
      its historical lock.
- [ ] The Landing static tar, embedded `config/app-config.json` and selected SAM
      copy match their signed SHA-256 values. Its exact reviewed legal/runtime
      values match the protected approval manifest, whose checksum is also
      signed. No legacy Amplify release was authorised by artifact generation.

## Runtime blockers and capacity

- [ ] The retained `jsc-public-beta-rds-monitoring-boundary` exists from the
      reviewed bootstrap update and its live default document has exactly the
      six approved actions and two `RDSOSMetrics` resources; the exact
      monitoring role uses it, trusts only `monitoring.rds.amazonaws.com` for
      the full production DB ARN, and has only
      `AmazonRDSEnhancedMonitoringRole` attached. The protected foundation
      observed six consecutive `MonitoringInterval=60` samples and no
      post-apply “unable to create credentials for” or “unable to configure”
      Enhanced Monitoring RDS event.

- [ ] Document Store contains `1183ce5a54ab60999ca37d826ceb16857d5763ff`
      (or a descendant) and accepts only ECS task-role credentials in S3 mode;
      no static key or custom S3 endpoint is injected.
- [ ] Adzuna contains `594ac33862c6360fe05768905bab0e2cb9ac1898`
      and JSearch contains `79677c6586207f5aa30b9c6d0720f5ed2cfe728a`
      (or descendants); the exact emitted `wget` health check passed in each
      built runtime image.
- [ ] `postcode-io-gateway` contains
      `f5588e5b0a2ca9e63319674f4b6cd40048b9e0fb` (or a descendant), and that
      dependency, Location Service `4d8d09a79018c3f281cfead84348d14ed84be851`,
      Location Gateway `86b2805c8430ede14a53a7320b87f0eeb2797b17` and all
      three exported OpenAPI hashes are recorded in the image manifest. The
      Location Service and Gateway hashes are respectively
      `0cd7a877836dfbf1a42b5f71e0a807ec8dc99f88d69a695d7c5734e320cdef27`
      and `30d71d6b2508c7cbd452b522c30c26bfa7a571e1f1ebcda979008422db469cfc`;
      `POSTCODES_IO_NORTHERN_IRELAND_ENABLED=false` rejects
      full/outward `BT` lookups before any cache/provider/network call. Enabling
      it has a separately completed `postcodes_ni` approval.
- [ ] Authentication contains `d447addae21714f51267c0ab073377c24e3cfe81`
      and OpenAPI SHA-256 `8ef5f12a32e836c2046fb163944b62d76cea31e389612408ca6ed1d1ccc42884`;
      UMG contains `5dc8aa1e7afb9492a96d3dedde847c530b6209b0`, OpenAPI SHA-256
      `dde3349e015f2cd7ef7bf9bc810681bebe98fca1ed1510005aa0b1a8b0e6d08e`
      and Auth snapshot SHA-256
      `95811cb81b0c32ad2f9c5cc42cd8f85c0385359cdade6c0f9e67e3ed63950dc0`;
      Document Generation Gateway is
      `cd9b71a3d4dbfbe41d6784f3eeeb7b1b113f5218` / OpenAPI SHA-256
      `864ba3c36b2ba4bcd1749edc597ed903a21e7dfa515bb2809d3bc9b9cf878f42`,
      Payment is `39005690b2fe5a1da6208b25c3e0e4c9c57c7eb3` /
      `40aa59f62a4ad4d956c2324c9c8d9fa154e4b04b49c029cbda0d80cc2c5dcdc9`,
      Payment Gateway is `99ee685a6809a254305a4cbb4dd92ba0fa7751bc` /
      `9da54edec5a264e541433bf16dbc3826d8e0aa813ceb8e91fcdafab05f324b0b`,
      and Stripe Gateway is `04dd9fa7c095f65120afd37cfc11380176756216` /
      `4fc3c82918d2c062c56a5326b783dfabcf2c3fd68dfdeb56626cca260fa225a7`.
      Auth calls only Payment for lifecycle work; Payment owns Stripe expiry
      with its distinct receiver token and recovery.
- [ ] Isolated signed-settlement acceptance evidence is ancestor-verified at
      System Data `ca4bafeafbfe41b25a8507f6f08d97490ef71a28`, E2E
      `cfa1a70a0028f11f8019c889b9057ba8124ff8f5` and Infrastructure
      `412566a750ead55740e0b2b4b81cebe29d3e0ad9`; its recorded result is 36/36
      healthy services, 4/4 scenarios and 33/33 steps. System Data/E2E remain
      outside production tasks, repositories and ALB. On the exact Stripe
      image, production-profile `FIXTURE` startup is rejected; production
      `DISABLED` is healthy, returns 404 for the control route and registers no
      conditional fixture control/provider beans. Production task definitions
      contain no fixture token/signing secret, and public OpenAPI has no fixture
      route. Do not claim the shared Stripe JAR lacks dormant fixture bytecode.
- [ ] All seven DB-owning runtime images and the operator contain the same
      checksum-pinned official RDS CA bundle at
      `/etc/jsc/rds/global-bundle.pem`; hostname-verifying TLS was exercised.
- [ ] The reviewed ECS-optimised AL2023 AMI is pinned, its agent is current, the
      account has `awsvpcTrunking=enabled`, every node reports a trunk ID, and
      private subnets retain fleet slots plus eight free IPs.
- [ ] Lean ASG min/desired/max are exactly one. Capacity output remains within
      8,192 CPU units, 32,768 MiB and 40 trunked task slots including node,
      the 29-slot application/ClamAV/operator envelope and node headroom.
- [ ] The ASG references the exact numeric launch-template version, not
      `$Latest`; instance refresh is bounded to `0/100` lean or `50/100` HA,
      uses protected-instance `Refresh`, ECS managed draining, skip-matching
      and automatic host-level rollback. No temporary cost node can launch.
- [ ] ECS service deployment maximum/minimum healthy percentages remain
      `100/0`; the HA capacity proof covers its two-task autoscaling ceiling
      without assuming space for four-copy `200%` rolling deployments.
- [ ] Each of the seven Hikari pools is max 6/min 1 with bounded timeouts; the
      calculated lean budget is 62 and RDS alarms/reserve remain valid.

## Data, security and recovery

- [ ] Database bootstrap succeeded for seven isolated roles/databases before
      any application start; the exact release marker exists.
- [ ] Every Flyway history is present and has no failed row; private health
      preflight and its exact release marker succeeded.
- [ ] Per-service security-group dependency rules and ALB-only public ingress
      were reviewed; ECS Exec is off unless separately approved.
- [ ] WAF tests prove ordinary CRS protection remains active and only the two
      exact authenticated upload paths count `SizeRestrictions_BODY`; the BFF
      still enforces authentication, content type and 10/25 MiB limits.
- [ ] The live default versions and documents of all four attached AWS Backup
      managed policies match the reviewed
      `aws-backup-managed-policy-contract.json`; any AWS-side policy revision
      was independently reviewed before the release preflight was rerun.
- [ ] Latest RDS/S3 backup jobs succeeded. An attested
      `purpose=restore-candidate` build from unchanged protected `main` was
      created before the drill. The protected `prepare-restore-source` action
      kept ingress fixed `503`, bootstrapped/migrated seven databases, quiesced
      every service, and independently verified matching canary rows plus two
      distinct checksum-bound S3 object versions before starting paired backups.
      Protected tfvars supplied no `additional_tags`; a simulated preparation
      failure proved the `always()` containment left the listener fixed `503`
      and every application/scanner service at desired/running/pending zero.
      The drill used only the exact run/release/source-preparation/canary/restore-start IDs and
      recovery points from that retained evidence. Their creation skew was at
      most ten minutes; completion skew was not misreported as consistency skew.
      The candidate was never treated as a releasable artifact.
- [ ] The protected restore workflow created a versioned, ACL-free,
      public-blocked, exact-key SSE-KMS destination; restored private RDS with
      the dedicated security group; and requested S3
      `RestoreLatestVersionsUpTo=all`. `observe` bound the completed jobs to the
      exact start artifact, sources, vault, restore role and destinations and
      stripped only the measured inherited RDS production-only tags before
      verifying the exact five drill ownership/cost tags and destination controls.
      The protected semantic workflow then bound the fixed-network broker and
      exact candidate children, exact seven-database source canary, restored
      two-version payload/metadata/SHA integrity, empty-bootstrap
      domain/payment invariants and synthetic non-customer journal
      write/read/reconstruction. Its retained tombstone and locked journal were
      explicitly approved. It did not claim customer object erasure, customer
      metadata/object mapping or aggregate Document Store object health. The
      semantic start held the shared AWS mutation lock until bounded terminal or
      redrive state; no release/restore mutation overlapped any later
      administrator redrive. Any redrive reused only the exact same canonical
      source/replay operation and immutable one-version journal state; it did
      not recreate a post-operation clone or accept extra rows/scopes/requests.
- [ ] Permanent-erasure readiness v3 is `READY` for the exact reviewed
      document, backup and independently reviewed journal-retention policy
      versions. The 35-day maximum matches the foundation Backup plan; the
      machine-written Object-Locked journal is outside that restore blast
      radius; and `recoveryJournalWritePending`,
      `recoveryJournalEvidenceMissing`, `liveErasureReconciliationPending`,
      `restoreJournalReadPending`, `restoreReplayPending` and
      `backupRetentionOverdue` are all zero. `backupRetentionPending` is a
      non-negative informational count and may be greater than zero only for
      erasures still inside the allowed recovery window; it is not treated as
      overdue.
- [ ] After evidence retention, cleanup was separately dispatched through
      `production-aws-restore-cleanup` with
      `DELETE ISOLATED RESTORE DRILL <drill-id>`. The exact drill RDS target and
      every S3 version/delete marker were removed before the bucket, and the
      evidence/live record says `COMPLETED`; neither `observe`, evidence
      validation nor the final build was misreported as cleanup. The exact
      Standard execution was terminal and all semantic broker/child tasks were
      contained before deletion; the permanent SSM tombstone and synthetic
      Object Lock journal version were intentionally retained.
- [ ] The reviewed `jsc-public-beta-restore-drill-evidence.v1` bytes bind the
      candidate Document Store revision, OpenAPI hash and image digest, the
      source-evidence/marker hashes and seven-database/two-version counts, the
      creation-window-bound completed jobs, isolation, all-version S3 controls, semantic
      checks, readiness v3 replay and truthful completed cleanup. Its signed
      reference is retained, its SHA-256 exactly matches
      `documentStorePermanentErasure.restoreDrillEvidenceSha256`, and the same
      bytes are present in protected `RESTORE_DRILL_EVIDENCE_B64` for build,
      plan and apply validation.
- [ ] The exact candidate was promoted with `purpose=release` only after that
      signed/hash-bound evidence and approval update, using the same candidate
      release ID/build run. Promotion made no AWS call and did not rebuild or
      republish images. Its `promotedFrom` hash, release ID, Infrastructure
      revision, Document Store revision, OpenAPI hash and image digest still
      match the drill; otherwise the drill was repeated. Only this newly
      attested release artifact is selected for private prepare and activation.
- [ ] The complete stateful-path inventory was reviewed: no required durable
      data depends on a container or EC2-host filesystem.
- [ ] Key/secret rotation owners, account-removal retention, S3 quarantine
      cleanup and log-access owners are assigned.
- [ ] The reviewed `securityLogRetentionDays` value exactly matches every
      CloudWatch group and the ALB/S3 access-log lifecycle; no shorter or longer
      diagnostic store is silently published under a different promise.
- [ ] The protected emergency-darkening path binds the typed release ID to
      applied state, fixes both HTTPS default and Stripe webhook at `503`
      before task drain, does not require an unexpired approval/build artifact,
      and has an owner for later Terraform drift reconciliation.

## External integrations

- [ ] Postcodes GB has reviewed terms/attribution/quota/cost metadata and an
      approval reference. NI/BT remains disabled unless its distinct LPS
      licensing decision is documented; the runtime flag alone cannot bypass
      the approval manifest or immutable-image capability.
- [ ] At least one useful job provider is approved. Reed, Adzuna and JSearch
      remain disabled without written commercial display/cache/quota approval;
      NHS Jobs and DfE apprenticeships have independent decisions.
- [ ] OpenAI has a current model/pricing decision, a reviewed `GLOBAL` /
      `STANDARD_30_DAY_ABUSE_MONITORING` privacy-control record with data
      sharing disabled, separate completed/due review dates, owner,
      cost/request ceilings and secret; no user data is sent until it passes.
- [ ] Google Maps remains disabled unless a named GCP project, separate program/
      billing decision, exact per-SKU quota IDs and daily limits, attribution/
      privacy decision and `googleBillingQuotasVerified=true` evidence are all
      recorded. GCP budget alerts exist at 50/75/90/100%, and an owner has tested
      the protected emergency-disable runbook; alerts are not a hard cap.
- [ ] Stripe live mode has a current catalog/tax/currency/terms/promotion/
      retention contract, a reviewed sole-trader or limited-company identity
      reference and trader disclosure, distinct service tokens, webhook secret,
      refund/reconciliation runbooks, and fail-closed readiness status `PASS`.
      `NOT_CONFIGURED` cannot reach live checkout; no legal-name placeholder is
      accepted as evidence. The protected `liveStripeCatalog` records the exact
      three permanent live Product/Price pairs; each Price is one-off GBP at
      £4.99, £11.99 or £19.99 and maps only to Starter, Active or Power.
- [ ] SES production access, sending/enforcement health, SPF/DKIM, exact
      `JobSeekerCopilotAccountEmails` configuration/event destination,
      encrypted SNS/KMS publication, suppression/bounce/complaint handling and
      sender-domain ownership pass the read-only release verifier. A named owner
      separately approves one controlled tester account/mailbox and records a
      redacted real password-reset delivery; automation must not choose a
      recipient or retain an address/reset token.
- [ ] Provider secret versions were supplied through the protected operator;
      no secrets appear in approval manifests, tfvars, plans or artifacts.

## Operations, cost and activation

- [ ] The operations SNS email subscription is confirmed and CloudWatch/WAF/
      RDS/ECS/backup alarms have a recorded test delivery.
- [ ] All three USD 750 AWS Budgets are account-wide with no cost filter, so
      tag propagation or an untagged resource cannot hide spend. Available
      user-defined cost-allocation tags and material resource tags are recorded
      separately for attribution.
- [ ] The latest eu-west-2 estimate supports the approximately USD 560 baseline;
      the USD 750 alert threshold is approved and understood not to be a cap.
- [ ] AWS Budgets thresholds and Cost Anomaly Detection are active; Google,
      OpenAI, Stripe and job-provider cost/quota controls are separately owned.
- [ ] Landing SAM ownership, Route 53/SES shared contracts and application CTA
      timing follow [landing integration](landing-integration.md).
- [ ] Landing hosting/SAM promotion has its own reviewer and evidence record;
      `AMPLIFY_RELEASE_AUTHORISED` remains absent/false until that decision, and
      an app activation does not claim the Landing artifact was deployed.
- [ ] The prepared application is still private, target health and alarms are
      good, and a final plan for `public_entrypoint_enabled=true` was reviewed.
- [ ] A second human explicitly approves `ACTIVATE <release-id>`.
- [ ] Post-activation smoke tests, monitoring period, incident owner and exact
      rollback artifact are ready.
