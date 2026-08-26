#!/usr/bin/env bash
set -euo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
module="$repository_root/aws/public-beta"

case "${GITHUB_REF:-}" in
  refs/heads/main|refs/tags/*)
    echo "Refusing account-free validation on protected main or a release tag." >&2
    exit 2
    ;;
esac
for credential_name in \
  AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE \
  AWS_DEFAULT_PROFILE AWS_WEB_IDENTITY_TOKEN_FILE \
  AWS_CONTAINER_CREDENTIALS_FULL_URI AWS_CONTAINER_CREDENTIALS_RELATIVE_URI \
  AWS_ENDPOINT_URL; do
  [[ -z "${!credential_name:-}" ]] || {
    echo "Refusing account-free validation while $credential_name is set." >&2
    exit 2
  }
done
while IFS='=' read -r environment_name _; do
  case "$environment_name" in
    AWS_ENDPOINT_URL_*)
      echo "Refusing account-free validation while $environment_name is set." >&2
      exit 2
      ;;
  esac
done < <(env)

validation_root=$(mktemp -d /tmp/jsc-public-beta-offline.XXXXXX)

cleanup() {
  case "$validation_root" in /tmp/jsc-public-beta-offline.*) rm -rf "$validation_root" ;; esac
}
trap cleanup EXIT HUP INT TERM

for source in "$module"/*.tf; do
  [[ "$(basename "$source")" == "backend.tf" ]] && continue
  cp "$source" "$validation_root/"
done
[[ ! -e "$validation_root/backend.tf" ]] || {
  echo "Disposable account-free module unexpectedly contains a backend." >&2
  exit 2
}
cp -R "$module/config" "$validation_root/config"
cp "$module/.terraform.lock.hcl" "$validation_root/.terraform.lock.hcl"

init_plugin_arguments=()
installed_provider_root="$module/.terraform/providers"
installed_provider_binary="$installed_provider_root/registry.terraform.io/hashicorp/aws/6.55.0/linux_amd64/terraform-provider-aws_v6.55.0_x5"
if [[ -x "$installed_provider_binary" ]]; then
  # Reuse the checksum-locked local provider for a genuinely network-free
  # developer recheck. CI may omit it and let Terraform resolve from its own
  # reviewed cache/registry path; neither mode calls an AWS API.
  init_plugin_arguments+=("-plugin-dir=$installed_provider_root")
fi
terraform -chdir="$validation_root" init -backend=false -input=false -lockfile=readonly "${init_plugin_arguments[@]}"
terraform -chdir="$validation_root" validate

approval_sha=$(sha256sum "$validation_root/config/launch-approvals.json" | cut -d' ' -f1)
release_ready_manifest="$validation_root/release-ready-manifest.json"
pending_frontend_manifest="$validation_root/pending-frontend-manifest.json"
image_digest="sha256:$(printf '1%.0s' {1..64})"
source_revision=$(printf '2%.0s' {1..40})
generated_static_sha=$(printf '3%.0s' {1..64})
generated_runtime_sha=$(printf '4%.0s' {1..64})
generated_sam_sha=$(printf '5%.0s' {1..64})
document_store_revision=$(printf '8%.0s' {1..40})
document_store_openapi_sha=$(printf '9%.0s' {1..64})
document_store_runbook_sha=$(sha256sum "$repository_root/docs/aws-public-beta/document-store-permanent-erasure.md" | cut -d' ' -f1)
jq \
  --arg approvalSha "$approval_sha" \
  --arg imageDigest "$image_digest" \
  --arg sourceRevision "$source_revision" \
  --arg staticSha "$generated_static_sha" \
  --arg runtimeSha "$generated_runtime_sha" \
  --arg samSha "$generated_sam_sha" \
  --arg documentStoreRevision "$document_store_revision" \
  --arg documentStoreOpenapiSha "$document_store_openapi_sha" \
  --arg documentStoreRunbookSha "$document_store_runbook_sha" \
  '.releaseId="20260815T000000Z-222222222222"
   | .createdAt="2026-08-15T00:00:00Z"
   | .sourceBranch="main"
   | .launchApprovalManifestSha256=$approvalSha
   | .capabilities |= with_entries(.value=true)
   | .dependencyEvidence.documentStorePermanentErasure.revision=$documentStoreRevision
   | .dependencyEvidence.documentStorePermanentErasure.openApiSha256=$documentStoreOpenapiSha
   | .dependencyEvidence.documentStorePermanentErasure.restoreReplayRunbookSha256=$documentStoreRunbookSha
   | .images |= with_entries(
       .value.digest=$imageDigest
       | .value.scanStatus="PASSED"
       | .value.revision=(
           if .key == "clamav" then "1.4.5"
           elif .key == "job-seeker-copilot-client" then "5f4aca3aa6528a883506a8a5dc31566187c5e3ae"
           else $sourceRevision
           end
         )
     )
   | .dependencyEvidence.frontendArtifacts.landing.staticArtifactSha256=$staticSha
   | .dependencyEvidence.frontendArtifacts.landing.runtimeConfigSha256=$runtimeSha
   | .dependencyEvidence.frontendArtifacts.landing.selectedSamTemplateSha256=$samSha' \
  "$validation_root/config/image-manifest.json" > "$release_ready_manifest"
jq \
  '.dependencyEvidence.frontendArtifacts.landing.staticArtifactSha256="PENDING"
   | .dependencyEvidence.frontendArtifacts.landing.runtimeConfigSha256="PENDING"
   | .dependencyEvidence.frontendArtifacts.landing.selectedSamTemplateSha256="PENDING"' \
  "$release_ready_manifest" > "$pending_frontend_manifest"

readiness_value() {
  local manifest=$1
  printf 'local.images_release_ready\n' | terraform -chdir="$validation_root" console \
    -no-color \
    -var=offline_validation=true \
    -var="image_manifest_path=$manifest" | tail -n 1
}

[[ "$(readiness_value "$pending_frontend_manifest")" == "false" ]] || {
  echo "PENDING Landing hashes incorrectly satisfy release readiness." >&2
  exit 1
}
echo "PENDING Landing hashes correctly block release readiness."
[[ "$(readiness_value "$release_ready_manifest")" == "true" ]] || {
  echo "Exact generated Landing hashes did not satisfy release readiness." >&2
  exit 1
}
echo "Exact generated Landing hashes satisfy release readiness."

# Build a non-secret, synthetic but fully substantive approval solely to prove
# the one-task-per-service topology. It is created inside the disposable /tmp
# module, never checked in, signed, uploaded or used against AWS state.
positive_approval_manifest="$validation_root/positive-approval-manifest.json"
positive_image_manifest="$validation_root/positive-image-manifest.json"
exception_approval_manifest="$validation_root/exception-approval-manifest.json"
exception_image_manifest="$validation_root/exception-image-manifest.json"
positive_tfvars="$validation_root/positive.tfvars.json"
review_date=$(date -u +%Y-%m-%d)
review_due_date=$(date -u -d "$review_date + 90 days" +%Y-%m-%d)
reviewed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
exception_expires_at=$(date -u -d "$reviewed_at + 7 days" +%Y-%m-%dT%H:%M:%SZ)
legal_version="uk-public-beta-$review_date"
client_legal_sha=$(printf '6%.0s' {1..64})
landing_legal_sha=$(printf '7%.0s' {1..64})
restore_evidence_sha=$(printf 'a%.0s' {1..64})
jq \
  --arg reviewedAt "$reviewed_at" \
  --arg reviewDate "$review_date" \
  --arg reviewDueDate "$review_due_date" \
  --arg legalVersion "$legal_version" \
  --arg clientLegalSha "$client_legal_sha" \
  --arg landingLegalSha "$landing_legal_sha" \
  --arg restoreEvidenceSha "$restore_evidence_sha" \
  '.reviewedAt=$reviewedAt
   | .githubEnvironmentProtection += {
       reviewed:true,
       reviewedBy:"Account-free release validator",
       reviewedOn:$reviewDate,
       evidenceReference:"offline-activation/github-environment-settings-evidence",
       operatorUsername:"jobseekercopilot",
       paidEnvironmentReviewerProtectionAvailable:false,
       ownerOnlyWorkflowActorVerified:true,
       soloOperatorSelfApprovalAuthorised:true,
       exactMainBranchVerified:true,
       administratorBypassDisabled:true
     }
   | .documentStorePermanentErasure += {
       reviewed:true,
       reviewedBy:"Account-free release validator",
       reviewedOn:$reviewDate,
       evidenceReference:"offline-activation/document-erasure-review-record",
       retentionPolicyVersion:"document-retention-2026-08-15",
       backupRetentionPolicyVersion:"aws-backup-35-days-2026-08-15",
       journalRetentionPolicyVersion:"immutable-erasure-journal-2026-08-15",
       maximumBackupRetentionDays:35,
       journalRetentionDays:90,
       externalDeletionJournalVerified:true,
       isolatedRestoreReplayVerified:true,
       restoreDrillEvidenceSha256:$restoreEvidenceSha
     }
   | .publicLegal += {
       reviewed:true,
       reviewedBy:"Account-free release validator",
       evidenceReference:"offline-activation/legal-review-record",
       legalVersion:$legalVersion,
       effectiveOn:$reviewDate,
       legalEntityType:"SOLE_TRADER",
       taxStatus:"NOT_VAT_REGISTERED",
       legalEntityName:"Account Free Validation Owner",
       tradingName:"Job Seeker Copilot",
       businessAddress:"Reviewed United Kingdom validation address",
       privacyEmail:"privacy@jobseekercopilot.com",
       supportEmail:"support@jobseekercopilot.com",
       icoRegistrationStatus:"NOT_REQUIRED_CONFIRMED",
       icoRegistrationReference:"",
       accountDeletionCompletionDays:35,
       documentDeletionCompletionDays:35,
       securityLogRetentionDays:30,
       supportRecordRetentionDays:365,
       financialRecordRetentionYears:7,
       termsUrl:"https://app.jobseekercopilot.com/terms",
       privacyNoticeUrl:"https://app.jobseekercopilot.com/privacy",
       clientLegalArtifactSha256:$clientLegalSha,
       landingLegalArtifactSha256:$landingLegalSha
     }
   | .integrations.postcodes_gb += {
       approved:true,
       approvalReference:"offline-activation/postcodes-gb-approval",
       approvedBy:"Account-free release validator",
       termsReviewedOn:$reviewDate,
       expiresOn:"2099-12-31",
       monthlyRequestLimit:1000,
       monthlyCostCeilingGbp:0
     }
   | .integrations.nhs_jobs += {
       approved:true,
       approvalReference:"offline-activation/nhs-jobs-approval",
       approvedBy:"Account-free release validator",
       termsReviewedOn:$reviewDate,
       expiresOn:"2099-12-31",
       monthlyRequestLimit:1000,
       monthlyCostCeilingGbp:0
     }
   | .integrations.openai += {
       approved:true,
       approvalReference:"offline-activation/openai-approval",
       approvedBy:"Account-free release validator",
       termsReviewedOn:$reviewDate,
       expiresOn:"2099-12-31",
       monthlyRequestLimit:1000,
       monthlyCostCeilingGbp:50,
       privacyPolicyVersion:"openai-api-data-controls-2026-08-23",
       privacyDecisionId:"offline-activation/openai-privacy-decision",
       privacyOwner:"Account-free release validator",
       privacyReviewedOn:$reviewDate,
       privacyReviewDueOn:$reviewDueDate
     }
   | .integrations.account_email += {
       approved:true,
       approvalReference:"offline-activation/ses-approval",
       approvedBy:"Account-free release validator",
       termsReviewedOn:$reviewDate,
       expiresOn:"2099-12-31",
       monthlyRequestLimit:1000,
       monthlyCostCeilingGbp:10
     }
   | .integrations.stripe += {
       approved:true,
       approvalReference:"offline-activation/stripe-approval",
       approvedBy:"Account-free release validator",
       termsReviewedOn:$reviewDate,
       expiresOn:"2099-12-31",
       monthlyRequestLimit:1000,
       monthlyCostCeilingGbp:100,
       paymentReadinessStatus:"PASS",
       refundRunbookReference:"offline-activation/refund-runbook",
       reconciliationRunbookReference:"offline-activation/reconciliation-runbook",
       checkoutEnabled:true,
       checkoutReleaseAuthorised:true,
       providerLiveModeExpected:true,
       stripeLiveReleaseAuthorised:true,
       stripeApiVersion:"2026-02-25.clover",
       legalEntityType:"SOLE_TRADER",
       legalEntityConfigurationVersion:$legalVersion,
       legalEntityReviewed:true,
       legalEntityEvidenceReference:"offline-activation/reviewed-seller-record",
       merchantTermsTraderDisclosureVerified:true,
       taxTreatment:"VAT_NOT_CHARGED",
       taxStatus:"NOT_VAT_REGISTERED",
       catalogVersion:"public-beta-2026-08-22",
       liveStripeCatalog:[
         {id:"starter",productId:"prod_offlineStarter",priceId:"price_offlineStarter499"},
         {id:"active",productId:"prod_offlineActive",priceId:"price_offlineActive1199"},
         {id:"power",productId:"prod_offlinePower",priceId:"price_offlinePower1999"}
       ],
       consumerTermsVersion:$legalVersion,
       consumerTermsEffectiveOn:$reviewDate,
       consumerTermsUrl:"https://app.jobseekercopilot.com/terms",
       consumerTermsContentSha256:$clientLegalSha,
       financialRecordRetentionYears:7
     }' \
  "$validation_root/config/launch-approvals.json" > "$positive_approval_manifest"
positive_approval_sha=$(sha256sum "$positive_approval_manifest" | cut -d' ' -f1)
jq --arg approvalSha "$positive_approval_sha" \
  '.launchApprovalManifestSha256=$approvalSha' \
  "$release_ready_manifest" > "$positive_image_manifest"
jq \
  --arg approvedAt "$reviewed_at" \
  --arg expiresAt "$exception_expires_at" \
  '.documentStorePermanentErasure.isolatedRestoreReplayVerified=false
   | .documentStorePermanentErasure.restoreDrillEvidenceSha256=""
   | .documentStorePermanentErasure.initialPublicBetaRecoveryException={
       approved:true,
       id:"offline-initial-beta-recovery-exception",
       approvedBy:"Account-free release validator",
       approvedAt:$approvedAt,
       expiresAt:$expiresAt,
       trackingReference:"https://github.com/jobseekercopilot/infrastructure/issues/153",
       justification:"Exercise the exact bounded initial public-beta recovery exception topology.",
       compensatingControl:"Encrypted versioned storage, backups, one-task scaling and emergency darkening remain enabled.",
       maximumApplicationDesiredCount:1
     }' \
  "$positive_approval_manifest" > "$exception_approval_manifest"
exception_approval_sha=$(sha256sum "$exception_approval_manifest" | cut -d' ' -f1)
jq --arg approvalSha "$exception_approval_sha" \
  '.launchApprovalManifestSha256=$approvalSha' \
  "$release_ready_manifest" > "$exception_image_manifest"
jq -n '{enabled_integrations:{
  postcodes_gb:true,
  postcodes_ni:false,
  reed:false,
  adzuna:false,
  jsearch:false,
  nhs_jobs:true,
  apprenticeships:false,
  google_maps:false,
  openai:true,
  stripe:true,
  account_email:true
},
app_domain_name:"app.jobseekercopilot.com",
route53_hosted_zone_id:"Z00000000000000000000",
manage_certificate:false,
existing_certificate_arn:"arn:aws:acm:eu-west-2:000000000000:certificate/00000000-0000-0000-0000-000000000000",
alarm_email:"operations@jobseekercopilot.com"}' > "$positive_tfvars"

plan_log="$validation_root/plan.log"
AWS_ACCESS_KEY_ID=offline-validation \
AWS_SECRET_ACCESS_KEY=offline-validation \
AWS_REGION=eu-west-2 \
AWS_EC2_METADATA_DISABLED=true \
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  terraform -chdir="$validation_root" plan \
    -no-color \
    -compact-warnings \
    -refresh=false \
    -input=false \
    -lock=false \
    -var=offline_validation=true \
    -var=app_domain_name=app.jobseekercopilot.com \
    -var=route53_hosted_zone_id=Z00000000000000000000 \
    -var=manage_certificate=false \
    -var=existing_certificate_arn=arn:aws:acm:eu-west-2:000000000000:certificate/00000000-0000-0000-0000-000000000000 \
    -out="$validation_root/public-beta.tfplan" >"$plan_log" 2>&1 || {
      cat "$plan_log" >&2
      exit 1
    }

plan_summary=$(sed -n '/^Plan: /p' "$plan_log" | tail -n 1)
[[ -n "$plan_summary" ]] || { cat "$plan_log" >&2; echo "Offline plan did not produce a resource summary." >&2; exit 1; }
terraform -chdir="$validation_root" show -json "$validation_root/public-beta.tfplan" \
  > "$validation_root/public-beta.tfplan.json"
python3 "$repository_root/scripts/aws/verify_offline_activation_plan.py" \
  --mode dark \
  "$validation_root/public-beta.tfplan.json" \
  "$validation_root/config/runtime-services.json"
echo "$plan_summary"
echo "Account-free dark topology plan passed; no AWS state, AWS calls or live credentials were used."

pending_activation_log="$validation_root/pending-activation.log"
if AWS_ACCESS_KEY_ID=offline-validation \
  AWS_SECRET_ACCESS_KEY=offline-validation \
  AWS_REGION=eu-west-2 \
  AWS_EC2_METADATA_DISABLED=true \
  AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  terraform -chdir="$validation_root" plan \
    -no-color \
    -compact-warnings \
    -refresh=false \
    -input=false \
    -lock=false \
    -var=offline_validation=true \
    -var=offline_activation_validation=true \
    -var=application_desired_count=1 \
    -var=public_entrypoint_enabled=true \
    -var-file="$positive_tfvars" >"$pending_activation_log" 2>&1; then
  echo "Checked-in PENDING approvals/images incorrectly produced an activation plan." >&2
  exit 1
fi
grep -Eq 'Every enabled integration|Starting the application requires|Starting Payment requires|permanent-erasure|release images' "$pending_activation_log" || {
  cat "$pending_activation_log" >&2
  echo "Checked-in activation failed for an unexpected reason." >&2
  exit 1
}
echo "Checked-in PENDING approvals/images correctly block the public activation topology."

positive_plan_log="$validation_root/positive-plan.log"
AWS_ACCESS_KEY_ID=offline-validation \
AWS_SECRET_ACCESS_KEY=offline-validation \
AWS_REGION=eu-west-2 \
AWS_EC2_METADATA_DISABLED=true \
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  terraform -chdir="$validation_root" plan \
    -no-color \
    -compact-warnings \
    -refresh=false \
    -input=false \
    -lock=false \
    -var=offline_validation=true \
    -var=offline_activation_validation=true \
    -var=application_desired_count=1 \
    -var=public_entrypoint_enabled=true \
    -var="image_manifest_path=$positive_image_manifest" \
    -var="approval_manifest_path=$positive_approval_manifest" \
    -var-file="$positive_tfvars" \
    -out="$validation_root/public-beta-positive.tfplan" >"$positive_plan_log" 2>&1 || {
      cat "$positive_plan_log" >&2
      exit 1
    }
positive_plan_summary=$(sed -n '/^Plan: /p' "$positive_plan_log" | tail -n 1)
[[ -n "$positive_plan_summary" ]] || {
  cat "$positive_plan_log" >&2
  echo "Offline fully approved activation plan did not produce a resource summary." >&2
  exit 1
}
terraform -chdir="$validation_root" show -json "$validation_root/public-beta-positive.tfplan" \
  > "$validation_root/public-beta-positive.tfplan.json"
python3 "$repository_root/scripts/aws/verify_offline_activation_plan.py" \
  "$validation_root/public-beta-positive.tfplan.json" \
  "$validation_root/config/runtime-services.json"
echo "$positive_plan_summary"
echo "Account-free fully approved activation topology passed with desired_count=1 and public_entrypoint=true; no backend, AWS state, AWS calls or live credentials were used."

exception_plan_log="$validation_root/exception-plan.log"
AWS_ACCESS_KEY_ID=offline-validation \
AWS_SECRET_ACCESS_KEY=offline-validation \
AWS_REGION=eu-west-2 \
AWS_EC2_METADATA_DISABLED=true \
AWS_ENDPOINT_URL=http://127.0.0.1:9 \
  terraform -chdir="$validation_root" plan \
    -no-color \
    -compact-warnings \
    -refresh=false \
    -input=false \
    -lock=false \
    -var=offline_validation=true \
    -var=offline_activation_validation=true \
    -var=application_desired_count=1 \
    -var=public_entrypoint_enabled=true \
    -var="image_manifest_path=$exception_image_manifest" \
    -var="approval_manifest_path=$exception_approval_manifest" \
    -var-file="$positive_tfvars" \
    -out="$validation_root/public-beta-exception.tfplan" >"$exception_plan_log" 2>&1 || {
      cat "$exception_plan_log" >&2
      exit 1
    }
exception_plan_summary=$(sed -n '/^Plan: /p' "$exception_plan_log" | tail -n 1)
[[ -n "$exception_plan_summary" ]] || {
  cat "$exception_plan_log" >&2
  echo "Offline initial-beta recovery-exception plan did not produce a resource summary." >&2
  exit 1
}
terraform -chdir="$validation_root" show -json "$validation_root/public-beta-exception.tfplan" \
  > "$validation_root/public-beta-exception.tfplan.json"
python3 "$repository_root/scripts/aws/verify_offline_activation_plan.py" \
  "$validation_root/public-beta-exception.tfplan.json" \
  "$validation_root/config/runtime-services.json"
echo "$exception_plan_summary"
echo "Account-free seven-day initial-beta recovery-exception topology passed with desired_count=1 and public_entrypoint=true; no backend, AWS state, AWS calls or live credentials were used."
