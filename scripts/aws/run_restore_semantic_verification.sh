#!/usr/bin/env bash
set -euo pipefail
umask 077

action=${1:-}
region=${AWS_REGION:-eu-west-2}
account_id=${AWS_ACCOUNT_ID:-}
drill_id=${RESTORE_DRILL_ID:-}
confirmation=${RESTORE_SEMANTIC_CONFIRMATION:-}
restore_start_evidence=${RESTORE_START_EVIDENCE:-}
semantic_start_evidence=${RESTORE_SEMANTIC_START_EVIDENCE:-}
output_directory=${RESTORE_SEMANTIC_OUTPUT_DIRECTORY:-}

cluster=jsc-public-beta
database="jsc-public-beta-restore-${drill_id}"
bucket="jsc-public-beta-restore-${account_id}-${drill_id}"
marker_name="/jsc/public-beta/restore-semantic/${drill_id}/start"
task_tag_managed_by=RestoreSemanticVerification
started_by="jsc-rs-$(printf '%s' "$drill_id" | sha256sum | cut -c1-20)"

fail() {
  echo "restore semantic verification refused: $1" >&2
  exit "${2:-2}"
}

case "$action" in start|observe|contain|cleanup) ;;
  *) fail "usage: $0 {start|observe|contain|cleanup}" ;;
esac
[[ "${GITHUB_REF:-}" == refs/heads/main ]] || fail "protected main is required"
[[ "$region" == eu-west-2 ]] || fail "region must be eu-west-2"
[[ "$account_id" =~ ^[0-9]{12}$ ]] || fail "AWS account ID is malformed"
[[ "$drill_id" =~ ^[a-z0-9]([a-z0-9-]{6,30})[a-z0-9]$ ]] || fail "drill ID is malformed"
for command_name in aws base64 jq python3 sha256sum; do
  command -v "$command_name" >/dev/null || fail "missing required command: $command_name"
done

temporary_files=()
cleanup_temporary_files() {
  if (( ${#temporary_files[@]} > 0 )); then rm -f -- "${temporary_files[@]}"; fi
}
trap cleanup_temporary_files EXIT HUP INT TERM
new_temporary_file() {
  local path
  path=$(mktemp /tmp/jsc-restore-semantic-orchestrator.XXXXXX)
  temporary_files+=("$path")
  printf '%s' "$path"
}

require_safe_file() {
  local path=$1 label=$2
  [[ -f "$path" && ! -L "$path" ]] || fail "$label is missing or unsafe"
}

exact_task_tags_json() {
  jq -cnS --arg drill "$drill_id" --arg managed "$task_tag_managed_by" '[
    {key:"Application",value:"Job Seeker Copilot"},
    {key:"Environment",value:"public-beta"},
    {key:"ManagedBy",value:$managed},
    {key:"RestoreDrillId",value:$drill}
  ]'
}

assert_exact_task_tags() {
  local task_arn=$1 tags
  tags=$(aws ecs list-tags-for-resource --region "$region" --resource-arn "$task_arn" --output json)
  jq -e --arg drill "$drill_id" --arg managed "$task_tag_managed_by" '
    (.tags | sort_by(.key)) == ([
      {key:"Application",value:"Job Seeker Copilot"},
      {key:"Environment",value:"public-beta"},
      {key:"ManagedBy",value:$managed},
      {key:"RestoreDrillId",value:$drill}
    ] | sort_by(.key))
  ' <<<"$tags" >/dev/null || fail "task $task_arn does not have the exact four drill tags" 3
}

contain_semantic_tasks() {
  local listing task tags family
  listing=$(aws ecs list-tasks --region "$region" --cluster "$cluster" --desired-status RUNNING --output json)
  while IFS= read -r task; do
    [[ -n "$task" ]] || continue
    tags=$(aws ecs list-tags-for-resource --region "$region" --resource-arn "$task" --output json)
    if jq -e --arg drill "$drill_id" --arg managed "$task_tag_managed_by" '
      (.tags | from_entries) as $tags |
      $tags.Application == "Job Seeker Copilot" and $tags.Environment == "public-beta" and
      $tags.ManagedBy == $managed and $tags.RestoreDrillId == $drill
    ' <<<"$tags" >/dev/null; then
      family=$(aws ecs describe-tasks --region "$region" --cluster "$cluster" --tasks "$task" \
        --query 'tasks[0].group' --output text)
      case "$family" in
        family:jsc-public-beta-restore-semantic-clone|\
        family:jsc-public-beta-restore-semantic-document-store|\
        family:jsc-public-beta-restore-semantic-verifier) ;;
        *) fail "tagged task has an out-of-scope family: $family" 3 ;;
      esac
      aws ecs stop-task --region "$region" --cluster "$cluster" --task "$task" \
        --reason "bounded restore semantic verification containment" >/dev/null
    fi
  done < <(jq -r '.taskArns[]?' <<<"$listing")
  listing=$(aws ecs list-tasks --region "$region" --cluster "$cluster" --desired-status RUNNING --output json)
  while IFS= read -r task; do
    [[ -n "$task" ]] || continue
    tags=$(aws ecs list-tags-for-resource --region "$region" --resource-arn "$task" --output json)
    jq -e --arg drill "$drill_id" --arg managed "$task_tag_managed_by" '
      (.tags | from_entries) as $tags |
      ($tags.Application != "Job Seeker Copilot" or $tags.Environment != "public-beta" or
       $tags.ManagedBy != $managed or $tags.RestoreDrillId != $drill)
    ' <<<"$tags" >/dev/null || fail "a semantic task remains running after containment" 3
  done < <(jq -r '.taskArns[]?' <<<"$listing")
}

if [[ "$action" == contain ]]; then
  [[ "$confirmation" == "CONTAIN RESTORE SEMANTIC VERIFICATION ${drill_id}" ]] || \
    fail "containment confirmation mismatch"
  contain_semantic_tasks
  echo "Restore semantic tasks for exact drill $drill_id are contained."
  exit 0
fi

if [[ "$action" == cleanup ]]; then
  [[ "$confirmation" == "DELETE ISOLATED RESTORE DRILL ${drill_id}" ]] || \
    fail "cleanup confirmation mismatch"
  contain_semantic_tasks
  if aws ssm get-parameter --region "$region" --name "$marker_name" >/dev/null 2>&1; then
    aws ssm list-tags-for-resource --region "$region" --resource-type Parameter \
      --resource-id "${marker_name#/}" --output json | jq -e \
      --arg drill "$drill_id" --arg managed "$task_tag_managed_by" '
        (.TagList | from_entries) == {
          Application:"Job Seeker Copilot",Environment:"public-beta",
          ManagedBy:$managed,RestoreDrillId:$drill
        }
      ' >/dev/null || fail "start marker ownership tags do not match this exact drill" 3
    aws ssm delete-parameter --region "$region" --name "$marker_name"
  fi
  echo "Restore semantic tasks and exact start marker are cleaned; retained Terraform SG rules were not mutated."
  exit 0
fi

require_safe_file "$restore_start_evidence" "restore-start evidence"
restore_start_sha=$(sha256sum "$restore_start_evidence" | cut -d' ' -f1)
jq -e --arg account "$account_id" --arg drill "$drill_id" --arg database "$database" --arg bucket "$bucket" '
  .schemaVersion == "jsc-public-beta-restore-request.v1" and .status == "RESTORES_STARTED" and
  .environment == "public-beta" and .drillId == $drill and
  .isolatedDestinations == {rds:$database,s3:$bucket} and
  (.restoreJobIds.rds | test("^[A-Za-z0-9-]{8,128}$")) and
  (.restoreJobIds.s3 | test("^[A-Za-z0-9-]{8,128}$")) and
  (.releaseCandidate.releaseId | test("^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")) and
  (.releaseCandidate.buildRunId | test("^[0-9]+$")) and
  (.releaseCandidate.infrastructureRevision | test("^[0-9a-f]{40}$")) and
  (.releaseCandidate.releaseAttestationId | test("^[0-9a-f]{64}$")) and
  (.releaseCandidate.documentStoreRevision | test("^[0-9a-f]{40}$")) and
  (.releaseCandidate.documentStoreImageDigest | test("^sha256:[0-9a-f]{64}$")) and
  (.releaseCandidate.releaseOperatorImageDigest | test("^sha256:[0-9a-f]{64}$")) and
  .restoreSource.logicalDatabaseCount == 7 and .restoreSource.documentObjectVersionCount == 2 and
  (.restoreSource.canaryId | test("^[a-z0-9][a-z0-9-]{6,30}[a-z0-9]$")) and
  (.restoreSource.markerSha256 | test("^[0-9a-f]{64}$")) and
  .restoreSource.evidenceSha256 == .restoreSourceEvidenceSha256 and
  (.restoreRoleArn | test("^arn:aws:iam::"+$account+":role/jsc-public-beta-backup-restore$"))
' "$restore_start_evidence" >/dev/null || fail "restore-start evidence is not the exact semantic-verification source" 3

release_id=$(jq -er '.releaseCandidate.releaseId' "$restore_start_evidence")
release_attestation_id=$(jq -er '.releaseCandidate.releaseAttestationId' "$restore_start_evidence")
infrastructure_revision=$(jq -er '.releaseCandidate.infrastructureRevision' "$restore_start_evidence")
document_revision=$(jq -er '.releaseCandidate.documentStoreRevision' "$restore_start_evidence")
document_digest=$(jq -er '.releaseCandidate.documentStoreImageDigest' "$restore_start_evidence")
operator_digest=$(jq -er '.releaseCandidate.releaseOperatorImageDigest' "$restore_start_evidence")
source_canary=$(jq -er '.restoreSource.canaryId' "$restore_start_evidence")
source_marker_sha=$(jq -er '.restoreSource.markerSha256' "$restore_start_evidence")
source_evidence_sha=$(jq -er '.restoreSource.evidenceSha256' "$restore_start_evidence")
rds_restore_job=$(jq -er '.restoreJobIds.rds' "$restore_start_evidence")
s3_restore_job=$(jq -er '.restoreJobIds.s3' "$restore_start_evidence")

seed=$(printf '%s:%s:%s' "$drill_id" "$release_id" "$source_marker_sha" | sha256sum | cut -d' ' -f1)
replay_seed=$(printf 'replay:%s:%s:%s' "$drill_id" "$release_id" "$source_marker_sha" | sha256sum | cut -d' ' -f1)
operation_id="7e57c0de-${seed:0:4}-4${seed:4:3}-8${seed:7:3}-${seed:10:12}"
restore_replay_id="${replay_seed:0:8}-${replay_seed:8:4}-4${replay_seed:12:3}-8${replay_seed:15:3}-${replay_seed:18:12}"
replay_database="restore_replay_$(tr -d '-' <<<"$operation_id" | cut -c1-12)"

assert_public_dark() {
  local load_balancer listener_arn listeners rules service_arns service_arn service_name status
  load_balancer=$(aws elbv2 describe-load-balancers --region "$region" --names jsc-public-beta-app --output json)
  jq -e '.LoadBalancers | length == 1 and .[0].Scheme == "internet-facing" and .[0].State.Code == "active"' \
    <<<"$load_balancer" >/dev/null || fail "public ALB binding is unexpected" 3
  listener_arn=$(aws elbv2 describe-listeners --region "$region" \
    --load-balancer-arn "$(jq -er '.LoadBalancers[0].LoadBalancerArn' <<<"$load_balancer")" --output json | jq -er '
      [.Listeners[] | select(.Port == 443 and .Protocol == "HTTPS" and
        (.DefaultActions | length) == 1 and .DefaultActions[0].Type == "fixed-response" and
        .DefaultActions[0].FixedResponseConfig.StatusCode == "503")] |
      if length == 1 then .[0].ListenerArn else error("HTTPS fixed-503 listener mismatch") end
    ')
  rules=$(aws elbv2 describe-rules --region "$region" --listener-arn "$listener_arn" --output json)
  jq -e '(.Rules | length) == 1 and .Rules[0].IsDefault == true and
    (.Rules[0].Actions | length) == 1 and .Rules[0].Actions[0].Type == "fixed-response" and
    .Rules[0].Actions[0].FixedResponseConfig.StatusCode == "503"' <<<"$rules" >/dev/null || \
    fail "public HTTPS listener has a forwarding rule" 3
  service_arns=$(aws ecs list-services --region "$region" --cluster "$cluster" --output json)
  while IFS= read -r service_arn; do
    [[ -n "$service_arn" ]] || continue
    service_name=${service_arn##*/}
    status=$(aws ecs describe-services --region "$region" --cluster "$cluster" --services "$service_name" --output json)
    jq -e '(.failures | length) == 0 and (.services | length) == 1 and
      .services[0].desiredCount == 0 and .services[0].runningCount == 0 and .services[0].pendingCount == 0' \
      <<<"$status" >/dev/null || fail "public application service is not quiesced: $service_name" 3
  done < <(jq -r '.serviceArns[]?' <<<"$service_arns")
}

discover_and_verify_network() {
  local vpcs groups subnets prefix_lists rules semantic_eni_count
  vpcs=$(aws ec2 describe-vpcs --region "$region" --filters Name=tag:Name,Values=jsc-public-beta-vpc --output json)
  vpc_id=$(jq -er '.Vpcs | if length == 1 and .[0].State == "available" and .[0].CidrBlock == "10.42.0.0/16" and .[0].IsDefault == false then .[0].VpcId else error("VPC mismatch") end' <<<"$vpcs")
  groups=$(aws ec2 describe-security-groups --region "$region" --filters Name=vpc-id,Values="$vpc_id" \
    Name=tag:ManagedBy,Values=Terraform Name=tag:Environment,Values=public-beta --output json)
  restore_database_sg=$(jq -er '.SecurityGroups | map(select(.Tags | from_entries | .Purpose == "RestoreDatabase")) | if length == 1 then .[0].GroupId else error("restore DB SG mismatch") end' <<<"$groups")
  semantic_sg=$(jq -er '.SecurityGroups | map(select(.Tags | from_entries | .Purpose == "RestoreSemanticVerifier")) | if length == 1 then .[0].GroupId else error("semantic SG mismatch") end' <<<"$groups")
  [[ "$restore_database_sg" != "$semantic_sg" ]] || fail "restore security groups are not distinct" 3
  subnets=$(aws ec2 describe-subnets --region "$region" --filters Name=vpc-id,Values="$vpc_id" \
    Name=tag:Tier,Values=private Name=tag:Network,Values=ecs --output json)
  jq -e '.Subnets | length == 2 and all(.[]; .MapPublicIpOnLaunch == false and .State == "available") and
    ([.[].AvailabilityZone] | unique | length) == 2' <<<"$subnets" >/dev/null || fail "private task subnet set mismatch" 3
  mapfile -t private_subnets < <(jq -r '.Subnets | sort_by(.AvailabilityZone) | .[].SubnetId' <<<"$subnets")
  prefix_lists=$(aws ec2 describe-prefix-lists --region "$region" --filters \
    Name=prefix-list-name,Values="com.amazonaws.${region}.s3" --output json)
  s3_prefix_list=$(jq -er '.PrefixLists | if length == 1 then .[0].PrefixListId else error("S3 prefix-list mismatch") end' <<<"$prefix_lists")
  rules=$(aws ec2 describe-security-group-rules --region "$region" --filters \
    Name=group-id,Values="$restore_database_sg,$semantic_sg" --output json)
  jq -e --arg db "$restore_database_sg" --arg semantic "$semantic_sg" --arg s3 "$s3_prefix_list" '
    [.SecurityGroupRules[] | {
      group:.GroupId,egress:.IsEgress,protocol:.IpProtocol,from:(.FromPort // null),to:(.ToPort // null),
      referenced:(.ReferencedGroupInfo.GroupId // null),cidr:(.CidrIpv4 // null),prefix:(.PrefixListId // null)
    }] | sort_by(.group,.egress,.protocol,.from,.to,.referenced,.cidr,.prefix) == ([
      {group:$db,egress:false,protocol:"tcp",from:5432,to:5432,referenced:$semantic,cidr:null,prefix:null},
      {group:$semantic,egress:false,protocol:"tcp",from:8089,to:8089,referenced:$semantic,cidr:null,prefix:null},
      {group:$semantic,egress:true,protocol:"tcp",from:53,to:53,referenced:null,cidr:"10.42.0.2/32",prefix:null},
      {group:$semantic,egress:true,protocol:"tcp",from:443,to:443,referenced:null,cidr:null,prefix:$s3},
      {group:$semantic,egress:true,protocol:"tcp",from:5432,to:5432,referenced:$db,cidr:null,prefix:null},
      {group:$semantic,egress:true,protocol:"tcp",from:8089,to:8089,referenced:$semantic,cidr:null,prefix:null},
      {group:$semantic,egress:true,protocol:"udp",from:53,to:53,referenced:null,cidr:"10.42.0.2/32",prefix:null}
    ] | sort_by(.group,.egress,.protocol,.from,.to,.referenced,.cidr,.prefix))
  ' <<<"$rules" >/dev/null || fail "Terraform-owned restore semantic SG allowlist is not exact" 3
  semantic_eni_count=$(aws ec2 describe-network-interfaces --region "$region" \
    --filters Name=group-id,Values="$semantic_sg" --output json | jq -er '.NetworkInterfaces | length')
  [[ "$semantic_eni_count" == 0 ]] || fail "semantic SG already has an attached ENI before approval" 3
}

