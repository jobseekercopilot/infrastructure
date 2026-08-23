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
  [[ "$(aws s3api get-bucket-location --region "$region" --bucket "$bucket" --query 'LocationConstraint' --output text)" == "$region" ]]
  [[ "$(aws s3api get-bucket-versioning --region "$region" --bucket "$bucket" --query 'Status' --output text)" == "Enabled" ]]
  [[ "$(aws s3api get-bucket-ownership-controls --region "$region" --bucket "$bucket" --query 'OwnershipControls.Rules[0].ObjectOwnership' --output text)" == "BucketOwnerEnforced" ]]
  aws s3api get-public-access-block --region "$region" --bucket "$bucket" --output json | jq -e '
    .PublicAccessBlockConfiguration |
    .BlockPublicAcls == true and .IgnorePublicAcls == true and
    .BlockPublicPolicy == true and .RestrictPublicBuckets == true
  ' >/dev/null
  aws s3api get-bucket-encryption --region "$region" --bucket "$bucket" --output json | jq -e \
    --arg key "$data_kms_key_arn" '
      .ServerSideEncryptionConfiguration.Rules | length == 1 and
      .[0].BucketKeyEnabled == true and
      .[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm == "aws:kms" and
      .[0].ApplyServerSideEncryptionByDefault.KMSMasterKeyID == $key
    ' >/dev/null
  [[ "$(aws s3api get-bucket-policy-status --region "$region" --bucket "$bucket" --query 'PolicyStatus.IsPublic' --output text)" == "False" ]]
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
  for path in "$image_manifest" "$provenance"; do
    [[ -f "$path" && ! -L "$path" ]] || { echo "Missing or unsafe restore candidate artifact: $path" >&2; exit 2; }
  done
  [[ -n "$output_directory" && ! -L "$output_directory" ]] || { echo "Unsafe restore output directory." >&2; exit 2; }
  mkdir -p -- "$output_directory"

  vault=jsc-public-beta-customer-data
  for pair in "RDS:$rds_recovery_point" "S3:$s3_recovery_point"; do
    expected_type=${pair%%:*}
    recovery_point=${pair#*:}
    aws backup describe-recovery-point \
      --region "$region" \
      --backup-vault-name "$vault" \
      --recovery-point-arn "$recovery_point" \
      --output json | jq -e --arg type "$expected_type" '
        .Status == "COMPLETED" and .ResourceType == $type and
        .CompletionDate != null and .CreationDate != null
      ' >/dev/null
    aws backup list-tags --region "$region" --resource-arn "$recovery_point" --output json | jq -e '
      .Tags.Application == "Job Seeker Copilot" and
      .Tags.Environment == "public-beta" and
      .Tags.RestoreTest == "quarterly"
    ' >/dev/null
  done

  aws s3api create-bucket \
    --region "$region" \
    --bucket "$bucket" \
    --create-bucket-configuration "LocationConstraint=$region" >/dev/null
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
  verify_bucket_controls

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
    --created-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --output-directory "$output_directory"

  rds_result=$(aws backup start-restore-job --region "$region" --cli-input-json "file://$output_directory/rds-restore-request.json" --output json)
  s3_result=$(aws backup start-restore-job --region "$region" --cli-input-json "file://$output_directory/s3-restore-request.json" --output json)
  rds_job=$(jq -er '.RestoreJobId | select(test("^[A-Za-z0-9-]{8,128}$"))' <<<"$rds_result")
  s3_job=$(jq -er '.RestoreJobId | select(test("^[A-Za-z0-9-]{8,128}$"))' <<<"$s3_result")
  jq --arg rds "$rds_job" --arg s3 "$s3_job" \
    '.status="RESTORES_STARTED" | .restoreJobIds={rds:$rds,s3:$s3}' \
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
  for pair in "RDS:$rds_restore_job_id" "S3:$s3_restore_job_id"; do
    expected_type=${pair%%:*}
    job_id=${pair#*:}
    aws backup describe-restore-job --region "$region" --restore-job-id "$job_id" --output json | jq -e --arg type "$expected_type" '
      .Status == "COMPLETED" and .ResourceType == $type and
      .CreatedResourceArn != null and .CompletionDate != null
    ' >/dev/null
  done
  aws rds describe-db-instances --region "$region" --db-instance-identifier "$database" --output json | jq -e \
    --arg sg "$restore_security_group" '
      .DBInstances | length == 1 and
      .[0].PubliclyAccessible == false and .[0].DBSubnetGroup.DBSubnetGroupName == "jsc-public-beta-postgres" and
      ([.[0].VpcSecurityGroups[].VpcSecurityGroupId] == [$sg])
    ' >/dev/null
  verify_bucket_controls
  echo "Restore control plane verified; application replay and semantic checks remain required."
  exit 0
fi

[[ "$confirmation" == "DELETE ISOLATED RESTORE DRILL ${drill_id}" ]] || {
  echo "Restore cleanup confirmation mismatch." >&2
  exit 2
}
if aws rds describe-db-instances --region "$region" --db-instance-identifier "$database" >/dev/null 2>&1; then
  aws rds delete-db-instance --region "$region" --db-instance-identifier "$database" --skip-final-snapshot --delete-automated-backups >/dev/null
  aws rds wait db-instance-deleted --region "$region" --db-instance-identifier "$database"
fi
if aws s3api head-bucket --region "$region" --bucket "$bucket" >/dev/null 2>&1; then
  aws s3api get-bucket-tagging --region "$region" --bucket "$bucket" --output json | jq -e \
    --arg drill "$drill_id" '
      (.TagSet | from_entries) as $tags |
      $tags.ManagedBy == "RestoreDrill" and $tags.RestoreDrillId == $drill
    ' >/dev/null || {
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
  aws s3api delete-bucket-policy --region "$region" --bucket "$bucket" 2>/dev/null || true
  aws s3api delete-bucket --region "$region" --bucket "$bucket"
fi
echo "Isolated restore drill resources deleted after separate cleanup approval."
