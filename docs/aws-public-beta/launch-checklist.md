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
      immutable build, including every mandatory dependency revision.
- [ ] The release ID/build run/image manifest and reviewer are recorded.
- [ ] The pinned Client/Landing source revisions and artifact-contract checksums
      are ancestors of protected `main`; the protected build replaced only the
      generated Landing static/runtime-config/SAM `PENDING` hashes. Client is
      the complete SSR/BFF OCI image; Landing is still explicitly `NOT_DEPLOYED`.

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
- [ ] `production-build`, `production-aws-plan` and `production-aws` allow only
      `main`, disable administrator bypass, and have no unsupported reviewer
      rule. The paid reviewer control is unavailable for the current private
      repository plan; the explicitly approved fallback requires
      `jobseekercopilot` to be the workflow actor before OIDC is issued, in
      addition to the exact manual confirmation phrase.
- [ ] Plan, build and apply OIDC role policies match the reviewed bootstrap
      output; there are no static AWS access keys in GitHub or tasks.
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
- [ ] The downloaded release artifact's GitHub attestation, successful build
      run, manifest digest and workspace-lock digest all match. A forward
      release uses the exact current `main` SHA; a rollback additionally proves
      the historical build SHA is an ancestor and hashes its historical lock.
- [ ] The Landing static tar, embedded `config/app-config.json` and selected SAM
      copy match their signed SHA-256 values. Its exact reviewed legal/runtime
      values match the protected approval manifest, whose checksum is also
      signed. No legacy Amplify release was authorised by artifact generation.

## Runtime blockers and capacity

- [ ] Document Store contains `1183ce5a54ab60999ca37d826ceb16857d5763ff`
      (or a descendant) and accepts only ECS task-role credentials in S3 mode;
      no static key or custom S3 endpoint is injected.
- [ ] Adzuna contains `594ac33862c6360fe05768905bab0e2cb9ac1898`
      and JSearch contains `79677c6586207f5aa30b9c6d0720f5ed2cfe728a`
      (or descendants); the exact emitted `wget` health check passed in each
      built runtime image.
- [ ] `postcode-io-gateway` contains
      `f5588e5b0a2ca9e63319674f4b6cd40048b9e0fb` (or a descendant), and that
      dependency, Location Service `91857140c71bfda8b807c535272f918fe7741263`,
      Location Gateway `777ec7e8885fcb07368e05ad2543181e4ef7a891` and all
      three exported OpenAPI hashes are recorded in the image manifest;
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
- [ ] Latest RDS/S3 backup jobs succeeded, restore-role access is controlled,
      and a quarterly isolated restore drill meeting the declared RPO/RTO is
      recorded.
- [ ] Permanent-erasure readiness v2 is `READY` for the exact reviewed
      document, backup and independently reviewed journal-retention policy
      versions. The 35-day maximum matches the foundation Backup plan; the
      machine-written Object-Locked journal is outside that restore blast
      radius; and `recoveryJournalWritePending`,
      `recoveryJournalEvidenceMissing`, `liveErasureReconciliationPending`,
      `restoreJournalReadPending`, `restoreReplayPending` and
      `backupRetentionPending` are all zero. A completed isolated restore
      replay and fresh backup-expiry attestation are recorded before traffic.
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
- [ ] OpenAI has a current model/pricing decision, EU/privacy control record,
      owner, cost/request ceilings and secret; no user data is sent until it
      passes.
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
- [ ] SES production access, SPF/DKIM, configuration set, suppression/bounce/
      complaint handling and sender-domain ownership are verified.
- [ ] Provider secret versions were supplied through the protected operator;
      no secrets appear in approval manifests, tfvars, plans or artifacts.

## Operations, cost and activation

- [ ] The operations SNS email subscription is confirmed and CloudWatch/WAF/
      RDS/ECS/backup alarms have a recorded test delivery.
- [ ] `CostCentre=public-beta` is activated as a billing cost-allocation tag.
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
