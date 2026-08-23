locals {
  name_prefix                 = "jsc-${var.environment}"
  namespace_name              = "${var.environment}.internal"
  release_placeholder_pattern = "(?i)(^|[^a-z0-9])(todo|tbd|placeholder|pending|not[ _-]?configured|unapproved|unknown|none|n[ /]?a|draft|sample|example|test|change[ _-]?me|replace[ _-]?me)([^a-z0-9]|$)"

  runtime_manifest_path  = "${path.module}/config/runtime-services.json"
  image_manifest_path    = startswith(var.image_manifest_path, "/") ? var.image_manifest_path : "${path.module}/${var.image_manifest_path}"
  approval_manifest_path = startswith(var.approval_manifest_path, "/") ? var.approval_manifest_path : "${path.module}/${var.approval_manifest_path}"

  runtime_manifest  = jsondecode(file(local.runtime_manifest_path))
  image_manifest    = jsondecode(file(local.image_manifest_path))
  approval_manifest = jsondecode(file(local.approval_manifest_path))

  raw_services = local.runtime_manifest.services

  database_owners = {
    authentication-service      = "authentication"
    user-profile-service        = "user_profile"
    job-service                 = "job_service"
    document-generation-gateway = "document_generation"
    document-store-service      = "document_store"
    application-tracker-service = "application_tracker"
    payment-service             = "payment"
  }

  databases = {
    authentication      = { username = "authentication", database = "authentication" }
    user_profile        = { username = "user_profile", database = "user_profile" }
    job_service         = { username = "job_service", database = "job_service" }
    document_generation = { username = "document_generation", database = "document_generation" }
    document_store      = { username = "document_store", database = "document_store" }
    application_tracker = { username = "application_tracker", database = "application_tracker" }
    payment             = { username = "payment", database = "payment" }
  }

  integration_secret_names = toset([
    "reed",
    "adzuna",
    "jsearch",
    "apprenticeships",
    "google_maps",
    "openai",
    "stripe",
  ])

  approval_complete = {
    for name, enabled in var.enabled_integrations : name => (
      !enabled || (
        try(local.approval_manifest.integrations[name].approved, false) &&
        length(trimspace(try(local.approval_manifest.integrations[name].approvalReference, ""))) >= 8 &&
        !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations[name].approvalReference, "")))) &&
        length(trimspace(try(local.approval_manifest.integrations[name].approvedBy, ""))) >= 3 &&
        !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations[name].approvedBy, "")))) &&
        can(regex("^20[0-9]{2}-[0-9]{2}-[0-9]{2}$", try(local.approval_manifest.integrations[name].termsReviewedOn, ""))) &&
        can(regex("^20[0-9]{2}-[0-9]{2}-[0-9]{2}$", try(local.approval_manifest.integrations[name].expiresOn, ""))) &&
        try(timecmp("${local.approval_manifest.integrations[name].termsReviewedOn}T00:00:00Z", plantimestamp()) <= 0, false) &&
        try(timecmp("${local.approval_manifest.integrations[name].expiresOn}T23:59:59Z", plantimestamp()) >= 0, false) &&
        try(timecmp("${local.approval_manifest.integrations[name].termsReviewedOn}T00:00:00Z", "${local.approval_manifest.integrations[name].expiresOn}T23:59:59Z") <= 0, false) &&
        try(timecmp("${local.approval_manifest.integrations[name].termsReviewedOn}T00:00:00Z", local.approval_manifest.reviewedAt) <= 0, false) &&
        try(local.approval_manifest.integrations[name].monthlyRequestLimit, 0) > 0 &&
        try(local.approval_manifest.integrations[name].monthlyCostCeilingGbp, -1) >= 0 &&
        length(trimspace(try(local.approval_manifest.integrations[name].attributionRequirement, ""))) >= 10 &&
        !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations[name].attributionRequirement, ""))))
      )
    )
  }

  google_approval_complete = !var.enabled_integrations.google_maps || (
    local.approval_complete.google_maps &&
    try(local.approval_manifest.integrations.google_maps.googleBillingQuotasVerified, false) &&
    length(trimspace(try(local.approval_manifest.integrations.google_maps.billingQuotaEvidenceReference, ""))) >= 8 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations.google_maps.billingQuotaEvidenceReference, "")))) &&
    length(trimspace(try(local.approval_manifest.integrations.google_maps.gcpProjectId, ""))) >= 4 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations.google_maps.gcpProjectId, "")))) &&
    length(trimspace(try(local.approval_manifest.integrations.google_maps.placesQuotaId, ""))) >= 3 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations.google_maps.placesQuotaId, "")))) &&
    try(local.approval_manifest.integrations.google_maps.placesDailyQuota, 0) > 0 &&
    length(trimspace(try(local.approval_manifest.integrations.google_maps.routeMatrixEssentialsQuotaId, ""))) >= 3 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations.google_maps.routeMatrixEssentialsQuotaId, "")))) &&
    try(local.approval_manifest.integrations.google_maps.routeMatrixEssentialsDailyElementQuota, 0) > 0 &&
    length(trimspace(try(local.approval_manifest.integrations.google_maps.routeMatrixProQuotaId, ""))) >= 3 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations.google_maps.routeMatrixProQuotaId, "")))) &&
    try(local.approval_manifest.integrations.google_maps.routeMatrixProDailyElementQuota, 0) > 0 &&
    try(local.approval_manifest.integrations.google_maps.gcpBudgetAlertGbp, 0) > 0 &&
    try(local.approval_manifest.integrations.google_maps.gcpBudgetAlertGbp, 0) <= try(local.approval_manifest.integrations.google_maps.monthlyCostCeilingGbp, -1) &&
    try(local.approval_manifest.integrations.google_maps.gcpBudgetAlertThresholdPercents, []) == [50, 75, 90, 100] &&
    length(trimspace(try(local.approval_manifest.integrations.google_maps.emergencyDisableOwner, ""))) >= 3 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations.google_maps.emergencyDisableOwner, "")))) &&
    length(trimspace(try(local.approval_manifest.integrations.google_maps.emergencyDisableRunbookReference, ""))) >= 8 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations.google_maps.emergencyDisableRunbookReference, ""))))
  )

  openai_approval_complete = !var.enabled_integrations.openai || (
    local.approval_complete.openai &&
    try(local.approval_manifest.integrations.openai.privacyPolicyVersion, "") == "openai-api-data-controls-2026-08-23" &&
    length(trimspace(try(local.approval_manifest.integrations.openai.privacyDecisionId, ""))) >= 8 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations.openai.privacyDecisionId, "")))) &&
    length(trimspace(try(local.approval_manifest.integrations.openai.privacyOwner, ""))) >= 3 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations.openai.privacyOwner, "")))) &&
    can(regex("^20[0-9]{2}-[0-9]{2}-[0-9]{2}$", try(local.approval_manifest.integrations.openai.privacyReviewedOn, ""))) &&
    try(timecmp("${local.approval_manifest.integrations.openai.privacyReviewedOn}T00:00:00Z", plantimestamp()) <= 0, false) &&
    can(regex("^20[0-9]{2}-[0-9]{2}-[0-9]{2}$", try(local.approval_manifest.integrations.openai.privacyReviewDueOn, ""))) &&
    try(timecmp("${local.approval_manifest.integrations.openai.privacyReviewDueOn}T23:59:59Z", plantimestamp()) >= 0, false) &&
    try(timecmp("${local.approval_manifest.integrations.openai.privacyReviewDueOn}T00:00:00Z", "${local.approval_manifest.integrations.openai.privacyReviewedOn}T00:00:00Z") > 0, false) &&
    try(timecmp("${local.approval_manifest.integrations.openai.privacyReviewDueOn}T00:00:00Z", timeadd("${local.approval_manifest.integrations.openai.privacyReviewedOn}T00:00:00Z", "2232h")) <= 0, false)
  )

  public_legal_contract           = local.approval_manifest.publicLegal
  payment_contract                = local.approval_manifest.integrations.stripe
  document_store_erasure_approval = try(local.approval_manifest.documentStorePermanentErasure, {})
  github_environment_protection   = try(local.approval_manifest.githubEnvironmentProtection, {})
  github_environment_protection_complete = (
    try(local.github_environment_protection.reviewed, false) &&
    try(local.github_environment_protection.environments, []) == ["production-build", "production-aws-plan", "production-aws", "production-aws-restore", "production-aws-restore-cleanup"] &&
    try(local.github_environment_protection.operatorUsername, "") == "jobseekercopilot" &&
    !try(local.github_environment_protection.paidEnvironmentReviewerProtectionAvailable, true) &&
    try(local.github_environment_protection.ownerOnlyWorkflowActorVerified, false) &&
    try(local.github_environment_protection.soloOperatorSelfApprovalAuthorised, false) &&
    try(local.github_environment_protection.exactMainBranchVerified, false) &&
    try(local.github_environment_protection.administratorBypassDisabled, false) &&
    length(trimspace(try(local.github_environment_protection.reviewedBy, ""))) >= 3 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.github_environment_protection.reviewedBy, "")))) &&
    length(trimspace(try(local.github_environment_protection.evidenceReference, ""))) >= 8 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.github_environment_protection.evidenceReference, "")))) &&
    can(regex("^20[0-9]{2}-[0-9]{2}-[0-9]{2}$", try(local.github_environment_protection.reviewedOn, ""))) &&
    try(timecmp("${local.github_environment_protection.reviewedOn}T00:00:00Z", plantimestamp()) <= 0, false) &&
    try(timecmp("${local.github_environment_protection.reviewedOn}T00:00:00Z", local.approval_manifest.reviewedAt) <= 0, false)
  )
  document_store_erasure_approval_complete = (
    try(local.document_store_erasure_approval.reviewed, false) &&
    length(trimspace(try(local.document_store_erasure_approval.reviewedBy, ""))) >= 3 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.document_store_erasure_approval.reviewedBy, "")))) &&
    length(trimspace(try(local.document_store_erasure_approval.evidenceReference, ""))) >= 8 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.document_store_erasure_approval.evidenceReference, "")))) &&
    can(regex("^20[0-9]{2}-[0-9]{2}-[0-9]{2}$", try(local.document_store_erasure_approval.reviewedOn, ""))) &&
    try(timecmp("${local.document_store_erasure_approval.reviewedOn}T00:00:00Z", plantimestamp()) <= 0, false) &&
    try(timecmp("${local.document_store_erasure_approval.reviewedOn}T00:00:00Z", local.approval_manifest.reviewedAt) <= 0, false) &&
    can(regex("^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$", try(local.document_store_erasure_approval.retentionPolicyVersion, ""))) &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.document_store_erasure_approval.retentionPolicyVersion, "")))) &&
    can(regex("^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$", try(local.document_store_erasure_approval.backupRetentionPolicyVersion, ""))) &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.document_store_erasure_approval.backupRetentionPolicyVersion, "")))) &&
    can(regex("^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$", try(local.document_store_erasure_approval.journalRetentionPolicyVersion, ""))) &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.document_store_erasure_approval.journalRetentionPolicyVersion, "")))) &&
    try(local.document_store_erasure_approval.maximumBackupRetentionDays, 0) == 35 &&
    try(local.document_store_erasure_approval.journalRetentionDays, 0) == var.foundation_erasure_journal_retention_days &&
    try(local.document_store_erasure_approval.journalRetentionDays, 0) > 35 &&
    try(local.document_store_erasure_approval.externalDeletionJournalVerified, false) &&
    try(local.document_store_erasure_approval.isolatedRestoreReplayVerified, false) &&
    can(regex("^[0-9a-f]{64}$", try(local.document_store_erasure_approval.restoreDrillEvidenceSha256, ""))) &&
    try(local.document_store_erasure_approval.restoreDrillEvidenceSha256, "") != "0000000000000000000000000000000000000000000000000000000000000000" &&
    try(local.document_store_erasure_approval.journalRetentionDays, 0) >= try(local.public_legal_contract.accountDeletionCompletionDays, 0) &&
    try(local.document_store_erasure_approval.journalRetentionDays, 0) >= try(local.public_legal_contract.documentDeletionCompletionDays, 0)
  )
  document_store_permanent_erasure_image_ready = (
    try(local.image_manifest.capabilities.documentStorePermanentErasureVerified, false) &&
    can(regex("^[0-9a-f]{40}$", try(local.image_manifest.dependencyEvidence.documentStorePermanentErasure.revision, ""))) &&
    try(local.image_manifest.dependencyEvidence.documentStorePermanentErasure.revision, "") != "0000000000000000000000000000000000000000" &&
    can(regex("^[0-9a-f]{64}$", try(local.image_manifest.dependencyEvidence.documentStorePermanentErasure.openApiSha256, ""))) &&
    try(local.image_manifest.dependencyEvidence.documentStorePermanentErasure.openApiSha256, "") != "0000000000000000000000000000000000000000000000000000000000000000" &&
    try(local.image_manifest.dependencyEvidence.documentStorePermanentErasure.maximumBackupRetentionDays, 0) == 35 &&
    try(local.image_manifest.dependencyEvidence.documentStorePermanentErasure.restoreReplayRunbook, "") == "docs/aws-public-beta/document-store-permanent-erasure.md" &&
    can(regex("^[0-9a-f]{64}$", try(local.image_manifest.dependencyEvidence.documentStorePermanentErasure.restoreReplayRunbookSha256, ""))) &&
    try(local.image_manifest.dependencyEvidence.documentStorePermanentErasure.restoreReplayRunbookSha256, "") != "0000000000000000000000000000000000000000000000000000000000000000"
  )
  document_store_permanent_erasure_runtime_enabled = (
    local.document_store_erasure_approval_complete &&
    local.document_store_permanent_erasure_image_ready
  )
  expected_catalog_plans = [
    { id = "starter", documentCredits = 10, priceGbpPence = 499 },
    { id = "active", documentCredits = 25, priceGbpPence = 1199 },
    { id = "power", documentCredits = 60, priceGbpPence = 1999 },
  ]
  live_stripe_catalog_by_id = {
    for entry in try(local.payment_contract.liveStripeCatalog, []) : entry.id => entry
  }
  payment_contract_complete = (
    try(local.payment_contract.catalogVersion, "") == "public-beta-2026-08-22" &&
    try(local.payment_contract.catalogPlans, []) == local.expected_catalog_plans &&
    toset(keys(local.live_stripe_catalog_by_id)) == toset(["starter", "active", "power"]) &&
    alltrue([
      for entry in values(local.live_stripe_catalog_by_id) :
      can(regex("^prod_[A-Za-z0-9]+$", try(entry.productId, ""))) &&
      can(regex("^price_[A-Za-z0-9]+$", try(entry.priceId, "")))
    ]) &&
    length(distinct([for entry in values(local.live_stripe_catalog_by_id) : entry.productId])) == 3 &&
    length(distinct([for entry in values(local.live_stripe_catalog_by_id) : entry.priceId])) == 3 &&
    try(local.payment_contract.freeDocumentCredits, 0) == 2 &&
    try(local.payment_contract.billingCountry, "") == "GB" &&
    try(local.payment_contract.currency, "") == "GBP" &&
    try(local.payment_contract.creditUnit, "") == "DOCUMENT" &&
    !try(local.payment_contract.automaticRenewal, true) &&
    try(local.payment_contract.displayedPriceIsCheckoutTotal, false) &&
    contains(["NOT_VAT_REGISTERED", "VAT_REGISTERED"], try(local.payment_contract.taxStatus, "NOT_CONFIGURED")) &&
    (
      (try(local.payment_contract.taxStatus, "") == "VAT_REGISTERED" && try(local.payment_contract.taxTreatment, "") == "VAT_INCLUDED") ||
      (try(local.payment_contract.taxStatus, "") == "NOT_VAT_REGISTERED" && try(local.payment_contract.taxTreatment, "") == "VAT_NOT_CHARGED")
    ) &&
    length(trimspace(try(local.payment_contract.consumerTermsVersion, ""))) >= 3 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.payment_contract.consumerTermsVersion, "")))) &&
    can(regex("^20[0-9]{2}-[0-9]{2}-[0-9]{2}$", try(local.payment_contract.consumerTermsEffectiveOn, ""))) &&
    try(timecmp("${local.payment_contract.consumerTermsEffectiveOn}T00:00:00Z", plantimestamp()) <= 0, false) &&
    can(regex("^https://", try(local.payment_contract.consumerTermsUrl, ""))) &&
    can(regex("^[0-9a-f]{64}$", try(local.payment_contract.consumerTermsContentSha256, ""))) &&
    try(local.payment_contract.consumerTermsContentSha256, "") != "0000000000000000000000000000000000000000000000000000000000000000" &&
    try(local.payment_contract.financialRecordRetentionYears, 0) >= 7 &&
    try(local.payment_contract.financialRecordRetentionYears, 0) <= 10 &&
    try(local.payment_contract.stripeApiVersion, "") == "2026-02-25.clover" &&
    contains(["SOLE_TRADER", "LIMITED_COMPANY"], try(local.payment_contract.legalEntityType, "NOT_CONFIGURED")) &&
    can(regex("^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$", try(local.payment_contract.legalEntityConfigurationVersion, ""))) &&
    try(local.payment_contract.legalEntityConfigurationVersion, "NOT_CONFIGURED") != "NOT_CONFIGURED" &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.payment_contract.legalEntityConfigurationVersion, "")))) &&
    try(local.payment_contract.legalEntityReviewed, false) &&
    length(trimspace(try(local.payment_contract.legalEntityEvidenceReference, ""))) >= 8 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.payment_contract.legalEntityEvidenceReference, "")))) &&
    try(local.payment_contract.merchantTermsTraderDisclosureVerified, false) &&
    try(local.payment_contract.checkoutEnabled, false) == var.enabled_integrations.stripe &&
    try(local.payment_contract.checkoutReleaseAuthorised, false) == var.enabled_integrations.stripe &&
    try(local.payment_contract.providerLiveModeExpected, false) == var.enabled_integrations.stripe &&
    try(local.payment_contract.stripeLiveReleaseAuthorised, false) == var.enabled_integrations.stripe &&
    (
      !try(local.payment_contract.foundingPromotionEnabled, false) ||
      try(local.payment_contract.foundingPromotionReleaseAuthorised, false)
    )
  )

  public_legal_contract_complete = (
    can(regex("^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", try(local.approval_manifest.reviewedAt, ""))) &&
    try(timecmp(local.approval_manifest.reviewedAt, plantimestamp()) <= 0, false) &&
    try(local.public_legal_contract.reviewed, false) &&
    length(trimspace(try(local.public_legal_contract.reviewedBy, ""))) >= 3 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.public_legal_contract.reviewedBy, "")))) &&
    length(trimspace(try(local.public_legal_contract.evidenceReference, ""))) >= 8 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.public_legal_contract.evidenceReference, "")))) &&
    can(regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", try(local.public_legal_contract.legalVersion, ""))) &&
    try(local.public_legal_contract.legalVersion, "NOT_CONFIGURED") != "NOT_CONFIGURED" &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.public_legal_contract.legalVersion, "")))) &&
    can(regex("^20[0-9]{2}-[0-9]{2}-[0-9]{2}$", try(local.public_legal_contract.effectiveOn, ""))) &&
    try(timecmp("${local.public_legal_contract.effectiveOn}T00:00:00Z", plantimestamp()) <= 0, false) &&
    try(timecmp("${local.public_legal_contract.effectiveOn}T00:00:00Z", local.approval_manifest.reviewedAt) <= 0, false) &&
    contains(["SOLE_TRADER", "LIMITED_COMPANY"], try(local.public_legal_contract.legalEntityType, "NOT_CONFIGURED")) &&
    contains(["NOT_VAT_REGISTERED", "VAT_REGISTERED"], try(local.public_legal_contract.taxStatus, "NOT_CONFIGURED")) &&
    length(trimspace(try(local.public_legal_contract.legalEntityName, ""))) >= 2 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.public_legal_contract.legalEntityName, "")))) &&
    length(trimspace(try(local.public_legal_contract.tradingName, ""))) >= 2 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.public_legal_contract.tradingName, "")))) &&
    length(trimspace(try(local.public_legal_contract.businessAddress, ""))) >= 8 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.public_legal_contract.businessAddress, "")))) &&
    can(regex("^[^@[:space:]]+@([a-z0-9-]+[.])*jobseekercopilot[.]com$", lower(try(local.public_legal_contract.privacyEmail, "")))) &&
    can(regex("^[^@[:space:]]+@([a-z0-9-]+[.])*jobseekercopilot[.]com$", lower(try(local.public_legal_contract.supportEmail, "")))) &&
    (
      try(local.public_legal_contract.icoRegistrationStatus, "NOT_CONFIGURED") == "NOT_REQUIRED_CONFIRMED" ||
      (
        try(local.public_legal_contract.icoRegistrationStatus, "NOT_CONFIGURED") == "REGISTERED" &&
        can(regex("^[A-Za-z0-9-]{4,40}$", try(local.public_legal_contract.icoRegistrationReference, "")))
      )
    ) &&
    try(local.public_legal_contract.accountDeletionCompletionDays, 0) >= 35 &&
    try(local.public_legal_contract.accountDeletionCompletionDays, 0) <= 365 &&
    try(local.public_legal_contract.documentDeletionCompletionDays, 0) >= 35 &&
    try(local.public_legal_contract.documentDeletionCompletionDays, 0) <= 365 &&
    try(local.public_legal_contract.securityLogRetentionDays, 0) >= 30 &&
    try(local.public_legal_contract.securityLogRetentionDays, 0) <= 3650 &&
    try(local.public_legal_contract.securityLogRetentionDays, 0) == var.log_retention_days &&
    try(local.public_legal_contract.supportRecordRetentionDays, 0) >= 30 &&
    try(local.public_legal_contract.supportRecordRetentionDays, 0) <= 3650 &&
    try(local.public_legal_contract.financialRecordRetentionYears, 0) >= 7 &&
    try(local.public_legal_contract.financialRecordRetentionYears, 0) <= 10 &&
    try(local.public_legal_contract.termsUrl, "") == "${trimsuffix(var.application_base_url, "/")}/terms" &&
    try(local.public_legal_contract.privacyNoticeUrl, "") == "${trimsuffix(var.application_base_url, "/")}/privacy" &&
    can(regex("^[0-9a-f]{64}$", try(local.public_legal_contract.clientLegalArtifactSha256, ""))) &&
    try(local.public_legal_contract.clientLegalArtifactSha256, "") != "0000000000000000000000000000000000000000000000000000000000000000" &&
    can(regex("^[0-9a-f]{64}$", try(local.public_legal_contract.landingLegalArtifactSha256, ""))) &&
    try(local.public_legal_contract.landingLegalArtifactSha256, "") != "0000000000000000000000000000000000000000000000000000000000000000" &&
    try(local.payment_contract.legalEntityType, "") == try(local.public_legal_contract.legalEntityType, "") &&
    try(local.payment_contract.legalEntityConfigurationVersion, "") == try(local.public_legal_contract.legalVersion, "") &&
    try(local.payment_contract.taxStatus, "") == try(local.public_legal_contract.taxStatus, "") &&
    try(local.payment_contract.consumerTermsVersion, "") == try(local.public_legal_contract.legalVersion, "") &&
    try(local.payment_contract.consumerTermsEffectiveOn, "") == try(local.public_legal_contract.effectiveOn, "") &&
    try(local.payment_contract.consumerTermsUrl, "") == try(local.public_legal_contract.termsUrl, "") &&
    try(local.payment_contract.consumerTermsContentSha256, "") == try(local.public_legal_contract.clientLegalArtifactSha256, "") &&
    try(local.payment_contract.financialRecordRetentionYears, 0) == try(local.public_legal_contract.financialRecordRetentionYears, 0)
  )

  stripe_approval_complete = !var.enabled_integrations.stripe || (
    local.approval_complete.stripe &&
    local.payment_contract_complete &&
    try(local.approval_manifest.integrations.stripe.paymentReadinessStatus, "BLOCKED") == "PASS" &&
    length(trimspace(try(local.approval_manifest.integrations.stripe.refundRunbookReference, ""))) >= 8 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations.stripe.refundRunbookReference, "")))) &&
    length(trimspace(try(local.approval_manifest.integrations.stripe.reconciliationRunbookReference, ""))) >= 8 &&
    !can(regex(local.release_placeholder_pattern, trimspace(try(local.approval_manifest.integrations.stripe.reconciliationRunbookReference, ""))))
  )

  any_job_provider_enabled = (
    var.enabled_integrations.reed ||
    var.enabled_integrations.adzuna ||
    var.enabled_integrations.jsearch ||
    var.enabled_integrations.nhs_jobs ||
    var.enabled_integrations.apprenticeships
  )

  substitution_values = {
    "{{namespace}}"                     = local.namespace_name
    "{{db_endpoint}}"                   = aws_db_instance.postgres.address
    "{{region}}"                        = var.aws_region
    "{{application_base_url}}"          = var.application_base_url
    "{{account_email_sender}}"          = var.account_email_sender
    "{{account_email_mode}}"            = var.enabled_integrations.account_email ? "ses" : "fixture"
    "{{ses_configuration_set}}"         = var.ses_configuration_set
    "{{document_bucket}}"               = aws_s3_bucket.documents.bucket
    "{{kms_key_arn}}"                   = var.foundation_data_kms_key_arn
    "{{google_enabled}}"                = tostring(var.enabled_integrations.google_maps)
    "{{google_maximum_sessions}}"       = tostring(var.google_maximum_sessions)
    "{{google_maximum_destinations}}"   = tostring(var.google_maximum_destinations)
    "{{reed_enabled}}"                  = tostring(var.enabled_integrations.reed)
    "{{adzuna_enabled}}"                = tostring(var.enabled_integrations.adzuna)
    "{{jsearch_enabled}}"               = tostring(var.enabled_integrations.jsearch)
    "{{nhs_jobs_enabled}}"              = tostring(var.enabled_integrations.nhs_jobs)
    "{{apprenticeships_enabled}}"       = tostring(var.enabled_integrations.apprenticeships)
    "{{openai_mode}}"                   = var.enabled_integrations.openai ? "LIVE" : "DISABLED"
    "{{job_search_mode}}"               = local.any_job_provider_enabled ? "REAL_PROVIDERS" : "REQUIRED_VALIDATION"
    "{{document_generation_mode}}"      = var.enabled_integrations.openai ? "REAL_LLM" : "REQUIRED_VALIDATION"
    "{{openai_privacy_policy_version}}" = try(local.approval_manifest.integrations.openai.privacyPolicyVersion, "")
    "{{openai_privacy_decision_id}}"    = try(local.approval_manifest.integrations.openai.privacyDecisionId, "")
    "{{openai_privacy_owner}}"          = try(local.approval_manifest.integrations.openai.privacyOwner, "")
    "{{openai_privacy_reviewed_on}}"    = try(local.approval_manifest.integrations.openai.privacyReviewedOn, "")
    "{{openai_privacy_review_due_on}}"  = try(local.approval_manifest.integrations.openai.privacyReviewDueOn, "")
  }

  payment_commercial_environment = {
    PAYMENT_CHECKOUT_ENABLED                      = tostring(var.enabled_integrations.stripe && try(local.payment_contract.checkoutEnabled, false))
    PAYMENT_CHECKOUT_RELEASE_AUTHORISED           = tostring(var.enabled_integrations.stripe && try(local.payment_contract.checkoutReleaseAuthorised, false))
    PAYMENT_PROVIDER_LIVE_MODE_EXPECTED           = tostring(var.enabled_integrations.stripe && try(local.payment_contract.providerLiveModeExpected, false))
    PAYMENT_TAX_TREATMENT                         = try(local.payment_contract.taxTreatment, "VAT_NOT_CHARGED")
    PAYMENT_TAX_STATUS                            = try(local.payment_contract.taxStatus, "NOT_CONFIGURED")
    PAYMENT_LEGAL_ENTITY_TYPE                     = try(local.payment_contract.legalEntityType, "NOT_CONFIGURED")
    PAYMENT_LEGAL_ENTITY_CONFIGURATION_VERSION    = try(local.payment_contract.legalEntityConfigurationVersion, "NOT_CONFIGURED")
    PAYMENT_LEGAL_ENTITY_REVIEWED                 = tostring(try(local.payment_contract.legalEntityReviewed, false))
    PAYMENT_FOUNDING_PROMOTION_ENABLED            = tostring(try(local.payment_contract.foundingPromotionEnabled, false))
    PAYMENT_FOUNDING_PROMOTION_RELEASE_AUTHORISED = tostring(try(local.payment_contract.foundingPromotionReleaseAuthorised, false))
    PAYMENT_CATALOG_VERSION                       = try(local.payment_contract.catalogVersion, "UNAPPROVED")
    PAYMENT_CONSUMER_TERMS_VERSION                = try(local.payment_contract.consumerTermsVersion, "UNAPPROVED")
    PAYMENT_FINANCIAL_RECORD_RETENTION_YEARS      = tostring(try(local.payment_contract.financialRecordRetentionYears, 0))
  }

  stripe_commercial_environment = {
    EXTERNAL_PROVIDER_MODE         = var.enabled_integrations.stripe ? "LIVE" : "DISABLED"
    STRIPE_LIVE_RELEASE_AUTHORISED = tostring(var.enabled_integrations.stripe && try(local.payment_contract.stripeLiveReleaseAuthorised, false))
    STRIPE_LEGACY_CHECKOUT_ENABLED = "false"
    STRIPE_API_BASE_URL            = "https://api.stripe.com"
    STRIPE_API_VERSION             = try(local.payment_contract.stripeApiVersion, "UNAPPROVED")
    STRIPE_PRICE_STARTER           = try(local.live_stripe_catalog_by_id["starter"].priceId, "UNAPPROVED")
    STRIPE_PRICE_ACTIVE            = try(local.live_stripe_catalog_by_id["active"].priceId, "UNAPPROVED")
    STRIPE_PRICE_POWER             = try(local.live_stripe_catalog_by_id["power"].priceId, "UNAPPROVED")
  }

  public_legal_environment = {
    LEGAL_DOCUMENTS_REVIEWED          = tostring(try(local.public_legal_contract.reviewed, false))
    LEGAL_EFFECTIVE_DATE              = try(local.public_legal_contract.effectiveOn, "")
    LEGAL_VERSION                     = try(local.public_legal_contract.legalVersion, "NOT_CONFIGURED")
    LEGAL_ENTITY_TYPE                 = try(local.public_legal_contract.legalEntityType, "NOT_CONFIGURED")
    TAX_STATUS                        = try(local.public_legal_contract.taxStatus, "NOT_CONFIGURED")
    LEGAL_ENTITY_NAME                 = try(local.public_legal_contract.legalEntityName, "")
    TRADING_NAME                      = try(local.public_legal_contract.tradingName, "")
    BUSINESS_ADDRESS                  = try(local.public_legal_contract.businessAddress, "")
    PRIVACY_EMAIL                     = try(local.public_legal_contract.privacyEmail, "")
    SUPPORT_EMAIL                     = try(local.public_legal_contract.supportEmail, "")
    ICO_REGISTRATION_STATUS           = try(local.public_legal_contract.icoRegistrationStatus, "NOT_CONFIGURED")
    ICO_REGISTRATION_REFERENCE        = try(local.public_legal_contract.icoRegistrationReference, "")
    ACCOUNT_DELETION_COMPLETION_DAYS  = tostring(try(local.public_legal_contract.accountDeletionCompletionDays, 0))
    DOCUMENT_DELETION_COMPLETION_DAYS = tostring(try(local.public_legal_contract.documentDeletionCompletionDays, 0))
    SECURITY_LOG_RETENTION_DAYS       = tostring(try(local.public_legal_contract.securityLogRetentionDays, 0))
    SUPPORT_RECORD_RETENTION_DAYS     = tostring(try(local.public_legal_contract.supportRecordRetentionDays, 0))
    FINANCIAL_RECORD_RETENTION_YEARS  = tostring(try(local.public_legal_contract.financialRecordRetentionYears, 0))
  }

  # Terraform has no user-defined functions. Applying every fixed replacement
  # in this order keeps the reviewed runtime manifest readable and deterministic.
  service_environment = {
    for name, service in local.raw_services : name => merge(
      name == "job-seeker-copilot-client" ? {} : {
        SPRING_PROFILES_ACTIVE = "production"
        SERVER_PORT            = tostring(service.port)
      },
      contains(keys(local.database_owners), name) ? {
        SPRING_DATASOURCE_HIKARI_MAXIMUM_POOL_SIZE  = "6"
        SPRING_DATASOURCE_HIKARI_MINIMUM_IDLE       = "1"
        SPRING_DATASOURCE_HIKARI_CONNECTION_TIMEOUT = "5000"
        SPRING_DATASOURCE_HIKARI_VALIDATION_TIMEOUT = "2000"
        SPRING_DATASOURCE_HIKARI_MAX_LIFETIME       = "1500000"
      } : {},
      {
        for key, value in service.environment : key => replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(
          value,
          "{{namespace}}", local.substitution_values["{{namespace}}"]),
          "{{db_endpoint}}", local.substitution_values["{{db_endpoint}}"]),
          "{{region}}", local.substitution_values["{{region}}"]),
          "{{application_base_url}}", local.substitution_values["{{application_base_url}}"]),
          "{{account_email_sender}}", local.substitution_values["{{account_email_sender}}"]),
          "{{account_email_mode}}", local.substitution_values["{{account_email_mode}}"]),
          "{{ses_configuration_set}}", local.substitution_values["{{ses_configuration_set}}"]),
          "{{document_bucket}}", local.substitution_values["{{document_bucket}}"]),
          "{{kms_key_arn}}", local.substitution_values["{{kms_key_arn}}"]),
          "{{google_enabled}}", local.substitution_values["{{google_enabled}}"]),
          "{{google_maximum_sessions}}", local.substitution_values["{{google_maximum_sessions}}"]),
          "{{google_maximum_destinations}}", local.substitution_values["{{google_maximum_destinations}}"]),
          "{{reed_enabled}}", local.substitution_values["{{reed_enabled}}"]),
          "{{adzuna_enabled}}", local.substitution_values["{{adzuna_enabled}}"]),
          "{{jsearch_enabled}}", local.substitution_values["{{jsearch_enabled}}"]),
          "{{nhs_jobs_enabled}}", local.substitution_values["{{nhs_jobs_enabled}}"]),
          "{{apprenticeships_enabled}}", local.substitution_values["{{apprenticeships_enabled}}"]),
          "{{openai_mode}}", local.substitution_values["{{openai_mode}}"]),
          "{{job_search_mode}}", local.substitution_values["{{job_search_mode}}"]),
          "{{document_generation_mode}}", local.substitution_values["{{document_generation_mode}}"]),
          "{{openai_privacy_policy_version}}", local.substitution_values["{{openai_privacy_policy_version}}"]),
          "{{openai_privacy_decision_id}}", local.substitution_values["{{openai_privacy_decision_id}}"]),
          "{{openai_privacy_owner}}", local.substitution_values["{{openai_privacy_owner}}"]),
          "{{openai_privacy_reviewed_on}}", local.substitution_values["{{openai_privacy_reviewed_on}}"]),
          "{{openai_privacy_review_due_on}}", local.substitution_values["{{openai_privacy_review_due_on}}"]
        )
      },
      name == "payment-service" ? local.payment_commercial_environment : {},
      name == "stripe-gateway" ? local.stripe_commercial_environment : {},
      name == "postcode-io-gateway" ? {
        POSTCODES_IO_NORTHERN_IRELAND_ENABLED = tostring(var.enabled_integrations.postcodes_ni)
      } : {},
      name == "document-store-service" ? {
        DOCUMENT_STORE_PURGE_ENABLED                            = tostring(local.document_store_permanent_erasure_runtime_enabled)
        DOCUMENT_STORE_PERMANENT_ERASURE_ENABLED                = tostring(local.document_store_permanent_erasure_runtime_enabled)
        DOCUMENT_STORE_PERMANENT_ERASURE_WRITE_FENCE_ENABLED    = "true"
        DOCUMENT_STORE_VERSIONED_OBJECT_ERASURE_ENABLED         = tostring(local.document_store_permanent_erasure_runtime_enabled)
        DOCUMENT_STORE_RETENTION_POLICY_VERSION                 = try(local.document_store_erasure_approval.retentionPolicyVersion, "NOT_CONFIGURED")
        DOCUMENT_STORE_BACKUP_RETENTION_POLICY_VERSION          = try(local.document_store_erasure_approval.backupRetentionPolicyVersion, "NOT_CONFIGURED")
        DOCUMENT_STORE_MAXIMUM_BACKUP_RETENTION_DAYS            = tostring(try(local.document_store_erasure_approval.maximumBackupRetentionDays, 0))
        DOCUMENT_STORE_ERASURE_JOURNAL_PROVIDER                 = "s3"
        DOCUMENT_STORE_ERASURE_JOURNAL_REGION                   = var.aws_region
        DOCUMENT_STORE_ERASURE_JOURNAL_BUCKET                   = var.foundation_erasure_journal_bucket_name
        DOCUMENT_STORE_ERASURE_JOURNAL_KMS_KEY_ID               = var.foundation_erasure_journal_kms_key_arn
        DOCUMENT_STORE_ERASURE_JOURNAL_CREDENTIALS_PROVIDER     = "task-role"
        DOCUMENT_STORE_ERASURE_JOURNAL_OBJECT_LOCK_ENABLED      = "true"
        DOCUMENT_STORE_ERASURE_JOURNAL_RETENTION_POLICY_VERSION = try(local.document_store_erasure_approval.journalRetentionPolicyVersion, "NOT_CONFIGURED")
      } : {},
      name == "authentication-service" ? {
        AUTH_LEGAL_DOCUMENTS_REVIEWED = tostring(try(local.public_legal_contract.reviewed, false))
        AUTH_LEGAL_CURRENT_VERSION    = try(local.public_legal_contract.legalVersion, "NOT_CONFIGURED")
        AUTH_LEGAL_TERMS_URL          = try(local.public_legal_contract.termsUrl, "")
        AUTH_LEGAL_PRIVACY_NOTICE_URL = try(local.public_legal_contract.privacyNoticeUrl, "")
      } : {},
      name == "job-seeker-copilot-client" ? merge(local.public_legal_environment, {
        NG_ALLOWED_HOSTS = join(",", compact([
          var.app_domain_name,
          "127.0.0.1",
          "localhost",
          "job-seeker-copilot-client",
          "job-seeker-copilot-client.${local.namespace_name}",
        ]))
      }) : {}
    )
  }

  service_secret_specs = {
    for name, service in local.raw_services : name => {
      for environment_name, specification in service.secrets : environment_name => specification
      if !startswith(specification, "integration/") || var.enabled_integrations[split(":", trimprefix(specification, "integration/"))[0]]
    }
  }

  release_attestation_payload = {
    image_manifest        = local.image_manifest
    approval_manifest     = local.approval_manifest
    service_environment   = local.service_environment
    service_secret_specs  = local.service_secret_specs
    enabled_integrations  = var.enabled_integrations
    high_availability     = var.high_availability
    instance_type         = var.instance_type
    db_instance_class     = var.db_instance_class
    db_storage_gib        = var.db_allocated_storage_gib
    application_base_url  = var.application_base_url
    app_domain_name       = var.app_domain_name
    certificate_arn       = local.effective_certificate_arn
    account_email_sender  = var.account_email_sender
    ses_configuration_set = var.ses_configuration_set
    account_email_events = {
      destination_name = "account-email-events"
      event_types      = sort(tolist(local.account_email_event_types))
      topic_arn        = var.foundation_operations_topic_arn
    }
    waf_rate_limit     = var.waf_rate_limit_per_five_minutes
    log_retention_days = var.log_retention_days
    foundation = {
      data_kms_key_arn               = var.foundation_data_kms_key_arn
      operations_topic_arn           = var.foundation_operations_topic_arn
      backup_plan_id                 = var.foundation_backup_plan_id
      erasure_journal_kms_key_arn    = var.foundation_erasure_journal_kms_key_arn
      erasure_journal_bucket_name    = var.foundation_erasure_journal_bucket_name
      erasure_journal_retention_days = var.foundation_erasure_journal_retention_days
      approved_ecs_ami_id            = var.foundation_approved_ecs_ami_id
      monthly_alert_budget_usd       = var.foundation_monthly_alert_budget_usd
    }
  }
  release_attestation_id = sha256(jsonencode(local.release_attestation_payload))

  required_image_names = setunion(toset(keys(local.raw_services)), toset(["clamav", "release-operator"]))
  manifest_image_names = toset(keys(local.image_manifest.images))
  zero_digest          = "sha256:${join("", [for _ in range(64) : "0"])}"

  frontend_release_ready = (
    try(local.image_manifest.dependencyEvidence.frontendArtifacts.client.revision, "") == "3cdb1dec9f6a8b78dbf4c576fdc960ff00aa111a" &&
    try(local.image_manifest.dependencyEvidence.frontendArtifacts.client.artifactContractSha256, "") == "801fab5beb7ea81798677086ef00a94759294a1e85915f74da843632de2c6f75" &&
    try(local.image_manifest.dependencyEvidence.frontendArtifacts.client.packaging, "") == "OCI_SSR_BFF" &&
    try(local.image_manifest.images["job-seeker-copilot-client"].revision, "") == try(local.image_manifest.dependencyEvidence.frontendArtifacts.client.revision, "") &&
    try(local.image_manifest.dependencyEvidence.frontendArtifacts.landing.revision, "") == "ce2a2a45aa32c838f12b3a8ff692ac5c1a0cdee7" &&
    try(local.image_manifest.dependencyEvidence.frontendArtifacts.landing.artifactContractSha256, "") == "9682372ef2d909de3b2b49c6d0fed232565b61e1b1fe0ac666ace58bfdb0804f" &&
    alltrue([
      for digest in [
        try(local.image_manifest.dependencyEvidence.frontendArtifacts.landing.staticArtifactSha256, ""),
        try(local.image_manifest.dependencyEvidence.frontendArtifacts.landing.runtimeConfigSha256, ""),
        try(local.image_manifest.dependencyEvidence.frontendArtifacts.landing.selectedSamTemplateSha256, ""),
      ] : can(regex("^[0-9a-f]{64}$", digest))
    ]) &&
    try(local.image_manifest.dependencyEvidence.frontendArtifacts.landing.selectedSamTemplate, "") == "infrastructure/waitlist-backend/template.yaml" &&
    try(local.image_manifest.dependencyEvidence.frontendArtifacts.landing.deploymentStatus, "") == "NOT_DEPLOYED"
  )

  images_release_ready = (
    local.image_manifest.schemaVersion == 1 &&
    local.image_manifest.releaseId != "UNRELEASED" &&
    local.image_manifest.sourceBranch == "main" &&
    try(local.image_manifest.launchApprovalManifestSha256, "") == filesha256(local.approval_manifest_path) &&
    try(local.image_manifest.dependencyEvidence.documentStoreTaskRoleStorage, "") == "1183ce5a54ab60999ca37d826ceb16857d5763ff" &&
    try(local.image_manifest.dependencyEvidence.adzunaRuntimeHealth, "") == "594ac33862c6360fe05768905bab0e2cb9ac1898" &&
    try(local.image_manifest.dependencyEvidence.jsearchRuntimeHealth, "") == "79677c6586207f5aa30b9c6d0720f5ed2cfe728a" &&
    try(local.image_manifest.capabilities.documentStoreTaskRoleCredentials, false) &&
    try(local.image_manifest.capabilities.documentStoreS3KmsEncryption, false) &&
    local.document_store_permanent_erasure_image_ready &&
    try(local.image_manifest.capabilities.runtimeHealthcheckCommandsVerified, false) &&
    try(local.image_manifest.capabilities.rdsCaBundleVerified, false) &&
    try(local.image_manifest.capabilities.postcodesNorthernIrelandCoverageChainVerified, false) &&
    try(local.image_manifest.capabilities.frontendArtifactsVerified, false) &&
    try(local.image_manifest.capabilities.paymentV2ProductionContractVerified, false) &&
    try(local.image_manifest.capabilities.paymentFixtureAcceptanceVerified, false) &&
    try(local.image_manifest.capabilities.stripeFixtureProductionIsolationVerified, false) &&
    local.frontend_release_ready &&
    try(local.image_manifest.dependencyEvidence.postcodesNorthernIrelandCoverageChain, {}) == {
      postcodeIoGateway = {
        revision      = "f5588e5b0a2ca9e63319674f4b6cd40048b9e0fb"
        openApiSha256 = "8321009c305d2d22986224e366df6f0b451c1b5587d05dd0ec4876441e09d7ff"
      }
      locationService = {
        revision      = "91857140c71bfda8b807c535272f918fe7741263"
        openApiSha256 = "cd74fbf278c710a2782bbbe6473f9f708a19b6dd9329f42927ce302bb53f5f6b"
      }
      locationGateway = {
        revision      = "777ec7e8885fcb07368e05ad2543181e4ef7a891"
        openApiSha256 = "30d71d6b2508c7cbd452b522c30c26bfa7a571e1f1ebcda979008422db469cfc"
      }
    } &&
    try(local.image_manifest.dependencyEvidence.paymentV2ProductionContract, {}) == {
      authenticationService = {
        revision      = "d447addae21714f51267c0ab073377c24e3cfe81"
        openApiSha256 = "8ef5f12a32e836c2046fb163944b62d76cea31e389612408ca6ed1d1ccc42884"
      }
      userManagementGateway = {
        revision           = "5dc8aa1e7afb9492a96d3dedde847c530b6209b0"
        openApiSha256      = "dde3349e015f2cd7ef7bf9bc810681bebe98fca1ed1510005aa0b1a8b0e6d08e"
        authSnapshotSha256 = "95811cb81b0c32ad2f9c5cc42cd8f85c0385359cdade6c0f9e67e3ed63950dc0"
      }
      documentGenerationGateway = {
        revision      = "cd9b71a3d4dbfbe41d6784f3eeeb7b1b113f5218"
        openApiSha256 = "864ba3c36b2ba4bcd1749edc597ed903a21e7dfa515bb2809d3bc9b9cf878f42"
      }
      paymentService = {
        revision      = "39005690b2fe5a1da6208b25c3e0e4c9c57c7eb3"
        openApiSha256 = "40aa59f62a4ad4d956c2324c9c8d9fa154e4b04b49c029cbda0d80cc2c5dcdc9"
      }
      paymentGateway = {
        revision      = "99ee685a6809a254305a4cbb4dd92ba0fa7751bc"
        openApiSha256 = "9da54edec5a264e541433bf16dbc3826d8e0aa813ceb8e91fcdafab05f324b0b"
      }
      stripeGateway = {
        revision      = "04dd9fa7c095f65120afd37cfc11380176756216"
        openApiSha256 = "4fc3c82918d2c062c56a5326b783dfabcf2c3fd68dfdeb56626cca260fa225a7"
      }
    } &&
    try(local.image_manifest.dependencyEvidence.paymentFixtureAcceptance, {}) == {
      systemDataServiceRevision = "ca4bafeafbfe41b25a8507f6f08d97490ef71a28"
      e2eRevision               = "cfa1a70a0028f11f8019c889b9057ba8124ff8f5"
      infrastructureRevision    = "412566a750ead55740e0b2b4b81cebe29d3e0ad9"
      profile                   = "test"
      providerMode              = "FIXTURE"
      healthyServiceCount       = 36
      scenarioCount             = 4
      stepCount                 = 33
    } &&
    try(local.image_manifest.dependencyEvidence.stripeFixtureProductionIsolation, {}) == {
      revision                         = "04dd9fa7c095f65120afd37cfc11380176756216"
      profile                          = "production"
      providerMode                     = "DISABLED"
      fixtureModeStartupRejected       = true
      fixturePaymentControlRouteStatus = 404
      conditionalBeansAbsent = [
        "FixturePaymentControlController",
        "FixturePaymentControlService",
        "FixtureStripeProviderClient",
        "FixtureStripeSessionStore",
      ]
    } &&
    alltrue([
      for evidence in values(try(local.image_manifest.dependencyEvidence.paymentV2ProductionContract, {})) :
      can(regex("^[0-9a-f]{40}$", evidence.revision)) &&
      can(regex("^[0-9a-f]{64}$", evidence.openApiSha256))
    ]) &&
    length(setsubtract(local.required_image_names, local.manifest_image_names)) == 0 &&
    length(setsubtract(local.manifest_image_names, local.required_image_names)) == 0 &&
    alltrue([
      for name, image in local.image_manifest.images :
      can(regex("^sha256:[0-9a-f]{64}$", image.digest)) &&
      image.digest != local.zero_digest &&
      image.scanStatus == "PASSED" &&
      (name == "clamav" || can(regex("^[0-9a-f]{40}$", image.revision)))
    ])
  )

  instance_capacity = {
    "m7i.2xlarge" = { cpu = 8192, memory = 32768, awsvpc_tasks_per_instance = 40 }
    "m7i.4xlarge" = { cpu = 16384, memory = 65536, awsvpc_tasks_per_instance = 80 }
  }

  node_count = var.high_availability ? 2 : 1
  # HA application autoscaling may retain two steady copies. Deployment
  # maximum-percent is fixed at 100, so replacement never adds a third/fourth
  # copy on top of that steady-state envelope.
  deployment_copy_multiplier = var.high_availability ? 2 : 1
  # The scanner is a separate no-task-role ECS service. It remains dark with
  # the application and runs one copy per reviewed node when the fleet starts.
  clamav_desired_count     = var.application_desired_count * local.deployment_copy_multiplier
  os_reserved_cpu          = 1024 * local.node_count
  os_reserved_memory       = 4096 * local.node_count
  operator_reserved_cpu    = 256
  operator_reserved_memory = 512
  steady_state_reserved_cpu = (
    sum([for service in local.raw_services : service.cpu]) + 512 + local.operator_reserved_cpu
  )
  steady_state_reserved_memory = (
    sum([for service in local.raw_services : service.memory]) + 4096 + local.operator_reserved_memory
  )
  steady_state_task_slots = length(local.raw_services) + 2
  # Capacity is approved against the largest scheduling envelope, independent
  # of the currently applied desired count. All deployments are stop-first;
  # HA must fit the autoscaling ceiling of two copies of every service.
  release_reserved_cpu = (
    (sum([for service in local.raw_services : service.cpu]) + 512) * local.deployment_copy_multiplier +
    local.operator_reserved_cpu
  )
  release_reserved_memory = (
    (sum([for service in local.raw_services : service.memory]) + 4096) * local.deployment_copy_multiplier +
    local.operator_reserved_memory
  )
  release_task_slots = (length(local.raw_services) + 1) * local.deployment_copy_multiplier + 1

  expanded_cost_shape = (
    var.high_availability ||
    var.instance_type != "m7i.2xlarge" ||
    var.db_allocated_storage_gib > 50 ||
    var.monthly_budget_usd > 750
  )

  service_dependency_edges = flatten([
    for source_name, source in local.raw_services : [
      for target_name, target in local.raw_services : {
        key    = "${source_name}--${target_name}"
        source = source_name
        target = target_name
        port   = target.port
        } if anytrue([
          for value in values(source.environment) :
          strcontains(value, "${target_name}.{{namespace}}")
      ])
    ]
  ])
  service_dependencies = {
    for edge in local.service_dependency_edges : edge.key => edge
  }

  # Seven pools x six connections x the HA steady autoscaling ceiling, plus
  # twenty reserved for migrations/operators. Both shapes replace tasks
  # stop-first, so this never assumes old and new copies simultaneously.
  db_connection_budget = length(local.databases) * 6 * local.deployment_copy_multiplier + 20

  has_domain            = var.app_domain_name != "" && var.route53_hosted_zone_id != ""
  create_certificate    = local.has_domain && var.manage_certificate && var.existing_certificate_arn == ""
  has_tls_configuration = var.existing_certificate_arn != "" || local.create_certificate
  effective_certificate_arn = var.existing_certificate_arn != "" ? var.existing_certificate_arn : (
    local.create_certificate ? aws_acm_certificate.app[0].arn : ""
  )
}

resource "terraform_data" "release_contract" {
  input = {
    image_release_id = local.image_manifest.releaseId
    approvals = merge(local.approval_complete, {
      github_environment_protection = local.github_environment_protection_complete
      public_legal                  = local.public_legal_contract_complete
      document_store_erasure        = local.document_store_erasure_approval_complete
    })
  }

  lifecycle {
    precondition {
      condition = !var.offline_validation || (
        startswith(abspath(path.root), "/tmp/jsc-public-beta-offline.") &&
        var.aws_account_id == "000000000000" &&
        var.ecs_ami_id == "ami-00000000000000000" &&
        (
          (var.application_desired_count == 0 && !var.public_entrypoint_enabled) ||
          (var.offline_activation_validation && var.application_desired_count == 1)
        )
      )
      error_message = "offline_validation is accepted only from the disposable backend-free /tmp harness with zero account/AMI sentinels; that harness may plan dark or the explicit one-task-per-service activation proof."
    }

    precondition {
      condition = var.offline_validation ? (
        var.foundation_data_kms_key_arn == "arn:aws:kms:eu-west-2:000000000000:key/00000000-0000-0000-0000-000000000000" &&
        var.foundation_operations_topic_arn == "arn:aws:sns:eu-west-2:000000000000:jsc-public-beta-operations" &&
        var.foundation_backup_plan_id == "00000000-0000-0000-0000-000000000000" &&
        var.foundation_erasure_journal_kms_key_arn == "arn:aws:kms:eu-west-2:000000000000:key/11111111-1111-1111-1111-111111111111" &&
        var.foundation_erasure_journal_bucket_name == "jsc-public-beta-erasure-journal-000000000000" &&
        var.foundation_approved_ecs_ami_id == "ami-00000000000000000" &&
        var.foundation_monthly_alert_budget_usd == 750 &&
        var.monthly_budget_usd == 750
        ) : (
        startswith(var.foundation_data_kms_key_arn, "arn:aws:kms:${var.aws_region}:${var.aws_account_id}:key/") &&
        var.foundation_operations_topic_arn == "arn:aws:sns:${var.aws_region}:${var.aws_account_id}:jsc-public-beta-operations" &&
        var.foundation_backup_plan_id != "00000000-0000-0000-0000-000000000000" &&
        startswith(var.foundation_erasure_journal_kms_key_arn, "arn:aws:kms:${var.aws_region}:${var.aws_account_id}:key/") &&
        var.foundation_erasure_journal_kms_key_arn != var.foundation_data_kms_key_arn &&
        var.foundation_erasure_journal_bucket_name == "jsc-public-beta-erasure-journal-${var.aws_account_id}" &&
        var.foundation_approved_ecs_ami_id == var.ecs_ami_id &&
        var.foundation_monthly_alert_budget_usd == var.monthly_budget_usd
      )
      error_message = "The normal stack requires exact retained data-key, operations-topic, backup-plan, alert-budget and isolated erasure-journal outputs from the reviewed manual bootstrap; offline validation accepts only zero-account sentinels."
    }

    precondition {
      condition     = alltrue(values(local.approval_complete))
      error_message = "Every enabled integration needs complete, current approval/quota/cost/attribution metadata. Credentials alone never constitute approval."
    }

    precondition {
      condition     = local.google_approval_complete
      error_message = "Google Maps also requires a true external billing-quota attestation, exact GCP project/quota IDs and daily limits, a bounded budget with 50/75/90/100 alerts, plus an owned emergency-disable runbook."
    }

    precondition {
      condition     = !var.enabled_integrations.postcodes_ni || var.enabled_integrations.postcodes_gb
      error_message = "Northern Ireland/BT postcode coverage cannot be enabled without the separately approved Great Britain postcode integration."
    }

    precondition {
      condition     = local.openai_approval_complete
      error_message = "OpenAI also requires the reviewed privacy policy, decision, owner and review date."
    }

    precondition {
      condition     = local.stripe_approval_complete
      error_message = "Stripe cannot be enabled until payment readiness is PASS and refund/reconciliation runbooks are referenced."
    }

    precondition {
      condition     = var.application_desired_count == 0 || local.payment_contract_complete
      error_message = "Starting Payment requires a reviewed legal trading identity, the reviewed GBP catalog, confirmed tax treatment, an exact immutable Client legal-artifact checksum/effective date, retention, disabled-or-authorised promotion, pinned Stripe API version and checkout/live switches matching the integration gate."
    }

    precondition {
      condition     = var.application_desired_count == 0 || local.public_legal_contract_complete
      error_message = "Starting the application requires one reviewed, published legal identity/version shared by Client, Authentication and Payment, explicit seller/tax/ICO status, exact HTTPS terms/privacy URLs, checksum-bound Client/Landing legal artifacts, and bounded retention/deletion periods."
    }

    precondition {
      condition     = var.application_desired_count == 0 || local.document_store_permanent_erasure_runtime_enabled
      error_message = "Starting the application requires the pinned Document Store permanent-erasure contract, exact 35-day backup policy, stable write fence/fingerprint secret, version-scoped S3 IAM and reviewed external deletion-journal/isolated-restore replay evidence."
    }

    precondition {
      condition     = !var.public_entrypoint_enabled || local.github_environment_protection_complete
      error_message = "Public activation requires substantive evidence that all three GitHub environments enforce the approved owner-only workflow actor fallback, exact-main deployment and disabled administrator bypass."
    }

    precondition {
      condition = (
        (!local.expanded_cost_shape && var.monthly_budget_usd <= 750) ||
        (
          local.expanded_cost_shape &&
          length(trimspace(var.expanded_capacity_approval_reference)) >= 8 &&
          !can(regex(local.release_placeholder_pattern, trimspace(var.expanded_capacity_approval_reference))) &&
          var.monthly_budget_usd > 750
        )
      )
      error_message = "The lean shape is bounded by the USD 750 alert ceiling. HA, a larger EC2 shape or initial RDS storage above 50 GiB needs a reviewed calculator/cost reference and an explicitly updated alert budget."
    }

    precondition {
      condition     = var.application_desired_count == 0 || var.application_base_url == "https://${var.app_domain_name}"
      error_message = "A runnable application requires application_base_url to exactly match the reviewed app_domain_name HTTPS origin."
    }

    precondition {
      condition = (
        var.existing_certificate_arn == "" ||
        can(regex("^arn:aws:acm:${var.aws_region}:${var.aws_account_id}:certificate/[0-9a-f-]{36}$", var.existing_certificate_arn))
      )
      error_message = "An existing certificate must be an ACM certificate in the exact reviewed account and eu-west-2 region."
    }

    precondition {
      condition     = var.application_desired_count == 0 || (local.images_release_ready && var.enabled_integrations.postcodes_gb)
      error_message = "Starting the application requires a scanned main-branch digest manifest, exact-image health-command/RDS CA/Document Store/payment-v2 attestations, the fail-closed NI/BT postcode gate, and approved Great Britain postcode lookup."
    }

    precondition {
      condition = (
        !var.public_entrypoint_enabled || (
          var.application_desired_count == 1 &&
          local.has_domain &&
          local.effective_certificate_arn != "" &&
          (
            (
              !var.offline_validation &&
              var.aws_account_id != "000000000000" &&
              var.ecs_ami_id != "ami-00000000000000000"
              ) || (
              var.offline_validation &&
              var.offline_activation_validation &&
              var.aws_account_id == "000000000000" &&
              var.ecs_ami_id == "ami-00000000000000000"
            )
          ) &&
          var.alarm_email != "" &&
          local.any_job_provider_enabled &&
          var.enabled_integrations.postcodes_gb &&
          var.enabled_integrations.openai &&
          var.enabled_integrations.stripe &&
          var.enabled_integrations.account_email
        )
      )
      error_message = "Public activation requires one healthy private fleet, DNS/TLS, real AMI, alarms, postcode/job/OpenAI/Stripe/account-email approvals and release images."
    }

    precondition {
      condition     = local.release_reserved_cpu + local.os_reserved_cpu <= local.instance_capacity[var.instance_type].cpu * local.node_count
      error_message = "Reserved fleet CPU plus ECS/OS/operator headroom exceeds the selected EC2 capacity."
    }

    precondition {
      condition     = local.release_reserved_memory + local.os_reserved_memory <= local.instance_capacity[var.instance_type].memory * local.node_count
      error_message = "Reserved fleet memory plus ECS/OS/operator headroom exceeds the selected EC2 capacity."
    }

    precondition {
      condition     = local.release_task_slots <= local.instance_capacity[var.instance_type].awsvpc_tasks_per_instance * local.node_count
      error_message = "Fleet ENI demand exceeds the awsvpcTrunking task limit with operator headroom."
    }

    precondition {
      condition     = local.db_connection_budget <= 120
      error_message = "Bounded Hikari pools plus migration/operator reserve exceed the db.t4g.medium beta connection budget."
    }
  }
}
