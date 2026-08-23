#!/usr/bin/env bash
set -euo pipefail
umask 077

action=${1:-}
region=${AWS_REGION:-eu-west-2}
account_id=${AWS_ACCOUNT_ID:-}
drill_id=${RESTORE_DRILL_ID:-}
confirmation=${RESTORE_DRILL_CONFIRMATION:-}
output_directory=${RESTORE_DRILL_OUTPUT_DIRECTORY:-}
rds_recovery_point=${RDS_RECOVERY_POINT_ARN:-}
s3_recovery_point=${S3_RECOVERY_POINT_ARN:-}
restore_security_group=${RESTORE_SECURITY_GROUP_ID:-}
restore_role_arn=${AWS_BACKUP_RESTORE_ROLE_ARN:-}
data_kms_key_arn=${AWS_DATA_KMS_KEY_ARN:-}
image_manifest=${IMAGE_MANIFEST:-}
provenance=${PROVENANCE:-}
restore_source_evidence=${RESTORE_SOURCE_EVIDENCE:-}
restore_start_evidence=${RESTORE_START_EVIDENCE:-}
candidate_build_run_id=${CANDIDATE_BUILD_RUN_ID:-}
rds_restore_job_id=${RDS_RESTORE_JOB_ID:-}
s3_restore_job_id=${S3_RESTORE_JOB_ID:-}

case "$action" in start|observe|cleanup) ;;
  *) echo "Usage: $0 {start|observe|cleanup}" >&2; exit 2 ;;
esac
[[ "${GITHUB_REF:-}" == "refs/heads/main" ]] || {
  echo "Restore drill refused outside protected main." >&2
  exit 2
}
[[ "$region" == "eu-west-2" ]] || { echo "Restore drill is restricted to eu-west-2." >&2; exit 2; }
[[ "$account_id" =~ ^[0-9]{12}$ ]] || { echo "Invalid AWS account ID." >&2; exit 2; }
[[ "$drill_id" =~ ^[a-z0-9]([a-z0-9-]{6,30})[a-z0-9]$ ]] || { echo "Invalid restore drill ID." >&2; exit 2; }

for command_name in aws jq python3 sha256sum; do
  command -v "$command_name" >/dev/null || { echo "Missing required command: $command_name" >&2; exit 2; }
done

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
bucket="jsc-public-beta-restore-${account_id}-${drill_id}"
database="jsc-public-beta-restore-${drill_id}"
expected_restore_role="arn:aws:iam::${account_id}:role/jsc-public-beta-backup-restore"
[[ "$restore_role_arn" == "$expected_restore_role" ]] || {
  echo "Restore drill requires the exact boundary-constrained AWS Backup role." >&2
  exit 2
}

temporary_files=()
cleanup_temporary_files() {
  if (( ${#temporary_files[@]} > 0 )); then
    rm -f -- "${temporary_files[@]}"
  fi
}
trap cleanup_temporary_files EXIT HUP INT TERM

verify_bucket_controls() {
  local live_policy
  [[ "$(aws s3api get-bucket-location --region "$region" --bucket "$bucket" --query 'LocationConstraint' --output text)" == "$region" ]] || return 1
  [[ "$(aws s3api get-bucket-versioning --region "$region" --bucket "$bucket" --query 'Status' --output text)" == "Enabled" ]] || return 1
  [[ "$(aws s3api get-bucket-ownership-controls --region "$region" --bucket "$bucket" --query 'OwnershipControls.Rules[0].ObjectOwnership' --output text)" == "BucketOwnerEnforced" ]] || return 1
  aws s3api get-public-access-block --region "$region" --bucket "$bucket" --output json | jq -e '
    .PublicAccessBlockConfiguration |
    .BlockPublicAcls == true and .IgnorePublicAcls == true and
    .BlockPublicPolicy == true and .RestrictPublicBuckets == true
  ' >/dev/null || return 1
  aws s3api get-bucket-encryption --region "$region" --bucket "$bucket" --output json | jq -e \
    --arg key "$data_kms_key_arn" '
      .ServerSideEncryptionConfiguration.Rules | length == 1 and
      .[0].BucketKeyEnabled == true and
      .[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm == "aws:kms" and
      .[0].ApplyServerSideEncryptionByDefault.KMSMasterKeyID == $key
    ' >/dev/null || return 1
  live_policy=$(aws s3api get-bucket-policy \
    --region "$region" --bucket "$bucket" --query Policy --output text) || return 1
  printf '%s' "$live_policy" | jq -e --arg bucket "$bucket" --arg key "$data_kms_key_arn" '
    .Version == "2012-10-17" and
    ([.Statement[].Sid] | sort) == ["DenyInsecureTransport","DenyWrongRestoreKmsKey","DenyWrongRestoreObjectEncryption"] and
    any(.Statement[];
      .Sid == "DenyInsecureTransport" and .Effect == "Deny" and .Principal == "*" and .Action == "s3:*" and
      .Resource == ["arn:aws:s3:::"+$bucket,"arn:aws:s3:::"+$bucket+"/*"] and
      .Condition == {Bool:{"aws:SecureTransport":"false"}}
    ) and
    any(.Statement[];
      .Sid == "DenyWrongRestoreObjectEncryption" and .Effect == "Deny" and .Principal == "*" and
      .Action == "s3:PutObject" and .Resource == "arn:aws:s3:::"+$bucket+"/*" and
      .Condition == {StringNotEquals:{"s3:x-amz-server-side-encryption":"aws:kms"}}
    ) and
    any(.Statement[];
      .Sid == "DenyWrongRestoreKmsKey" and .Effect == "Deny" and .Principal == "*" and
      .Action == "s3:PutObject" and .Resource == "arn:aws:s3:::"+$bucket+"/*" and
      .Condition == {StringNotEquals:{"s3:x-amz-server-side-encryption-aws-kms-key-id":$key}}
    )
  ' >/dev/null || return 1
  [[ "$(aws s3api get-bucket-policy-status --region "$region" --bucket "$bucket" --query 'PolicyStatus.IsPublic' --output text)" == "False" ]] || return 1
}

verify_restore_bucket_tags() {
  aws s3api get-bucket-tagging --region "$region" --bucket "$bucket" --output json | jq -e \
    --arg drill "$drill_id" '
      (.TagSet | from_entries) as $tags |
      ($tags | with_entries(select(.key | startswith("aws:") | not)) | keys | sort) ==
        ["Application","CostCentre","Environment","ManagedBy","RestoreDrillId"] and
      $tags.Application == "Job Seeker Copilot" and
      $tags.Environment == "public-beta" and
      $tags.ManagedBy == "RestoreDrill" and
      $tags.RestoreDrillId == $drill and
      $tags.CostCentre == "public-beta"
    ' >/dev/null
}

verify_restore_database_tags() {
  local resource_arn=$1
  aws rds list-tags-for-resource --region "$region" --resource-name "$resource_arn" --output json | jq -e \
    --arg drill "$drill_id" '
      (.TagList | from_entries) as $tags |
      ($tags | with_entries(select(.key | startswith("aws:") | not)) | keys | sort) ==
        ["Application","CostCentre","Environment","ManagedBy","RestoreDrillId"] and
      $tags.Application == "Job Seeker Copilot" and
      $tags.Environment == "public-beta" and
      $tags.ManagedBy == "RestoreDrill" and
      $tags.RestoreDrillId == $drill and
      $tags.CostCentre == "public-beta" and
      ($tags.Name // null) == null
    ' >/dev/null
}

normalise_restore_database_tags() {
  local resource_arn=$1
  local current key
  local -a unexpected=()

  # Establish exact drill ownership before the narrowly conditioned removal
  # grant can strip the known production-only tags copied by RDS restore.
  aws rds add-tags-to-resource --region "$region" --resource-name "$resource_arn" --tags \
    Key=Application,Value="Job Seeker Copilot" \
    Key=Environment,Value=public-beta \
    Key=ManagedBy,Value=RestoreDrill \
    Key=RestoreDrillId,Value="$drill_id" \
    Key=CostCentre,Value=public-beta
  current=$(aws rds list-tags-for-resource --region "$region" --resource-name "$resource_arn" --output json)
  mapfile -t unexpected < <(jq -r '
    .TagList[]? |
    select(.Key | startswith("aws:") | not) |
    select(.Key as $key | ["Application","CostCentre","Environment","ManagedBy","RestoreDrillId"] | index($key) | not) |
    .Key
  ' <<<"$current")
  (( ${#unexpected[@]} <= 50 )) || {
    echo "Restore database has an unbounded copied tag set." >&2
    exit 3
  }
  for key in "${unexpected[@]}"; do
    [[ "$key" =~ ^[A-Za-z0-9_.:/=+@\ -]{1,128}$ ]] || {
      echo "Restore database has a malformed copied tag key." >&2
      exit 3
    }
    case "$key" in
      Name|Repository|DataClass|Backup|BetaBlocker) ;;
      *)
        echo "Restore database has an unexpected copied tag outside the reviewed removal allowlist: $key" >&2
        exit 3
        ;;
    esac
  done
  if (( ${#unexpected[@]} > 0 )); then
    aws rds remove-tags-from-resource \
      --region "$region" --resource-name "$resource_arn" --tag-keys "${unexpected[@]}"
  fi
  verify_restore_database_tags "$resource_arn"
}

tag_restored_database_when_created() {
  local job_id=$1
  local recovery_point=$2
  local expected_resource="arn:aws:rds:${region}:${account_id}:db:${database}"
  local timeout=${RESTORE_DATABASE_TAG_TIMEOUT_SECONDS:-3600}
  [[ "$timeout" =~ ^[0-9]+$ ]] && (( timeout >= 60 && timeout <= 3600 )) || {
    echo "Restore database tag timeout must be 60-3600 seconds." >&2
    exit 2
  }
  local deadline=$(( $(date +%s) + timeout ))
  local observed state created
  while (( $(date +%s) < deadline )); do
    observed=$(aws backup describe-restore-job \
      --region "$region" --restore-job-id "$job_id" --output json)
    jq -e \
      --arg account "$account_id" --arg job "$job_id" --arg recovery "$recovery_point" \
      --arg role "$restore_role_arn" '
        .AccountId == $account and .RestoreJobId == $job and
        .RecoveryPointArn == $recovery and .IamRoleArn == $role and .ResourceType == "RDS"
      ' <<<"$observed" >/dev/null || {
      echo "Restore database job escaped the exact account/source/role binding." >&2
      exit 3
    }
    state=$(jq -er '.Status' <<<"$observed")
    created=$(jq -r '.CreatedResourceArn // ""' <<<"$observed")
    if [[ -n "$created" ]]; then
      [[ "$created" == "$expected_resource" ]] || {
        echo "Restore database job created an unexpected resource: $created" >&2
        exit 3
      }
      normalise_restore_database_tags "$created"
      echo "Restored database is cost- and ownership-tagged for exact drill $drill_id."
      return 0
    fi
    case "$state" in
      PENDING|RUNNING) ;;
      ABORTED|FAILED|PARTIAL)
        echo "Restore database job reached terminal state $state before its destination could be tagged." >&2
        exit 3
        ;;
      COMPLETED)
        echo "Restore database job completed without an exact created-resource ARN." >&2
        exit 3
        ;;
      *) echo "Restore database job returned unexpected state: $state" >&2; exit 3 ;;
    esac
    sleep 20
  done
  echo "Timed out waiting to tag the restored database. Rerun exact start inputs to resume the idempotent jobs before observation." >&2
  exit 3
}

if [[ "$action" == "start" ]]; then
  [[ "$confirmation" == "START ISOLATED RESTORE DRILL ${drill_id}" ]] || {
    echo "Restore start confirmation mismatch." >&2
    exit 2
  }
  [[ "$restore_security_group" =~ ^sg-[0-9a-f]{8,17}$ ]] || { echo "Invalid isolated security group ID." >&2; exit 2; }
  [[ "$data_kms_key_arn" =~ ^arn:aws:kms:eu-west-2:${account_id}:key/[0-9a-f-]{36}$ ]] || {
    echo "Invalid foundation data KMS key ARN." >&2
    exit 2
  }
  for path in "$image_manifest" "$provenance" "$restore_source_evidence"; do
    [[ -f "$path" && ! -L "$path" ]] || { echo "Missing or unsafe restore candidate artifact: $path" >&2; exit 2; }
  done
  [[ "$candidate_build_run_id" =~ ^[0-9]+$ ]] || { echo "Missing candidate build run binding." >&2; exit 2; }
  [[ -n "$output_directory" && ! -L "$output_directory" ]] || { echo "Unsafe restore output directory." >&2; exit 2; }
  mkdir -p -- "$output_directory"

  python3 "$repository_root/scripts/aws/validate_restore_source_evidence.py" \
    --evidence "$restore_source_evidence" --image-manifest "$image_manifest" --provenance "$provenance" \
    --candidate-build-run-id "$candidate_build_run_id" \
    --expected-rds-recovery-point "$rds_recovery_point" \
    --expected-s3-recovery-point "$s3_recovery_point"
  source_canary=$(jq -er '.sourceCanary.marker.canaryId' "$restore_source_evidence")
  source_marker_sha=$(jq -er '.sourceCanary.markerSha256' "$restore_source_evidence")
  source_evidence_sha=$(sha256sum "$restore_source_evidence" | cut -d' ' -f1)

  vault=jsc-public-beta-customer-data
  for pair in "RDS:$rds_recovery_point" "S3:$s3_recovery_point"; do
    expected_type=${pair%%:*}
    recovery_point=${pair#*:}
    if [[ "$expected_type" == RDS ]]; then
      expected_source="arn:aws:rds:${region}:${account_id}:db:jsc-public-beta-postgres"
    else
      expected_source="arn:aws:s3:::jsc-public-beta-documents-${account_id}"
    fi
    aws backup describe-recovery-point \
      --region "$region" \
      --backup-vault-name "$vault" \
      --recovery-point-arn "$recovery_point" \
      --output json | jq -e --arg type "$expected_type" --arg recovery "$recovery_point" \
      --arg source "$expected_source" --arg vault "arn:aws:backup:${region}:${account_id}:backup-vault:jsc-public-beta-customer-data" '
        .RecoveryPointArn == $recovery and .ResourceArn == $source and .BackupVaultArn == $vault and
        .Status == "COMPLETED" and .ResourceType == $type and
        .CompletionDate != null and .CreationDate != null and
        .Lifecycle.DeleteAfterDays == 35
      ' >/dev/null
    aws backup list-tags --region "$region" --resource-arn "$recovery_point" --output json | jq -e \
      --arg release "$(jq -er '.releaseId' "$image_manifest")" \
      --arg canary "$source_canary" --arg marker "$source_marker_sha" '
      .Tags.Application == "Job Seeker Copilot" and
      .Tags.Environment == "public-beta" and
      .Tags.RestoreTest == "quarterly" and
      .Tags.ReleaseId == $release and
      .Tags.RestoreSourceCanary == $canary and
      .Tags.RestoreSourceMarker == $marker
    ' >/dev/null
  done

  if aws s3api head-bucket --region "$region" --bucket "$bucket" >/dev/null 2>&1; then
    # A partial retry may reuse only the exact fully hardened, workflow-owned
    # destination. Never adopt or repair a foreign/ambiguous existing bucket.
    verify_restore_bucket_tags || {
      echo "Restore start refused: the existing destination bucket is not owned by this exact drill." >&2
      exit 3
    }
    verify_bucket_controls || {
      echo "Restore start refused: the existing drill bucket no longer has the exact reviewed controls." >&2
      exit 3
    }
  else
    aws s3api create-bucket \
      --region "$region" \
      --bucket "$bucket" \
      --create-bucket-configuration "LocationConstraint=$region" >/dev/null
    # Tag first so any later setup failure is safely selectable by the separate
    # exact-drill cleanup role rather than becoming an ambiguous orphan.
    aws s3api put-bucket-tagging --region "$region" --bucket "$bucket" --tagging "TagSet=[{Key=Application,Value=Job Seeker Copilot},{Key=Environment,Value=public-beta},{Key=ManagedBy,Value=RestoreDrill},{Key=RestoreDrillId,Value=$drill_id},{Key=CostCentre,Value=public-beta}]"
    aws s3api put-public-access-block --region "$region" --bucket "$bucket" --public-access-block-configuration 'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'
    aws s3api put-bucket-ownership-controls --region "$region" --bucket "$bucket" --ownership-controls 'Rules=[{ObjectOwnership=BucketOwnerEnforced}]'
    aws s3api put-bucket-versioning --region "$region" --bucket "$bucket" --versioning-configuration 'Status=Enabled'
    aws s3api put-bucket-encryption --region "$region" --bucket "$bucket" --server-side-encryption-configuration "Rules=[{ApplyServerSideEncryptionByDefault={SSEAlgorithm=aws:kms,KMSMasterKeyID=$data_kms_key_arn},BucketKeyEnabled=true}]"

    bucket_policy=$(mktemp /tmp/jsc-restore-bucket-policy.XXXXXX.json)
    temporary_files+=("$bucket_policy")
    jq -n --arg bucket "$bucket" --arg key "$data_kms_key_arn" '{
      Version:"2012-10-17",
      Statement:[
        {Sid:"DenyInsecureTransport",Effect:"Deny",Principal:"*",Action:"s3:*",
         Resource:["arn:aws:s3:::"+$bucket,"arn:aws:s3:::"+$bucket+"/*"],
         Condition:{Bool:{"aws:SecureTransport":"false"}}},
        {Sid:"DenyWrongRestoreObjectEncryption",Effect:"Deny",Principal:"*",Action:"s3:PutObject",
         Resource:"arn:aws:s3:::"+$bucket+"/*",
         Condition:{StringNotEquals:{"s3:x-amz-server-side-encryption":"aws:kms"}}},
        {Sid:"DenyWrongRestoreKmsKey",Effect:"Deny",Principal:"*",Action:"s3:PutObject",
         Resource:"arn:aws:s3:::"+$bucket+"/*",
         Condition:{StringNotEquals:{"s3:x-amz-server-side-encryption-aws-kms-key-id":$key}}}
      ]
    }' > "$bucket_policy"
    aws s3api put-bucket-policy --region "$region" --bucket "$bucket" --policy "file://$bucket_policy"
    verify_restore_bucket_tags
    verify_bucket_controls
  fi

  rds_restore_metadata="$output_directory/rds-recovery-point-restore-metadata.json"
  [[ ! -e "$rds_restore_metadata" ]] || {
    echo "Refusing to overwrite RDS recovery-point metadata evidence." >&2
    exit 2
  }
  aws backup get-recovery-point-restore-metadata \
    --region "$region" \
    --backup-vault-name "$vault" \
    --recovery-point-arn "$rds_recovery_point" \
    --output json > "$rds_restore_metadata"
  chmod 0600 "$rds_restore_metadata"

  python3 "$repository_root/scripts/aws/render_backup_restore_requests.py" \
    --account-id "$account_id" \
    --region "$region" \
    --drill-id "$drill_id" \
    --rds-recovery-point-arn "$rds_recovery_point" \
    --s3-recovery-point-arn "$s3_recovery_point" \
    --restore-role-arn "$restore_role_arn" \
    --data-kms-key-arn "$data_kms_key_arn" \
    --restore-security-group-id "$restore_security_group" \
    --rds-restore-metadata "$rds_restore_metadata" \
    --image-manifest "$image_manifest" \
    --provenance "$provenance" \
    --restore-source-evidence "$restore_source_evidence" \
    --created-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --output-directory "$output_directory"

  rds_result=$(aws backup start-restore-job --region "$region" --cli-input-json "file://$output_directory/rds-restore-request.json" --output json)
  s3_result=$(aws backup start-restore-job --region "$region" --cli-input-json "file://$output_directory/s3-restore-request.json" --output json)
  rds_job=$(jq -er '.RestoreJobId | select(test("^[A-Za-z0-9-]{8,128}$"))' <<<"$rds_result")
  s3_job=$(jq -er '.RestoreJobId | select(test("^[A-Za-z0-9-]{8,128}$"))' <<<"$s3_result")
  tag_restored_database_when_created "$rds_job" "$rds_recovery_point"
  jq --arg rds "$rds_job" --arg s3 "$s3_job" \
    --arg sourceEvidenceSha256 "$source_evidence_sha" \
    --arg restoreRoleArn "$restore_role_arn" \
    '.status="RESTORES_STARTED" | .restoreJobIds={rds:$rds,s3:$s3} |
      .restoreSourceEvidenceSha256=$sourceEvidenceSha256 | .restoreRoleArn=$restoreRoleArn' \
    "$output_directory/restore-request-evidence.json" > "$output_directory/restore-start-evidence.json"
  chmod 0600 "$output_directory/restore-start-evidence.json"
  echo "Isolated restore jobs started: RDS=$rds_job S3=$s3_job"
  exit 0
fi

if [[ "$action" == "observe" ]]; then
  [[ "$confirmation" == "OBSERVE ISOLATED RESTORE DRILL ${drill_id}" ]] || {
    echo "Restore observation confirmation mismatch." >&2
    exit 2
  }
  [[ "$rds_restore_job_id" =~ ^[A-Za-z0-9-]{8,128}$ && "$s3_restore_job_id" =~ ^[A-Za-z0-9-]{8,128}$ ]] || {
    echo "Restore job IDs are malformed." >&2
    exit 2
  }
  [[ -f "$restore_start_evidence" && ! -L "$restore_start_evidence" ]] || {
    echo "Observe requires the immutable exact restore-start evidence artifact." >&2
    exit 2
  }
  jq -e \
    --arg account "$account_id" --arg drill "$drill_id" \
    --arg rds_job "$rds_restore_job_id" --arg s3_job "$s3_restore_job_id" \
    --arg role "$restore_role_arn" --arg database "$database" --arg bucket "$bucket" '
      .schemaVersion == "jsc-public-beta-restore-request.v1" and .status == "RESTORES_STARTED" and
      .environment == "public-beta" and .drillId == $drill and
      .restoreJobIds == {rds:$rds_job,s3:$s3_job} and .restoreRoleArn == $role and
      .isolatedDestinations == {rds:$database,s3:$bucket} and
      .restoreSourceEvidenceSha256 == .restoreSource.evidenceSha256 and
      (.restoreSource.markerSha256 | test("^[0-9a-f]{64}$")) and
      (.restoreSource.canaryId | test("^[a-z0-9][a-z0-9-]{6,30}[a-z0-9]$")) and
      (.sourceRecoveryPoints.rds | test("^arn:aws:rds:eu-west-2:"+$account+":snapshot:awsbackup:job-[A-Za-z0-9-]+$")) and
      (.sourceRecoveryPoints.s3 | test("^arn:aws:backup:eu-west-2:"+$account+":recovery-point:[A-Za-z0-9-]+$"))
    ' "$restore_start_evidence" >/dev/null || {
    echo "Restore-start evidence does not bind this exact drill, jobs, sources, role and destinations." >&2
    exit 3
  }
  rds_recovery_point=$(jq -er '.sourceRecoveryPoints.rds' "$restore_start_evidence")
  s3_recovery_point=$(jq -er '.sourceRecoveryPoints.s3' "$restore_start_evidence")
  source_release=$(jq -er '.releaseCandidate.releaseId' "$restore_start_evidence")
  source_canary=$(jq -er '.restoreSource.canaryId' "$restore_start_evidence")
  source_marker_sha=$(jq -er '.restoreSource.markerSha256' "$restore_start_evidence")
  vault_arn="arn:aws:backup:${region}:${account_id}:backup-vault:jsc-public-beta-customer-data"
  for pair in "RDS:$rds_restore_job_id" "S3:$s3_restore_job_id"; do
    expected_type=${pair%%:*}
    job_id=${pair#*:}
    if [[ "$expected_type" == RDS ]]; then
      recovery_point=$rds_recovery_point
      expected_source="arn:aws:rds:${region}:${account_id}:db:jsc-public-beta-postgres"
      expected_destination="arn:aws:rds:${region}:${account_id}:db:${database}"
    else
      recovery_point=$s3_recovery_point
      expected_source="arn:aws:s3:::jsc-public-beta-documents-${account_id}"
      expected_destination="arn:aws:s3:::${bucket}"
    fi
    aws backup describe-recovery-point \
      --region "$region" --backup-vault-name jsc-public-beta-customer-data \
      --recovery-point-arn "$recovery_point" --output json | jq -e \
      --arg type "$expected_type" --arg recovery "$recovery_point" --arg source "$expected_source" --arg vault "$vault_arn" '
        .RecoveryPointArn == $recovery and .BackupVaultArn == $vault and .ResourceArn == $source and
        .Status == "COMPLETED" and .ResourceType == $type and .Lifecycle.DeleteAfterDays == 35
      ' >/dev/null || {
      echo "$expected_type recovery point no longer matches the exact source/vault/lifecycle binding." >&2
      exit 3
    }
    aws backup list-tags --region "$region" --resource-arn "$recovery_point" --output json | jq -e \
      --arg release "$source_release" --arg canary "$source_canary" --arg marker "$source_marker_sha" '
        .Tags.Application == "Job Seeker Copilot" and .Tags.Environment == "public-beta" and
        .Tags.RestoreTest == "quarterly" and .Tags.ReleaseId == $release and
        .Tags.RestoreSourceCanary == $canary and .Tags.RestoreSourceMarker == $marker
      ' >/dev/null || {
      echo "$expected_type recovery point lost its exact source-canary tags." >&2
      exit 3
    }
    aws backup describe-restore-job --region "$region" --restore-job-id "$job_id" --output json | jq -e \
      --arg account "$account_id" --arg job "$job_id" --arg type "$expected_type" \
      --arg recovery "$recovery_point" --arg destination "$expected_destination" --arg role "$restore_role_arn" '
        .AccountId == $account and .RestoreJobId == $job and
        .Status == "COMPLETED" and .ResourceType == $type and
        .RecoveryPointArn == $recovery and .CreatedResourceArn == $destination and
        .IamRoleArn == $role and .CompletionDate != null
      ' >/dev/null || {
      echo "$expected_type restore job does not bind the exact source, role, account and destination." >&2
      exit 3
    }
  done
  aws rds describe-db-instances --region "$region" --db-instance-identifier "$database" --output json | jq -e \
    --arg sg "$restore_security_group" '
      .DBInstances | length == 1 and
      .[0].PubliclyAccessible == false and .[0].DBSubnetGroup.DBSubnetGroupName == "jsc-public-beta-postgres" and
      ([.[0].VpcSecurityGroups[].VpcSecurityGroupId] == [$sg])
  ' >/dev/null
  restored_database_arn="arn:aws:rds:${region}:${account_id}:db:${database}"
  normalise_restore_database_tags "$restored_database_arn"
  verify_restore_bucket_tags
  verify_bucket_controls
  echo "Restore control plane verified; application replay and semantic checks remain required."
  exit 0
fi

[[ "$confirmation" == "DELETE ISOLATED RESTORE DRILL ${drill_id}" ]] || {
  echo "Restore cleanup confirmation mismatch." >&2
  exit 2
}
if aws rds describe-db-instances --region "$region" --db-instance-identifier "$database" >/dev/null 2>&1; then
  restored_database_arn="arn:aws:rds:${region}:${account_id}:db:${database}"
  verify_restore_database_tags "$restored_database_arn" || {
    echo "Refusing cleanup: restored database ownership tags do not match the exact drill." >&2
    exit 3
  }
  aws rds delete-db-instance --region "$region" --db-instance-identifier "$database" --skip-final-snapshot --delete-automated-backups >/dev/null
  aws rds wait db-instance-deleted --region "$region" --db-instance-identifier "$database"
fi
if aws s3api head-bucket --region "$region" --bucket "$bucket" >/dev/null 2>&1; then
  verify_restore_bucket_tags || {
    echo "Refusing cleanup: restore bucket ownership tags do not match the exact drill." >&2
    exit 3
  }
  while true; do
    # Delete one service page at a time so each DeleteObjects request remains
    # within S3's exact 1,000-object API limit. Deleting the first page makes
    # the next loop safely continue from the new first page.
    versions=$(aws s3api list-object-versions --region "$region" --bucket "$bucket" --max-keys 1000 --no-paginate --output json)
    deletion_batch=$(jq -c '{Objects:([.Versions[]? | {Key,VersionId}] + [.DeleteMarkers[]? | {Key,VersionId}]),Quiet:true}' <<<"$versions")
    [[ "$(jq '.Objects | length' <<<"$deletion_batch")" -gt 0 ]] || break
    aws s3api delete-objects --region "$region" --bucket "$bucket" --delete "$deletion_batch" >/dev/null
  done
  aws s3api delete-bucket-policy --region "$region" --bucket "$bucket"
  aws s3api delete-bucket --region "$region" --bucket "$bucket"
fi
echo "Isolated restore drill resources deleted after separate cleanup approval."
