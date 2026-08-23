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
data_kms_key_arn=${AWS_DATA_KMS_KEY_ARN:-}
repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

cluster=jsc-public-beta
cluster_arn="arn:aws:ecs:${region}:${account_id}:cluster/${cluster}"
state_machine_name=jsc-public-beta-restore-semantic
state_machine_arn="arn:aws:states:${region}:${account_id}:stateMachine:${state_machine_name}"
state_machine_role="arn:aws:iam::${account_id}:role/jsc-public-beta-restore-semantic-state-machine"
marker_name="/jsc/public-beta/restore-semantic/${drill_id}/start"
database="jsc-public-beta-restore-${drill_id}"
bucket="jsc-public-beta-restore-${account_id}-${drill_id}"
raw_prefix=JSC_RESTORE_SEMANTIC_RAW_EVIDENCE_B64=

fail() { echo "restore semantic verification refused: $1" >&2; exit "${2:-2}"; }
case "$action" in start|observe|contain|cleanup) ;; *) fail "usage: $0 {start|observe|contain|cleanup}" ;; esac
[[ "${GITHUB_REF:-}" == refs/heads/main ]] || fail "protected main is required"
[[ "$region" == eu-west-2 ]] || fail "region must be eu-west-2"
[[ "$account_id" =~ ^[0-9]{12}$ ]] || fail "AWS account ID is malformed"
[[ "$drill_id" =~ ^[a-z0-9]([a-z0-9-]{6,30})[a-z0-9]$ ]] || fail "drill ID is malformed"
for command_name in aws base64 date jq ln mktemp python3 sed sha256sum sleep sort wc; do command -v "$command_name" >/dev/null || fail "missing command: $command_name"; done
started_by="jsc-rs-$(printf '%s' "$drill_id" | sha256sum | cut -c1-20)"

temporary_files=()
cleanup_temporary_files() { if (( ${#temporary_files[@]} )); then rm -f -- "${temporary_files[@]}"; fi; }
trap cleanup_temporary_files EXIT HUP INT TERM
new_temporary_file() {
  local target_variable=$1 path
  path=$(mktemp /tmp/jsc-restore-semantic-observer.XXXXXX)
  temporary_files+=("$path")
  printf -v "$target_variable" '%s' "$path"
}
require_safe_file() { [[ -f "$1" && ! -L "$1" ]] || fail "$2 is missing or unsafe"; }
require_new_output() {
  [[ -n "$output_directory" && -d "$output_directory" && ! -L "$output_directory" ]] || fail "safe output directory is required"
  [[ ! -e "$1" && ! -L "$1" ]] || fail "refusing to overwrite evidence: $1"
}

require_safe_file "$restore_start_evidence" "restore-start evidence"
restore_start_sha=$(sha256sum "$restore_start_evidence" | cut -d' ' -f1)
jq -e --arg account "$account_id" --arg drill "$drill_id" --arg database "$database" --arg bucket "$bucket" '
  .schemaVersion == "jsc-public-beta-restore-request.v1" and .status == "RESTORES_STARTED" and
  .environment == "public-beta" and .drillId == $drill and .isolatedDestinations == {rds:$database,s3:$bucket} and
  (.restoreJobIds.rds|test("^[A-Za-z0-9-]{8,128}$")) and (.restoreJobIds.s3|test("^[A-Za-z0-9-]{8,128}$")) and
  (.sourceRecoveryPoints.rds|test("^arn:aws:rds:eu-west-2:"+$account+":snapshot:awsbackup:job-[A-Za-z0-9-]+$")) and
  (.sourceRecoveryPoints.s3|test("^arn:aws:backup:eu-west-2:"+$account+":recovery-point:[A-Za-z0-9-]+$")) and
  (.releaseCandidate.releaseId|test("^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")) and
  (.releaseCandidate.releaseAttestationId|test("^[0-9a-f]{64}$")) and
  (.releaseCandidate.documentStoreImageDigest|test("^sha256:[0-9a-f]{64}$")) and
  (.releaseCandidate.releaseOperatorImageDigest|test("^sha256:[0-9a-f]{64}$")) and
  .restoreSource.logicalDatabaseCount == 7 and .restoreSource.documentObjectVersionCount == 2 and
  (.restoreSource.canaryId|test("^[a-z0-9][a-z0-9-]{6,30}[a-z0-9]$")) and
  (.restoreSource.markerSha256|test("^[0-9a-f]{64}$")) and
  .restoreSource.evidenceSha256 == .restoreSourceEvidenceSha256 and
  .restoreRoleArn == ("arn:aws:iam::"+$account+":role/jsc-public-beta-backup-restore")
' "$restore_start_evidence" >/dev/null || fail "restore-start evidence is not the exact semantic source" 3

release_id=$(jq -er '.releaseCandidate.releaseId' "$restore_start_evidence")
release_attestation_id=$(jq -er '.releaseCandidate.releaseAttestationId' "$restore_start_evidence")
document_digest=$(jq -er '.releaseCandidate.documentStoreImageDigest' "$restore_start_evidence")
operator_digest=$(jq -er '.releaseCandidate.releaseOperatorImageDigest' "$restore_start_evidence")
source_canary=$(jq -er '.restoreSource.canaryId' "$restore_start_evidence")
source_marker_sha=$(jq -er '.restoreSource.markerSha256' "$restore_start_evidence")
source_evidence_sha=$(jq -er '.restoreSource.evidenceSha256' "$restore_start_evidence")
rds_restore_job=$(jq -er '.restoreJobIds.rds' "$restore_start_evidence")
s3_restore_job=$(jq -er '.restoreJobIds.s3' "$restore_start_evidence")
rds_recovery_point=$(jq -er '.sourceRecoveryPoints.rds' "$restore_start_evidence")
s3_recovery_point=$(jq -er '.sourceRecoveryPoints.s3' "$restore_start_evidence")
restore_role=$(jq -er '.restoreRoleArn' "$restore_start_evidence")

seed=$(printf '%s:%s:%s' "$drill_id" "$release_id" "$source_marker_sha" | sha256sum | cut -d' ' -f1)
replay_seed=$(printf 'replay:%s:%s:%s' "$drill_id" "$release_id" "$source_marker_sha" | sha256sum | cut -d' ' -f1)
operation_id="7e57c0de-${seed:0:4}-4${seed:4:3}-8${seed:7:3}-${seed:10:12}"
restore_replay_id="${replay_seed:0:8}-${replay_seed:8:4}-4${replay_seed:12:3}-8${replay_seed:15:3}-${replay_seed:18:12}"
replay_database="restore_replay_${seed:0:12}"
state_input=$(jq -cnS --arg drill "$drill_id" --arg release "$release_id" --arg attestation "$release_attestation_id" \
  --arg canary "$source_canary" --arg source "$source_evidence_sha" --arg marker "$source_marker_sha" \
  --arg start "$restore_start_sha" --arg rds "$rds_restore_job" --arg s3 "$s3_restore_job" \
  --arg rdsRecovery "$rds_recovery_point" --arg s3Recovery "$s3_recovery_point" --arg role "$restore_role" '{
    drillId:$drill,releaseId:$release,releaseAttestationId:$attestation,sourceCanaryId:$canary,
    sourceEvidenceSha256:$source,sourceMarkerSha256:$marker,restoreStartEvidenceSha256:$start,
    rdsRestoreJobId:$rds,s3RestoreJobId:$s3,rdsRecoveryPointArn:$rdsRecovery,
    s3RecoveryPointArn:$s3Recovery,restoreRoleArn:$role}')
state_input_sha=$(printf '%s' "$state_input" | sha256sum | cut -d' ' -f1)
execution_name="jsc-rs-${drill_id}-${restore_start_sha:0:12}"
(( ${#execution_name} <= 80 )) || fail "execution name is too long"
execution_arn="arn:aws:states:${region}:${account_id}:execution:${state_machine_name}:${execution_name}"

if [[ "$action" == start ]]; then
  [[ "$confirmation" == "START RESTORE SEMANTIC VERIFICATION ${drill_id}" ]] || fail "start confirmation mismatch"
  start_output="$output_directory/restore-semantic-start-${drill_id}.json"; require_new_output "$start_output"
  start_temporary=$(mktemp "${output_directory}/.restore-semantic-start-${drill_id}.XXXXXX")
  temporary_files+=("$start_temporary")
  new_temporary_file execution_error_file
  if execution=$(aws stepfunctions describe-execution --region "$region" --execution-arn "$execution_arn" --output json 2>"$execution_error_file"); then
    : # Reconstruct the same immutable binding after an artifact/upload interruption.
  else
    [[ $(<"$execution_error_file") == *ExecutionDoesNotExist* ]] || fail "could not determine deterministic execution existence" 3
    if start_result=$(aws stepfunctions start-execution --region "$region" --state-machine-arn "$state_machine_arn" \
      --name "$execution_name" --input "$state_input" --output json 2>"$execution_error_file"); then
      jq -e --arg arn "$execution_arn" '.executionArn == $arn and .startDate != null' <<<"$start_result" >/dev/null || \
        fail "StartExecution returned another execution binding" 3
    else
      [[ $(<"$execution_error_file") == *ExecutionAlreadyExists* ]] || fail "could not start deterministic semantic execution" 3
    fi
    execution=$(aws stepfunctions describe-execution --region "$region" --execution-arn "$execution_arn" --output json)
  fi
  jq -e --arg machine "$state_machine_arn" --arg name "$execution_name" --arg rawInput "$state_input" --argjson input "$state_input" '
    .stateMachineArn == $machine and .name == $name and
    (.status|IN("RUNNING","SUCCEEDED","FAILED","TIMED_OUT","ABORTED","PENDING_REDRIVE")) and
    .input == $rawInput and (.input|fromjson) == $input and .startDate != null
  ' <<<"$execution" >/dev/null || fail "execution is not bound to the exact input" 3
  jq -nS --arg execution "$execution_arn" --arg machine "$state_machine_arn" --arg name "$execution_name" \
    --arg inputSha "$state_input_sha" --arg restoreSha "$restore_start_sha" --arg started "$(jq -er '.startDate' <<<"$execution")" \
    --argjson input "$state_input" '{schemaVersion:"jsc-public-beta-restore-semantic-execution.v1",status:"EXECUTION_STARTED",
      environment:"public-beta",drillId:$input.drillId,stateMachineArn:$machine,executionArn:$execution,
      executionName:$name,stateMachineInput:$input,stateMachineInputSha256:$inputSha,
      restoreStartEvidenceSha256:$restoreSha,startedAt:$started}' >"$start_temporary"
  chmod 0600 "$start_temporary"
  ln -- "$start_temporary" "$start_output" || fail "could not atomically publish semantic execution binding" 3
  echo "Restore semantic Standard execution started: $execution_arn"; exit 0
fi

wait_for_exact_restore_jobs_terminal() {
  local deadline=$((SECONDS + 5400)) kind job recovery destination observed status created
  for kind in RDS S3; do
    if [[ "$kind" == RDS ]]; then
      job=$rds_restore_job; recovery=$rds_recovery_point
      destination="arn:aws:rds:${region}:${account_id}:db:${database}"
    else
      job=$s3_restore_job; recovery=$s3_recovery_point
      destination="arn:aws:s3:::${bucket}"
    fi
    while :; do
      observed=$(aws backup describe-restore-job --region "$region" --restore-job-id "$job" --output json)
      jq -e --arg account "$account_id" --arg job "$job" --arg type "$kind" --arg recovery "$recovery" \
        --arg role "$restore_role" --arg destination "$destination" '
        .AccountId == $account and .RestoreJobId == $job and .ResourceType == $type and
        .RecoveryPointArn == $recovery and .IamRoleArn == $role and
        ((.CreatedResourceArn // "") == "" or .CreatedResourceArn == $destination)
      ' <<<"$observed" >/dev/null || fail "$kind restore job escaped its immutable account/source/role/destination binding" 3
      status=$(jq -er '.Status' <<<"$observed")
      case "$status" in
        COMPLETED)
          jq -e --arg destination "$destination" '.CreatedResourceArn == $destination and .CompletionDate != null' \
            <<<"$observed" >/dev/null || fail "$kind completed restore job lacks its exact destination/completion binding" 3
          break
          ;;
        FAILED|ABORTED)
          jq -e '.CompletionDate != null' <<<"$observed" >/dev/null || fail "$kind terminal restore job lacks CompletionDate" 3
          break
          ;;
        PENDING|RUNNING) ;;
        *) fail "$kind restore job returned an unknown status: $status" 3 ;;
      esac
      (( SECONDS < deadline )) || fail "$kind restore job remained non-terminal past the cleanup bound" 3
      sleep 20
    done
  done
}

prove_semantic_never_started() {
  local error_file execution listing task described family tags groups group_ids enis desired
  new_temporary_file error_file
  if execution=$(aws stepfunctions describe-execution --region "$region" --execution-arn "$execution_arn" --output json 2>"$error_file"); then
    fail "deterministic semantic execution exists; its exact binding artifact is required for cleanup" 3
  fi
  [[ $(<"$error_file") == *ExecutionDoesNotExist* ]] || fail "could not prove deterministic semantic execution absence" 3
  if aws ssm get-parameter --region "$region" --name "$marker_name" --output json >/dev/null 2>"$error_file"; then
    fail "durable semantic marker exists; its exact execution binding artifact is required for cleanup" 3
  fi
  [[ $(<"$error_file") == *ParameterNotFound* ]] || fail "could not prove durable semantic marker absence" 3
  for desired in PENDING RUNNING; do
    listing=$(aws ecs list-tasks --region "$region" --cluster "$cluster_arn" --desired-status "$desired" --output json)
    while IFS= read -r task; do
      [[ -n "$task" ]] || continue
      described=$(aws ecs describe-tasks --region "$region" --cluster "$cluster_arn" --tasks "$task" --output json)
      family=$(jq -r '.tasks[0].group // ""' <<<"$described")
      case "$family" in
        family:jsc-public-beta-restore-semantic-clone|family:jsc-public-beta-restore-semantic-document-store|family:jsc-public-beta-restore-semantic-verifier|family:jsc-public-beta-restore-semantic-broker|jsc-restore-semantic-broker|jsc-restore-semantic-contain)
          tags=$(aws ecs list-tags-for-resource --region "$region" --resource-arn "$task" --output json)
          if jq -e --arg drill "$drill_id" 'any(.tags[]?;.key == "RestoreDrillId" and .value == $drill)' <<<"$tags" >/dev/null; then
            fail "semantic task exists for this drill; its exact execution binding artifact is required for cleanup" 3
          fi
          ;;
      esac
    done < <(jq -r '.taskArns[]?' <<<"$listing")
  done
  groups=$(aws ec2 describe-security-groups --region "$region" --filters \
    Name=tag:Application,Values="Job Seeker Copilot" Name=tag:Environment,Values=public-beta \
    Name=tag:ManagedBy,Values=Terraform Name=tag:Repository,Values=jobseekercopilot/infrastructure \
    Name=tag:CostCentre,Values=public-beta Name=tag:Purpose,Values=RestoreSemanticVerifier,RestoreSemanticBroker --output json)
  jq -e '(.SecurityGroups|length) == 2 and
    ([.SecurityGroups[]|(.Tags|from_entries).Purpose]|sort) == ["RestoreSemanticBroker","RestoreSemanticVerifier"] and
    all(.SecurityGroups[];(.Tags|from_entries) as $t | (.Tags|length) == 7 and ([.Tags[].Key]|unique|length) == 7 and
      $t == {Application:"Job Seeker Copilot",Environment:"public-beta",ManagedBy:"Terraform",
        Repository:"jobseekercopilot/infrastructure",CostCentre:"public-beta",Purpose:$t.Purpose,
        Name:(if $t.Purpose == "RestoreSemanticVerifier" then "jsc-public-beta-restore-semantic-verifier"
              else "jsc-public-beta-restore-semantic-broker" end)}))' <<<"$groups" >/dev/null || \
    fail "could not resolve the exact Terraform-owned semantic security groups" 3
  group_ids=$(jq -jr '[.SecurityGroups[].GroupId]|sort|join(",")' <<<"$groups")
  enis=$(aws ec2 describe-network-interfaces --region "$region" --filters Name=group-id,Values="$group_ids" --output json)
  jq -e '.NetworkInterfaces == []' <<<"$enis" >/dev/null || fail "semantic/broker ENIs exist; cleanup without an execution artifact is refused" 3
  echo "Proved deterministic semantic execution/marker/tasks/ENIs never existed for this drill."
}

if [[ "$action" == cleanup && -z "$semantic_start_evidence" ]]; then
  wait_for_exact_restore_jobs_terminal
  prove_semantic_never_started
  echo "Exact restore jobs are terminal; no semantic execution was started."
  exit 0
fi

require_safe_file "$semantic_start_evidence" "restore-semantic execution evidence"
jq -e --arg drill "$drill_id" --arg machine "$state_machine_arn" --arg inputSha "$state_input_sha" \
  --arg restoreSha "$restore_start_sha" --argjson input "$state_input" '
  .schemaVersion == "jsc-public-beta-restore-semantic-execution.v1" and .status == "EXECUTION_STARTED" and
  .environment == "public-beta" and .drillId == $drill and .stateMachineArn == $machine and
  .stateMachineInput == $input and .stateMachineInputSha256 == $inputSha and .restoreStartEvidenceSha256 == $restoreSha
' "$semantic_start_evidence" >/dev/null || fail "semantic execution evidence binding is invalid" 3
execution_arn=$(jq -er '.executionArn' "$semantic_start_evidence")
[[ "$execution_arn" == "arn:aws:states:${region}:${account_id}:execution:${state_machine_name}:"* ]] || fail "execution ARN is out of scope" 3

get_durable_marker() {
  marker_json=$(aws ssm get-parameter --region "$region" --name "$marker_name" --query Parameter.Value --output text)
  marker_sha=$(printf '%s' "$marker_json" | sha256sum | cut -d' ' -f1)
  marker_tags=$(aws ssm list-tags-for-resource --region "$region" --resource-type Parameter --resource-id "$marker_name" --output json)
  jq -e --arg drill "$drill_id" '(.TagList|length) == 4 and ([.TagList[].Key]|unique|length) == 4 and
    (.TagList|from_entries) == {Application:"Job Seeker Copilot",Environment:"public-beta",
    ManagedBy:"RestoreSemanticVerification",RestoreDrillId:$drill}' <<<"$marker_tags" >/dev/null || fail "durable marker tags are not exact" 3
}
assert_child_tags() {
  local tags; tags=$(aws ecs list-tags-for-resource --region "$region" --resource-arn "$1" --output json)
  jq -e --arg drill "$drill_id" --arg managed "$2" '(.tags|length) == 4 and ([.tags[].key]|unique|length) == 4 and
    (.tags|from_entries) == {Application:"Job Seeker Copilot",
    Environment:"public-beta",ManagedBy:$managed,RestoreDrillId:$drill}' <<<"$tags" >/dev/null || fail "task tags drifted: $1" 3
}

contain_children_after_terminal_execution() {
  local execution status deadline task listing described family candidates live marker_valid=true tags containment_drift=false recorded
  deadline=$((SECONDS + 600))
  while :; do
    execution=$(aws stepfunctions describe-execution --region "$region" --execution-arn "$execution_arn" --output json)
    jq -e --arg machine "$state_machine_arn" --argjson input "$state_input" \
      '.stateMachineArn == $machine and (.input|fromjson) == $input' <<<"$execution" >/dev/null || \
      fail "execution changed from its immutable start binding" 3
    status=$(jq -er '.status' <<<"$execution")
    case "$status" in
      SUCCEEDED|FAILED|TIMED_OUT|ABORTED) break ;;
      RUNNING) ;;
      PENDING_REDRIVE) fail "execution is PENDING_REDRIVE; cleanup is refused until redrive is completed or permanently declined" 3 ;;
      *) fail "execution returned an unknown non-terminal status: $status" 3 ;;
    esac
    (( SECONDS < deadline )) || fail "execution is still RUNNING; cleanup is refused and emergency cancellation is admin-only" 3
    sleep 10
  done
  marker_json=''; marker_tags=''
  if marker_json=$(aws ssm get-parameter --region "$region" --name "$marker_name" --query Parameter.Value --output text) &&
     marker_tags=$(aws ssm list-tags-for-resource --region "$region" --resource-type Parameter --resource-id "$marker_name" --output json) &&
     jq -e --arg execution "$execution_arn" --arg drill "$drill_id" '
       .schemaVersion == "jsc-public-beta-restore-semantic-start-marker.v2" and .executionArn == $execution and
       .drillId == $drill and ((.childTasks // {})|type == "object")' <<<"$marker_json" >/dev/null &&
     jq -e --arg drill "$drill_id" '(.TagList|length) == 4 and ([.TagList[].Key]|unique|length) == 4 and
       (.TagList|from_entries) == {Application:"Job Seeker Copilot",Environment:"public-beta",
         ManagedBy:"RestoreSemanticVerification",RestoreDrillId:$drill}' <<<"$marker_tags" >/dev/null; then
    candidates=$(jq -r '.childTasks[]?,(.runtimeBinding?.broker?.taskArn? // empty)' <<<"$marker_json")
  else
    marker_valid=false
    candidates=''
  fi
  for desired in PENDING RUNNING; do
    listing=$(aws ecs list-tasks --region "$region" --cluster "$cluster_arn" --desired-status "$desired" --output json)
    candidates+=$'\n'"$(jq -r '.taskArns[]?' <<<"$listing")"
  done
  while IFS= read -r task; do
    [[ -n "$task" ]] || continue
    recorded=false
    if [[ "$marker_valid" == true ]] && jq -e --arg task "$task" '([.childTasks[]?]+[(.runtimeBinding?.broker?.taskArn? // empty)])|index($task) != null' <<<"$marker_json" >/dev/null; then
      recorded=true
    fi
    described=$(aws ecs describe-tasks --region "$region" --cluster "$cluster_arn" --tasks "$task" --output json)
    family=$(jq -r '.tasks[0].group//"MISSING"' <<<"$described")
    case "$family" in family:jsc-public-beta-restore-semantic-clone|family:jsc-public-beta-restore-semantic-document-store|family:jsc-public-beta-restore-semantic-verifier|family:jsc-public-beta-restore-semantic-broker|jsc-restore-semantic-broker|jsc-restore-semantic-contain) ;;
      *) [[ "$recorded" == true ]] && containment_drift=true; continue ;;
    esac
    tags=$(aws ecs list-tags-for-resource --region "$region" --resource-arn "$task" --output json)
    if jq -e --arg drill "$drill_id" '(.tags|from_entries) as $t |
      (.tags|length) == 4 and ([.tags[].key]|unique|length) == 4 and ($t|keys|length) == 4 and
      $t.Application == "Job Seeker Copilot" and $t.Environment == "public-beta" and
      ($t.ManagedBy == "RestoreSemanticVerification" or $t.ManagedBy == "RestoreSemanticBroker") and
      $t.RestoreDrillId == $drill' <<<"$tags" >/dev/null; then
      [[ $(jq -r '.tasks[0].lastStatus' <<<"$described") == STOPPED ]] || aws ecs stop-task --region "$region" --cluster "$cluster_arn" \
        --task "$task" --reason "bounded exact restore semantic containment" >/dev/null
    elif [[ "$recorded" == true ]]; then containment_drift=true; fi
  done < <(printf '%s\n' "$candidates" | sort -u)
  deadline=$((SECONDS + 480))
  while :; do
    live=0
    for desired in PENDING RUNNING; do
      listing=$(aws ecs list-tasks --region "$region" --cluster "$cluster_arn" --desired-status "$desired" --output json)
      while IFS= read -r task; do
        [[ -n "$task" ]] || continue
        tags=$(aws ecs list-tags-for-resource --region "$region" --resource-arn "$task" --output json)
        if jq -e --arg drill "$drill_id" '(.tags|from_entries) as $t |
          (.tags|length) == 4 and ([.tags[].key]|unique|length) == 4 and ($t|keys|length) == 4 and
          $t.Application == "Job Seeker Copilot" and $t.Environment == "public-beta" and
          ($t.ManagedBy == "RestoreSemanticVerification" or $t.ManagedBy == "RestoreSemanticBroker") and
          $t.RestoreDrillId == $drill' <<<"$tags" >/dev/null; then live=$((live + 1)); fi
      done < <(jq -r '.taskArns[]?' <<<"$listing")
    done
    (( live == 0 )) && break; (( SECONDS < deadline )) || fail "semantic children remain live" 3; sleep 5
  done
  [[ "$marker_valid" == true ]] || fail "durable marker is missing/malformed; exact-tag live tasks were contained but cleanup remains refused" 3
  [[ "$containment_drift" == false ]] || fail "recorded task family/tags drifted; exact-tag live tasks were contained but cleanup remains refused" 3
  echo "Terminal execution and exact PENDING/RUNNING children contained; permanent marker retained: $marker_name"
}

if [[ "$action" == contain || "$action" == cleanup ]]; then
  if [[ "$action" == contain ]]; then [[ "$confirmation" == "CONTAIN RESTORE SEMANTIC VERIFICATION ${drill_id}" ]] || fail "containment confirmation mismatch"
  else [[ "$confirmation" == "DELETE ISOLATED RESTORE DRILL ${drill_id}" ]] || fail "cleanup confirmation mismatch"; fi
  [[ "$action" == cleanup ]] && wait_for_exact_restore_jobs_terminal
  contain_children_after_terminal_execution
  exit 0
fi

[[ "$confirmation" == "OBSERVE RESTORE SEMANTIC VERIFICATION ${drill_id}" ]] || fail "observation confirmation mismatch"
[[ "$data_kms_key_arn" =~ ^arn:aws:kms:eu-west-2:${account_id}:key/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || fail "data KMS key ARN is malformed or out of scope"
observation_output="$output_directory/restore-semantic-observation-${drill_id}.json"; require_new_output "$observation_output"
get_durable_marker
expected_input_binding=$(jq -cnS --arg execution "$execution_arn" --argjson input "$state_input" --arg operation "$operation_id" \
  --arg replay "$restore_replay_id" --arg replayDb "$replay_database" '$input+{executionArn:$execution,operationId:$operation,restoreReplayId:$replay,replayDatabase:$replayDb}' | sha256sum | cut -d' ' -f1)
jq -e --arg drill "$drill_id" --arg execution "$execution_arn" --arg binding "$expected_input_binding" --arg operation "$operation_id" \
  --arg replay "$restore_replay_id" --arg replayDb "$replay_database" --arg machine "$state_machine_arn" --arg account "$account_id" '
  (keys|sort) == (["attempt","childTasks","completedAt","createdAt","drillId","executionArn","inputBindingSha256",
    "lastAttemptStartedAt","network","operationId","phase","publicSafety","replayDatabase","restoreReplayId",
    "runtimeBinding","schemaVersion","verifierLogStream"]|sort) and
  .schemaVersion == "jsc-public-beta-restore-semantic-start-marker.v2" and .phase == "COMPLETED" and
  .drillId == $drill and .executionArn == $execution and .inputBindingSha256 == $binding and
  .operationId == $operation and .restoreReplayId == $replay and .replayDatabase == $replayDb and
  (.attempt|type == "number" and . >= 1 and . <= 3 and floor == .) and
  (.childTasks|keys|sort) == ["clone","replayApplication","sourceApplication","verifier"] and
  (.runtimeBinding|keys|sort) == (["broker","childNetwork","executionArn","privateSubnetIds","stateMachineArn"]|sort) and
  .runtimeBinding.stateMachineArn == $machine and .runtimeBinding.executionArn == $execution and
  .runtimeBinding.broker.injectedSecretCount == 0 and (.runtimeBinding.privateSubnetIds|length) == 2 and
  (.runtimeBinding.privateSubnetIds|unique|length) == 2 and .network.childStaticRuleCount == 7 and
  .network.brokerStaticRuleCount == 3 and .network.semanticEniCountBeforeStart == 0 and
  .network.semanticEniCountAfterContainment == 0 and
  .network.restoredDatabaseArn == ("arn:aws:rds:eu-west-2:"+$account+":db:jsc-public-beta-restore-"+$drill) and
  .publicSafety == {publicEntrypointFixed503:true,applicationDesiredCount:0,runningPublicApplicationTaskCount:0,
    pendingClusterTaskCountAfterContainment:0,semanticTasksNotAttachedToPublicFleet:true}
' <<<"$marker_json" >/dev/null || fail "completed marker shape/binding is invalid" 3

execution=$(aws stepfunctions describe-execution --region "$region" --execution-arn "$execution_arn" --output json)
jq -e --arg machine "$state_machine_arn" --argjson input "$state_input" '.stateMachineArn == $machine and .status == "SUCCEEDED" and
  (.input|fromjson) == $input and .startDate != null and .stopDate != null' <<<"$execution" >/dev/null || fail "execution did not succeed with exact input" 3
execution_start=$(jq -er '.startDate' <<<"$execution"); execution_stop=$(jq -er '.stopDate' <<<"$execution")

# Resolve immutable task-definition revisions from stopped tasks, never from latest-family aliases or marker assertions.
describe_exact_task() {
  local task_arn=$1 family=$2 digest=$3 managed=$4 network_key=$5 described marker_network expected_group expected_started_by
  if [[ "$managed" == RestoreSemanticBroker ]]; then
    expected_group=jsc-restore-semantic-broker
    expected_started_by="AWS Step Functions"
  else
    expected_group="family:${family}"
    expected_started_by=$started_by
  fi
  described=$(aws ecs describe-tasks --region "$region" --cluster "$cluster_arn" --tasks "$task_arn" --include TAGS --output json)
  jq -e --arg arn "$task_arn" --arg group "$expected_group" --arg started "$expected_started_by" --arg digest "$digest" '
    (.failures|length) == 0 and (.tasks|length) == 1 and
    .tasks[0].taskArn == $arn and .tasks[0].group == $group and .tasks[0].startedBy == $started and
    .tasks[0].lastStatus == "STOPPED" and
    (.tasks[0].containers|length) == 1 and .tasks[0].containers[0].imageDigest == $digest' <<<"$described" >/dev/null || fail "stopped task binding drifted: $task_arn" 3
  assert_child_tags "$task_arn" "$managed"
  if [[ "$managed" == RestoreSemanticBroker ]]; then marker_network=$(jq -c '.runtimeBinding.broker|{eniId,privateIp,subnetId,securityGroupId}' <<<"$marker_json")
  else marker_network=$(jq -c --arg key "$network_key" '.runtimeBinding.childNetwork[$key]' <<<"$marker_json"); fi
  jq -e --argjson expected "$marker_network" --argjson subnets "$(jq -c '.runtimeBinding.privateSubnetIds' <<<"$marker_json")" '
    .tasks[0] as $task |
    ($task.attachments|length) == 1 and $task.attachments[0].type == "ElasticNetworkInterface" and
    ($task.attachments[0].details|type) == "array" and
    ([$task.attachments[0].details[].name]|length) == ([$task.attachments[0].details[].name]|unique|length) and
    (["networkInterfaceId","privateIPv4Address","subnetId"] - [$task.attachments[0].details[].name]|length) == 0 and
    ([$task.attachments[0].details[]|select((.name|IN("networkInterfaceId","privateIPv4Address","subnetId","macAddress","privateDnsName"))|not)]|length) == 0 and
    [$task.attachments[0].details[]|{key:.name,value:.value}]|from_entries as $n |
    $n.networkInterfaceId == $expected.eniId and $n.privateIPv4Address == $expected.privateIp and
    $n.subnetId == $expected.subnetId and ($subnets|index($expected.subnetId)) != null' <<<"$described" >/dev/null || fail "task attachment/marker ENI tuple drifted" 3
  jq -er '.tasks[0].taskDefinitionArn' <<<"$described"
}
clone_task=$(jq -er '.childTasks.clone' <<<"$marker_json"); source_task=$(jq -er '.childTasks.sourceApplication' <<<"$marker_json")
replay_task=$(jq -er '.childTasks.replayApplication' <<<"$marker_json"); verifier_task=$(jq -er '.childTasks.verifier' <<<"$marker_json")
broker_task=$(jq -er '.runtimeBinding.broker.taskArn' <<<"$marker_json")
clone_definition=$(describe_exact_task "$clone_task" jsc-public-beta-restore-semantic-clone "$operator_digest" RestoreSemanticVerification clone)
app_definition=$(describe_exact_task "$source_task" jsc-public-beta-restore-semantic-document-store "$document_digest" RestoreSemanticVerification sourceApplication)
replay_definition=$(describe_exact_task "$replay_task" jsc-public-beta-restore-semantic-document-store "$document_digest" RestoreSemanticVerification replayApplication)
[[ "$replay_definition" == "$app_definition" ]] || fail "source/replay application definitions differ" 3
verifier_definition=$(describe_exact_task "$verifier_task" jsc-public-beta-restore-semantic-verifier "$operator_digest" RestoreSemanticVerification verifier)
broker_definition=$(describe_exact_task "$broker_task" jsc-public-beta-restore-semantic-broker "$operator_digest" RestoreSemanticBroker broker)

broker_execution_role="arn:aws:iam::${account_id}:role/jsc-public-beta-restore-semantic-broker-execution"
broker_task_role="arn:aws:iam::${account_id}:role/jsc-public-beta-restore-semantic-broker-task"
clone_execution="arn:aws:iam::${account_id}:role/jsc-public-beta-restore-semantic-clone-execution"
app_execution="arn:aws:iam::${account_id}:role/jsc-public-beta-restore-semantic-document-store-execution"
app_task_role="arn:aws:iam::${account_id}:role/jsc-public-beta-restore-semantic-document-store-task"
verifier_execution="arn:aws:iam::${account_id}:role/jsc-public-beta-restore-semantic-verifier-execution"
verifier_task_role="arn:aws:iam::${account_id}:role/jsc-public-beta-restore-semantic-verifier-task"
private_subnets=$(jq -cS '.runtimeBinding.privateSubnetIds' <<<"$marker_json")
broker_sg=$(jq -er '.network.brokerSecurityGroupId' <<<"$marker_json")
vpc_id=$(jq -er '.network.vpcId' <<<"$marker_json")
database_sg=$(jq -er '.network.restoreDatabaseSecurityGroupId' <<<"$marker_json")
semantic_sg=$(jq -er '.network.semanticSecurityGroupId' <<<"$marker_json")

verify_task_definition() {
  local definition=$1 kind=$2 described
  described=$(aws ecs describe-task-definition --region "$region" --task-definition "$definition" --include TAGS --output json)
  case "$kind" in
    broker) broker_definition_json=$described ;;
    clone) clone_definition_json=$described ;;
    application) application_definition_json=$described ;;
    verifier) verifier_definition_json=$described ;;
  esac
  jq -e --arg arn "$definition" '.taskDefinition.taskDefinitionArn == $arn and (.tags|type == "array")' \
    <<<"$described" >/dev/null || fail "$kind task definition lookup is not exact" 3
}
verify_task_definition "$broker_definition" broker
verify_task_definition "$clone_definition" clone
verify_task_definition "$app_definition" application
verify_task_definition "$verifier_definition" verifier

state_machine=$(aws stepfunctions describe-state-machine --region "$region" --state-machine-arn "$state_machine_arn" --output json)
expected_state_machine=$(jq -cnS --arg cluster "$cluster_arn" --arg definition "$broker_definition" \
  --arg exec "$broker_execution_role" --arg task "$broker_task_role" --arg sg "$broker_sg" --argjson subnets "$private_subnets" '
  def network: {AwsvpcConfiguration:{Subnets:$subnets,SecurityGroups:[$sg],AssignPublicIp:"DISABLED"}};
  def static_environment: [
    {Name:"RESTORE_BROKER_TASK_DEFINITION_ARN",Value:$definition},
    {Name:"RESTORE_BROKER_EXECUTION_ROLE_ARN",Value:$exec},
    {Name:"RESTORE_BROKER_TASK_ROLE_ARN",Value:$task}
  ];
  def dynamic_environment: [
    {Name:"RESTORE_DRILL_ID","Value.$":"$.drillId"},
    {Name:"RELEASE_ID","Value.$":"$.releaseId"},
    {Name:"RELEASE_ATTESTATION_ID","Value.$":"$.releaseAttestationId"},
    {Name:"RESTORE_SOURCE_CANARY_ID","Value.$":"$.sourceCanaryId"},
    {Name:"RESTORE_SOURCE_EVIDENCE_SHA256","Value.$":"$.sourceEvidenceSha256"},
    {Name:"RESTORE_SOURCE_MARKER_SHA256","Value.$":"$.sourceMarkerSha256"},
    {Name:"RESTORE_START_EVIDENCE_SHA256","Value.$":"$.restoreStartEvidenceSha256"},
    {Name:"RDS_RESTORE_JOB_ID","Value.$":"$.rdsRestoreJobId"},
    {Name:"S3_RESTORE_JOB_ID","Value.$":"$.s3RestoreJobId"},
    {Name:"RDS_RECOVERY_POINT_ARN","Value.$":"$.rdsRecoveryPointArn"},
    {Name:"S3_RECOVERY_POINT_ARN","Value.$":"$.s3RecoveryPointArn"},
    {Name:"RESTORE_ROLE_ARN","Value.$":"$.restoreRoleArn"},
    {Name:"STATE_MACHINE_EXECUTION_ARN","Value.$":"$$.Execution.Id"}
  ];
  def tags: [
    {Key:"Application",Value:"Job Seeker Copilot"},
    {Key:"Environment",Value:"public-beta"},
    {Key:"ManagedBy",Value:"RestoreSemanticBroker"},
    {Key:"RestoreDrillId","Value.$":"$.drillId"}
  ];
  def parameters($group;$command;$environment): {
    Cluster:$cluster,TaskDefinition:$definition,LaunchType:"EC2",Group:$group,
    NetworkConfiguration:network,
    Overrides:{ExecutionRoleArn:$exec,TaskRoleArn:$task,ContainerOverrides:[{
      Name:"restore-semantic-broker",Command:$command,Environment:$environment
    }]},Tags:tags,EnableECSManagedTags:false
  };
  {Comment:"Fixed-network, secret-free broker for isolated restore semantic verification",StartAt:"RunVerifierBroker",States:{
    RunVerifierBroker:{Type:"Task",Resource:"arn:aws:states:::ecs:runTask.sync",TimeoutSeconds:7200,
      Parameters:parameters("jsc-restore-semantic-broker";["/opt/jsc/run-restore-semantic-broker.sh","start"];
        (static_environment+dynamic_environment)),
      Catch:[{ErrorEquals:["States.ALL"],ResultPath:"$.brokerFailure",Next:"ContainChildren"}],End:true},
    ContainChildren:{Type:"Task",Resource:"arn:aws:states:::ecs:runTask.sync",TimeoutSeconds:900,
      Parameters:parameters("jsc-restore-semantic-contain";["/opt/jsc/run-restore-semantic-broker.sh","contain"];
        (static_environment+[{Name:"RESTORE_DRILL_ID","Value.$":"$.drillId"}])),Next:"VerificationFailed"},
    VerificationFailed:{Type:"Fail",Error:"RestoreSemanticVerificationFailed",
      Cause:"The fixed broker failed; child containment was invoked."}
  }}')
jq -e --arg role "$state_machine_role" --argjson expected "$expected_state_machine" '
  .type == "STANDARD" and .roleArn == $role and (.definition|fromjson) == $expected
' <<<"$state_machine" >/dev/null || fail "state machine escaped fixed broker contract" 3

workload_boundary="arn:aws:iam::${account_id}:policy/jsc-public-beta-workload-boundary"; broker_boundary="arn:aws:iam::${account_id}:policy/jsc-public-beta-restore-semantic-broker-boundary"

# Collect full IAM documents for the offline validator. It compares exact trust,
# every inline Resource/Condition, the attachment set, and the live default
# AmazonECSTaskExecutionRolePolicy document. A permissions boundary is bound by
# exact ARN; it only intersects/limits identity permissions and cannot grant.
iam_roles='{}'
collect_role_contract() {
  local kind=$1 role_arn=$2 name role inline attached policy_name policy_document inline_documents='{}' entry
  name=${role_arn##*/}
  role=$(aws iam get-role --role-name "$name" --output json)
  inline=$(aws iam list-role-policies --role-name "$name" --output json)
  attached=$(aws iam list-attached-role-policies --role-name "$name" --output json)
  while IFS= read -r policy_name; do
    [[ -n "$policy_name" ]] || continue
    policy_document=$(aws iam get-role-policy --role-name "$name" --policy-name "$policy_name" --query PolicyDocument --output json)
    inline_documents=$(jq -cnS --argjson old "$inline_documents" --arg name "$policy_name" --argjson document "$policy_document" \
      '$old+{($name):$document}')
  done < <(jq -r '.PolicyNames[]?' <<<"$inline")
  entry=$(jq -cnS --argjson role "$role" --argjson names "$(jq -c '.PolicyNames|sort' <<<"$inline")" \
    --argjson attached "$(jq -c '[.AttachedPolicies[].PolicyArn]|sort' <<<"$attached")" --argjson documents "$inline_documents" \
    '{getRole:$role,inlinePolicyNames:$names,attachedPolicies:$attached,inlineDocuments:$documents}')
  iam_roles=$(jq -cnS --argjson old "$iam_roles" --arg kind "$kind" --argjson entry "$entry" '$old+{($kind):$entry}')
}
collect_role_contract stateMachine "$state_machine_role"
collect_role_contract brokerExecution "$broker_execution_role"
collect_role_contract brokerTask "$broker_task_role"
collect_role_contract cloneExecution "$clone_execution"
collect_role_contract applicationExecution "$app_execution"
collect_role_contract applicationTask "$app_task_role"
collect_role_contract verifierExecution "$verifier_execution"
collect_role_contract verifierTask "$verifier_task_role"
managed_execution_policy_arn=arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
managed_policy_metadata=$(aws iam get-policy --policy-arn "$managed_execution_policy_arn" --output json)
managed_policy_version_id=$(jq -er '.Policy.DefaultVersionId' <<<"$managed_policy_metadata")
managed_policy_version=$(aws iam get-policy-version --policy-arn "$managed_execution_policy_arn" --version-id "$managed_policy_version_id" --output json)
new_temporary_file iam_contracts_file
jq -nS --argjson roles "$iam_roles" --argjson metadata "$managed_policy_metadata" --argjson version "$managed_policy_version" \
  '{roles:$roles,managedExecutionPolicy:{metadata:$metadata,version:$version}}' >"$iam_contracts_file"

groups=$(aws ec2 describe-security-groups --region "$region" --group-ids "$database_sg" "$semantic_sg" "$broker_sg" --output json)
jq -e --arg vpc "$vpc_id" --arg db "$database_sg" --arg semantic "$semantic_sg" --arg broker "$broker_sg" '(.SecurityGroups|length) == 3 and all(.SecurityGroups[];.VpcId == $vpc) and
  any(.SecurityGroups[];.GroupId == $db and (.Tags|from_entries).Purpose == "RestoreDatabase") and any(.SecurityGroups[];.GroupId == $semantic and (.Tags|from_entries).Purpose == "RestoreSemanticVerifier") and
  any(.SecurityGroups[];.GroupId == $broker and (.Tags|from_entries).Purpose == "RestoreSemanticBroker")' <<<"$groups" >/dev/null || fail "semantic security groups drifted" 3
subnets=$(aws ec2 describe-subnets --region "$region" --subnet-ids $(jq -r '.[]' <<<"$private_subnets") --output json)
jq -e --arg vpc "$vpc_id" --argjson expected "$private_subnets" '(.Subnets|length) == 2 and ([.Subnets[].SubnetId]|sort) == ($expected|sort) and
  all(.Subnets[];.VpcId == $vpc and .MapPublicIpOnLaunch == false and .State == "available") and ([.Subnets[].AvailabilityZone]|unique|length) == 2' <<<"$subnets" >/dev/null || fail "private subnets drifted" 3
prefix=$(aws ec2 describe-prefix-lists --region "$region" --filters Name=prefix-list-name,Values="com.amazonaws.${region}.s3" --output json | jq -er '.PrefixLists|if length == 1 then .[0].PrefixListId else error("prefix") end')
rules=$(aws ec2 describe-security-group-rules --region "$region" --filters Name=group-id,Values="$database_sg,$semantic_sg,$broker_sg" --output json)
jq -e --arg db "$database_sg" --arg semantic "$semantic_sg" --arg broker "$broker_sg" --arg s3 "$prefix" '
 [.SecurityGroupRules[]|{group:.GroupId,egress:.IsEgress,protocol:.IpProtocol,from:(.FromPort//null),to:(.ToPort//null),referenced:(.ReferencedGroupInfo.GroupId//null),cidr:(.CidrIpv4//null),prefix:(.PrefixListId//null)}]|
 sort_by(.group,.egress,.protocol,.from,.to,.referenced,.cidr,.prefix) == ([
 {group:$db,egress:false,protocol:"tcp",from:5432,to:5432,referenced:$semantic,cidr:null,prefix:null},
 {group:$semantic,egress:false,protocol:"tcp",from:8089,to:8089,referenced:$semantic,cidr:null,prefix:null},
 {group:$semantic,egress:true,protocol:"tcp",from:53,to:53,referenced:null,cidr:"10.42.0.2/32",prefix:null},
 {group:$semantic,egress:true,protocol:"tcp",from:443,to:443,referenced:null,cidr:null,prefix:$s3},
 {group:$semantic,egress:true,protocol:"tcp",from:5432,to:5432,referenced:$db,cidr:null,prefix:null},
 {group:$semantic,egress:true,protocol:"tcp",from:8089,to:8089,referenced:$semantic,cidr:null,prefix:null},
 {group:$semantic,egress:true,protocol:"udp",from:53,to:53,referenced:null,cidr:"10.42.0.2/32",prefix:null},
 {group:$broker,egress:true,protocol:"tcp",from:53,to:53,referenced:null,cidr:"10.42.0.2/32",prefix:null},
 {group:$broker,egress:true,protocol:"tcp",from:443,to:443,referenced:null,cidr:"0.0.0.0/0",prefix:null},
 {group:$broker,egress:true,protocol:"udp",from:53,to:53,referenced:null,cidr:"10.42.0.2/32",prefix:null}]|sort_by(.group,.egress,.protocol,.from,.to,.referenced,.cidr,.prefix))' <<<"$rules" >/dev/null || fail "SG rules are not exact seven plus three" 3

# CloudTrail ECS RunTask is authoritative after awsvpc trunk branch ENIs are
# deleted; EC2 CreateNetworkInterface event history records only the trunk ENI.
cloudtrail_start=$(date -u -d "$execution_start - 5 minutes" +%Y-%m-%dT%H:%M:%SZ)
marker_endpoint=$(jq -er '.network.restoredDatabaseEndpoint' <<<"$marker_json")
restored_arn="arn:aws:rds:${region}:${account_id}:db:${database}"
verify_all_child_run_tasks() {
  local deadline=$((SECONDS + 900)) events token page next end_time relevant_run_task_events validation_error
  local relevant_digest stable_digest='' stable_count=0 not_before
  local -a described_task_arns=()
  not_before=$(( $(date -u -d "$execution_stop" +%s) + 300 ))
  new_temporary_file cloudtrail_file; new_temporary_file task_history_file; new_temporary_file run_task_context_file
  while :; do
    events='[]'; token=''; pages=0; end_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    while :; do
      if [[ -n "$token" ]]; then page=$(aws cloudtrail lookup-events --region "$region" --lookup-attributes AttributeKey=EventName,AttributeValue=RunTask \
        --start-time "$cloudtrail_start" --end-time "$end_time" --next-token "$token" --output json)
      else page=$(aws cloudtrail lookup-events --region "$region" --lookup-attributes AttributeKey=EventName,AttributeValue=RunTask \
        --start-time "$cloudtrail_start" --end-time "$end_time" --output json); fi
      events=$(jq -cn --argjson old "$events" --argjson new "$(jq -c '[.Events[].CloudTrailEvent|fromjson]' <<<"$page")" '$old+$new')
      next=$(jq -r '.NextToken//""' <<<"$page"); pages=$((pages + 1)); (( pages <= 50 )) || fail "CloudTrail pagination exceeded bound" 3
      [[ -z "$next" ]] && break; token=$next; sleep 1
    done
    relevant_run_task_events=$(jq -c --arg broker "$broker_task_role" --arg state "$state_machine_role" '[.[]|select(.eventSource == "ecs.amazonaws.com" and .eventName == "RunTask" and
      (.userIdentity.sessionContext.sessionIssuer.arn == $broker or .userIdentity.sessionContext.sessionIssuer.arn == $state))]' <<<"$events")
    mapfile -t described_task_arns < <(jq -r '[.[]|.responseElements.tasks[]?.taskArn]|unique[]' <<<"$relevant_run_task_events")
    (( ${#described_task_arns[@]} <= 18 )) || fail "RunTask history exceeded three bounded child/broker attempts" 3
    if (( ${#described_task_arns[@]} )); then
      task_history=$(aws ecs describe-tasks --region "$region" --cluster "$cluster_arn" --tasks "${described_task_arns[@]}" --include TAGS --output json)
    else
      task_history='{"tasks":[],"failures":[]}'
    fi
    jq -cnS --argjson events "$events" '{events:$events}' >"$cloudtrail_file"
    printf '%s' "$task_history" >"$task_history_file"
    jq -nS --arg account "$account_id" --arg region "$region" --arg drill "$drill_id" \
      --argjson attempt "$(jq -er '.attempt' <<<"$marker_json")" --arg lastAttempt "$(jq -er '.lastAttemptStartedAt' <<<"$marker_json")" \
      --arg role "$broker_task_role" --arg stateRole "$state_machine_role" --arg cluster "$cluster_arn" --arg started "$started_by" --arg binding "$expected_input_binding" \
      --arg cloneDef "$clone_definition" --arg appDef "$app_definition" --arg verifierDef "$verifier_definition" \
      --arg clone "$clone_task" --arg source "$source_task" --arg replay "$replay_task" --arg verifier "$verifier_task" \
      --argjson subnets "$private_subnets" --arg semanticSg "$semantic_sg" --arg host "$marker_endpoint" \
      --arg release "$release_id" --arg canary "$source_canary" --arg marker "$source_marker_sha" --arg sourceEvidence "$source_evidence_sha" \
      --arg replayDb "$replay_database" --arg bucket "$bucket" --arg operation "$operation_id" --arg replayId "$restore_replay_id" \
      --arg documentDigest "$document_digest" --arg operatorDigest "$operator_digest" --arg vpc "$vpc_id" \
      --arg databaseSg "$database_sg" --arg restoredArn "$restored_arn" --arg brokerDef "$broker_definition" \
      --arg brokerExec "$broker_execution_role" --arg brokerTaskRole "$broker_task_role" --arg brokerSg "$broker_sg" \
      --arg execution "$execution_arn" --arg markerBroker "$broker_task" --argjson stateInput "$state_input" '{
        accountId:$account,region:$region,drillId:$drill,attempt:$attempt,lastAttemptStartedAt:$lastAttempt,
        brokerRoleArn:$role,stateMachineRoleArn:$stateRole,clusterArn:$cluster,startedBy:$started,inputBindingSha256:$binding,
        definitions:{clone:$cloneDef,source:$appDef,replay:$appDef,verifier:$verifierDef},
        currentTasks:{clone:$clone,source:$source,replay:$replay,verifier:$verifier},
        privateSubnetIds:$subnets,semanticSecurityGroupId:$semanticSg,databaseHost:$host,releaseId:$release,
        sourceCanaryId:$canary,sourceMarkerSha256:$marker,sourceEvidenceSha256:$sourceEvidence,
        replayDatabase:$replayDb,bucket:$bucket,operationId:$operation,restoreReplayId:$replayId,
        documentStoreImageDigest:$documentDigest,releaseOperatorImageDigest:$operatorDigest,vpcId:$vpc,
        databaseSecurityGroupId:$databaseSg,restoredDatabaseArn:$restoredArn,brokerDefinitionArn:$brokerDef,
        brokerExecutionRoleArn:$brokerExec,brokerTaskRoleArn:$brokerTaskRole,brokerSecurityGroupId:$brokerSg,
        executionArn:$execution,stateInput:$stateInput,markerBrokerTaskArn:$markerBroker
      }' >"$run_task_context_file"
    if validation_error=$(python3 "$repository_root/scripts/aws/validate_restore_semantic_evidence.py" \
      --run-task-events "$cloudtrail_file" --run-task-tasks "$task_history_file" --run-task-context "$run_task_context_file" 2>&1); then
      relevant_digest=$(jq -cS 'sort_by(.eventID // "",.eventTime)' <<<"$relevant_run_task_events" | sha256sum | cut -d' ' -f1)
      if [[ "$relevant_digest" == "$stable_digest" ]]; then stable_count=$((stable_count + 1));
      else stable_digest=$relevant_digest; stable_count=1; fi
      if (( $(date -u +%s) >= not_before && stable_count >= 2 )); then return 0; fi
      (( SECONDS < deadline )) || fail "CloudTrail RunTask history did not become complete and stable within the delivery bound" 3
      sleep 30
      continue
    fi
    if [[ "$validation_error" != *"current attempt RunTask response ARNs do not match the durable marker"* &&
          "$validation_error" != *"CloudTrail has no broker-role child RunTask event"* &&
          "$validation_error" != *"CloudTrail has no state-machine-role broker RunTask event"* &&
          "$validation_error" != *"durable marker broker task is not a state-machine start response"* ]]; then
      fail "CloudTrail RunTask contract invalid: $validation_error" 3
    fi
    (( SECONDS < deadline )) || fail "CloudTrail did not prove every bounded attempt and the current four child responses" 3
    sleep 30
  done
}
verify_all_child_run_tasks
semantic_enis=$(aws ec2 describe-network-interfaces --region "$region" --filters Name=group-id,Values="$semantic_sg" --output json | jq -er '.NetworkInterfaces|length')
broker_enis=$(aws ec2 describe-network-interfaces --region "$region" --filters Name=group-id,Values="$broker_sg" --output json | jq -er '.NetworkInterfaces|length')
[[ "$semantic_enis" == 0 && "$broker_enis" == 0 ]] || fail "semantic ENIs remain after completion" 3

for binding in "RDS:$rds_restore_job:$rds_recovery_point:arn:aws:rds:${region}:${account_id}:db:${database}" \
  "S3:$s3_restore_job:$s3_recovery_point:arn:aws:s3:::${bucket}"; do
  type=${binding%%:*}; remainder=${binding#*:}; job=${remainder%%:*}
  if [[ "$type" == RDS ]]; then recovery=$rds_recovery_point; destination="arn:aws:rds:${region}:${account_id}:db:${database}"
  else recovery=$s3_recovery_point; destination="arn:aws:s3:::${bucket}"; fi
  restore_job=$(aws backup describe-restore-job --region "$region" --restore-job-id "$job" --output json)
  jq -e --arg account "$account_id" --arg job "$job" --arg type "$type" --arg recovery "$recovery" \
    --arg destination "$destination" --arg role "$restore_role" '.AccountId == $account and .RestoreJobId == $job and
    .ResourceType == $type and .Status == "COMPLETED" and .RecoveryPointArn == $recovery and
    .CreatedResourceArn == $destination and .IamRoleArn == $role and .CompletionDate != null' <<<"$restore_job" >/dev/null || \
    fail "$type restore job binding drifted" 3
done
data_subnets_result=$(aws ec2 describe-subnets --region "$region" --filters Name=vpc-id,Values="$vpc_id" \
  Name=tag:Tier,Values=isolated Name=tag:Network,Values=rds --output json)
data_subnets=$(jq -cS '.Subnets|sort_by(.AvailabilityZone)|[.[].SubnetId]' <<<"$data_subnets_result")
jq -e --arg vpc "$vpc_id" '(.Subnets|length) == 2 and all(.Subnets[];.VpcId == $vpc and
  .MapPublicIpOnLaunch == false and .State == "available") and ([.Subnets[].AvailabilityZone]|unique|length) == 2' \
  <<<"$data_subnets_result" >/dev/null || fail "restored RDS data subnet set drifted" 3
rds=$(aws rds describe-db-instances --region "$region" --db-instance-identifier "$database" --output json)
restored_endpoint=$(jq -er --arg sg "$database_sg" --arg account "$account_id" --arg drill "$drill_id" --arg vpc "$vpc_id" \
  --arg kms "$data_kms_key_arn" --argjson subnets "$data_subnets" '.DBInstances|if length == 1 and
  .[0].DBInstanceArn == ("arn:aws:rds:eu-west-2:"+$account+":db:jsc-public-beta-restore-"+$drill) and
  .[0].DBInstanceStatus == "available" and .[0].PubliclyAccessible == false and .[0].Port == 5432 and .[0].Endpoint.Port == 5432 and
  .[0].Engine == "postgres" and (.[0].EngineVersion|test("^15\\.")) and .[0].StorageEncrypted == true and .[0].KmsKeyId == $kms and
  .[0].MultiAZ == false and .[0].DeletionProtection == false and .[0].DBSubnetGroup.DBSubnetGroupName == "jsc-public-beta-postgres" and
  .[0].DBSubnetGroup.SubnetGroupStatus == "Complete" and .[0].DBSubnetGroup.VpcId == $vpc and
  ([.[0].DBSubnetGroup.Subnets[].SubnetIdentifier]|sort) == ($subnets|sort) and
  (.[0].DBParameterGroups|length) == 1 and (.[0].DBParameterGroups[0].DBParameterGroupName|test("^jsc-public-beta-postgres15-[a-z0-9-]+$")) and
  .[0].DBParameterGroups[0].ParameterApplyStatus == "in-sync" and [.[0].VpcSecurityGroups[].VpcSecurityGroupId] == [$sg]
  then .[0].Endpoint.Address else error("RDS") end' <<<"$rds")
[[ "$restored_endpoint" == "$(jq -er '.network.restoredDatabaseEndpoint' <<<"$marker_json")" ]] || fail "restored endpoint drifted" 3
rds_tags=$(aws rds list-tags-for-resource --region "$region" --resource-name "$restored_arn" --output json)
jq -e --arg drill "$drill_id" '(.TagList|from_entries|with_entries(select(.key|startswith("aws:")|not))) == {
  Application:"Job Seeker Copilot",CostCentre:"public-beta",Environment:"public-beta",ManagedBy:"RestoreDrill",RestoreDrillId:$drill}' \
  <<<"$rds_tags" >/dev/null || fail "restored RDS ownership tags drifted" 3

# The detailed validator rejects duplicate/extra base env, tags and secrets and
# binds every valueFrom/role/image/network setting before final evidence exists.
new_temporary_file task_definitions_file; new_temporary_file task_definition_context_file
jq -nS --argjson broker "$broker_definition_json" --argjson clone "$clone_definition_json" \
  --argjson application "$application_definition_json" --argjson verifier "$verifier_definition_json" \
  '{broker:$broker,clone:$clone,application:$application,verifier:$verifier}' >"$task_definitions_file"
db_parameter_group=$(jq -er '.DBInstances[0].DBParameterGroups[0].DBParameterGroupName' <<<"$rds")
jq -nS --arg account "$account_id" --arg region "$region" --arg dataKms "$data_kms_key_arn" \
  --arg brokerDef "$broker_definition" --arg cloneDef "$clone_definition" --arg appDef "$app_definition" --arg verifierDef "$verifier_definition" \
  --arg brokerExec "$broker_execution_role" --arg brokerTask "$broker_task_role" --arg cloneExec "$clone_execution" \
  --arg appExec "$app_execution" --arg appTask "$app_task_role" --arg verifierExec "$verifier_execution" --arg verifierTask "$verifier_task_role" \
  --argjson privateSubnets "$private_subnets" --argjson dataSubnets "$data_subnets" --arg vpc "$vpc_id" \
  --arg dbSg "$database_sg" --arg semanticSg "$semantic_sg" --arg brokerSg "$broker_sg" --arg parameterGroup "$db_parameter_group" \
  --arg documentDigest "$document_digest" --arg operatorDigest "$operator_digest" '{
    accountId:$account,region:$region,dataKmsKeyArn:$dataKms,
    definitions:{broker:$brokerDef,clone:$cloneDef,application:$appDef,verifier:$verifierDef},
    roles:{brokerExecution:$brokerExec,brokerTask:$brokerTask,cloneExecution:$cloneExec,
      applicationExecution:$appExec,applicationTask:$appTask,verifierExecution:$verifierExec,verifierTask:$verifierTask},
    privateSubnetIds:$privateSubnets,dataSubnetIds:$dataSubnets,vpcId:$vpc,databaseSecurityGroupId:$dbSg,
    semanticSecurityGroupId:$semanticSg,brokerSecurityGroupId:$brokerSg,databaseParameterGroupName:$parameterGroup,
    documentStoreImageDigest:$documentDigest,releaseOperatorImageDigest:$operatorDigest
  }' >"$task_definition_context_file"
python3 "$repository_root/scripts/aws/validate_restore_semantic_evidence.py" \
  --task-definitions "$task_definitions_file" --task-definition-context "$task_definition_context_file" >/dev/null || \
  fail "live semantic task definitions escaped their canonical contracts" 3

document_store_secret_arn=$(jq -er '[.taskDefinition.containerDefinitions[0].secrets[]|select(.name == "DOCUMENT_STORE_DATABASE_PASSWORD")]|if length == 1 then .[0].valueFrom|sub(":password::$";"") else error("document secret") end' <<<"$application_definition_json")
rds_master_secret_arn=$(jq -er '[.taskDefinition.containerDefinitions[0].secrets[]|select(.name == "MASTER_USERNAME")]|if length == 1 then .[0].valueFrom|sub(":username::$";"") else error("master secret") end' <<<"$clone_definition_json")
database_secret_arns=$(jq -ce '[.taskDefinition.containerDefinitions[0].secrets[].valueFrom|sub(":password::$";"")]|unique|sort' <<<"$verifier_definition_json")
erasure_journal_bucket=$(jq -er '[.taskDefinition.containerDefinitions[0].environment[]|select(.name == "ERASURE_JOURNAL_BUCKET")]|if length == 1 then .[0].value else error("journal bucket") end' <<<"$verifier_definition_json")
erasure_journal_kms_key=$(jq -er '[.taskDefinition.containerDefinitions[0].environment[]|select(.name == "ERASURE_JOURNAL_KMS_KEY_ARN")]|if length == 1 then .[0].value else error("journal key") end' <<<"$verifier_definition_json")
new_temporary_file iam_context_file
jq -nS --arg account "$account_id" --arg region "$region" --arg machine "$state_machine_arn" --arg cluster "$cluster_arn" \
  --arg stateRole "$state_machine_role" --arg brokerExec "$broker_execution_role" --arg brokerTask "$broker_task_role" \
  --arg cloneExec "$clone_execution" --arg appExec "$app_execution" --arg appTask "$app_task_role" \
  --arg verifierExec "$verifier_execution" --arg verifierTask "$verifier_task_role" \
  --arg brokerDef "$broker_definition" --arg cloneDef "$clone_definition" --arg appDef "$app_definition" --arg verifierDef "$verifier_definition" \
  --arg workloadBoundary "$workload_boundary" --arg brokerBoundary "$broker_boundary" --arg dataKms "$data_kms_key_arn" \
  --arg journalKms "$erasure_journal_kms_key" --arg journalBucket "$erasure_journal_bucket" \
  --arg rdsSecret "$rds_master_secret_arn" --arg documentSecret "$document_store_secret_arn" \
  --argjson databaseSecrets "$database_secret_arns" --arg managedPolicy "$managed_execution_policy_arn" '{
    accountId:$account,region:$region,stateMachineArn:$machine,clusterArn:$cluster,
    roles:{stateMachine:$stateRole,brokerExecution:$brokerExec,brokerTask:$brokerTask,cloneExecution:$cloneExec,
      applicationExecution:$appExec,applicationTask:$appTask,verifierExecution:$verifierExec,verifierTask:$verifierTask},
    definitions:{broker:$brokerDef,clone:$cloneDef,application:$appDef,verifier:$verifierDef},
    workloadBoundaryArn:$workloadBoundary,brokerBoundaryArn:$brokerBoundary,dataKmsKeyArn:$dataKms,
    erasureJournalKmsKeyArn:$journalKms,erasureJournalBucket:$journalBucket,rdsMasterSecretArn:$rdsSecret,
    documentStoreSecretArn:$documentSecret,databaseSecretArns:$databaseSecrets,managedExecutionPolicyArn:$managedPolicy
  }' >"$iam_context_file"
python3 "$repository_root/scripts/aws/validate_restore_semantic_evidence.py" \
  --iam-contracts "$iam_contracts_file" --iam-context "$iam_context_file" >/dev/null || \
  fail "live semantic IAM trust/identity/attachment contracts drifted" 3

[[ $(aws s3api get-bucket-location --region "$region" --bucket "$bucket" --query LocationConstraint --output text) == "$region" ]] || fail "restored bucket region drifted" 3
ownership=$(aws s3api get-bucket-ownership-controls --region "$region" --bucket "$bucket" --output json)
jq -e '.OwnershipControls.Rules == [{ObjectOwnership:"BucketOwnerEnforced"}]' <<<"$ownership" >/dev/null || fail "restored bucket ownership mode drifted" 3
versioning=$(aws s3api get-bucket-versioning --region "$region" --bucket "$bucket" --output json)
jq -e '. == {Status:"Enabled"}' <<<"$versioning" >/dev/null || fail "restored bucket versioning drifted" 3
public_block=$(aws s3api get-public-access-block --region "$region" --bucket "$bucket" --output json)
jq -e '.PublicAccessBlockConfiguration == {BlockPublicAcls:true,IgnorePublicAcls:true,BlockPublicPolicy:true,RestrictPublicBuckets:true}' \
  <<<"$public_block" >/dev/null || fail "restored bucket public-access block drifted" 3
encryption=$(aws s3api get-bucket-encryption --region "$region" --bucket "$bucket" --output json)
jq -e --arg key "$data_kms_key_arn" '.ServerSideEncryptionConfiguration.Rules == [{
  ApplyServerSideEncryptionByDefault:{SSEAlgorithm:"aws:kms",KMSMasterKeyID:$key},BucketKeyEnabled:true}]' \
  <<<"$encryption" >/dev/null || fail "restored bucket encryption drifted" 3
bucket_policy=$(aws s3api get-bucket-policy --region "$region" --bucket "$bucket" --query Policy --output text)
jq -e --arg bucket "$bucket" --arg key "$data_kms_key_arn" '.Version == "2012-10-17" and
  ([.Statement[].Sid]|sort) == ["DenyInsecureTransport","DenyWrongRestoreKmsKey","DenyWrongRestoreObjectEncryption"] and
  any(.Statement[];.Sid == "DenyInsecureTransport" and .Effect == "Deny" and .Principal == "*" and .Action == "s3:*" and
    .Resource == ["arn:aws:s3:::"+$bucket,"arn:aws:s3:::"+$bucket+"/*"] and .Condition == {Bool:{"aws:SecureTransport":"false"}}) and
  any(.Statement[];.Sid == "DenyWrongRestoreObjectEncryption" and .Effect == "Deny" and .Principal == "*" and .Action == "s3:PutObject" and
    .Resource == "arn:aws:s3:::"+$bucket+"/*" and .Condition == {StringNotEquals:{"s3:x-amz-server-side-encryption":"aws:kms"}}) and
  any(.Statement[];.Sid == "DenyWrongRestoreKmsKey" and .Effect == "Deny" and .Principal == "*" and .Action == "s3:PutObject" and
    .Resource == "arn:aws:s3:::"+$bucket+"/*" and .Condition == {StringNotEquals:{"s3:x-amz-server-side-encryption-aws-kms-key-id":$key}})' \
  <<<"$bucket_policy" >/dev/null || fail "restored bucket deny policy drifted" 3
[[ $(aws s3api get-bucket-policy-status --region "$region" --bucket "$bucket" --query PolicyStatus.IsPublic --output text) == False ]] || fail "restored bucket policy is public" 3
bucket_tags=$(aws s3api get-bucket-tagging --region "$region" --bucket "$bucket" --output json)
jq -e --arg drill "$drill_id" '(.TagSet|from_entries) == {Application:"Job Seeker Copilot",CostCentre:"public-beta",
  Environment:"public-beta",ManagedBy:"RestoreDrill",RestoreDrillId:$drill}' <<<"$bucket_tags" >/dev/null || fail "restored bucket tags drifted" 3

lb=$(aws elbv2 describe-load-balancers --region "$region" --names jsc-public-beta-app --output json); lb_arn=$(jq -er '.LoadBalancers|if length == 1 and .[0].Scheme == "internet-facing" and .[0].State.Code == "active" then .[0].LoadBalancerArn else error("ALB") end' <<<"$lb")
listeners=$(aws elbv2 describe-listeners --region "$region" --load-balancer-arn "$lb_arn" --output json)
listener_arn=$(jq -er '[.Listeners[]|select(.Port == 443 and .Protocol == "HTTPS" and (.DefaultActions|length) == 1 and .DefaultActions[0].Type == "fixed-response" and .DefaultActions[0].FixedResponseConfig.StatusCode == "503")]|if length == 1 then .[0].ListenerArn else error("listener") end' <<<"$listeners")
listener_rules=$(aws elbv2 describe-rules --region "$region" --listener-arn "$listener_arn" --output json)
jq -e '(.Rules|length) == 1 and .Rules[0].IsDefault == true and .Rules[0].Actions[0].Type == "fixed-response" and .Rules[0].Actions[0].FixedResponseConfig.StatusCode == "503"' <<<"$listener_rules" >/dev/null || fail "public listener can forward" 3
service_arns=$(aws ecs list-services --region "$region" --cluster "$cluster_arn" --output json); desired=0; running=0; pending=0
while IFS= read -r service_arn; do [[ -n "$service_arn" ]] || continue; service=$(aws ecs describe-services --region "$region" --cluster "$cluster_arn" --services "$service_arn" --output json)
  jq -e '(.failures|length) == 0 and (.services|length) == 1' <<<"$service" >/dev/null || fail "service discovery failed" 3
  desired=$((desired + $(jq -er '.services[0].desiredCount' <<<"$service"))); running=$((running + $(jq -er '.services[0].runningCount' <<<"$service"))); pending=$((pending + $(jq -er '.services[0].pendingCount' <<<"$service")))
done < <(jq -r '.serviceArns[]?' <<<"$service_arns")
[[ "$desired" == 0 && "$running" == 0 && "$pending" == 0 ]] || fail "public fleet is not quiesced" 3

log_stream=$(jq -er '.verifierLogStream' <<<"$marker_json"); [[ "$log_stream" == "restore-semantic-verifier/restore-semantic-verifier/${verifier_task##*/}" ]] || fail "log stream is not verifier-task bound" 3
messages='[]'; token=''; pages=0
while :; do
  if [[ -n "$token" ]]; then page=$(aws logs get-log-events --region "$region" --log-group-name /jsc/public-beta/release-operator --log-stream-name "$log_stream" --start-from-head --next-token "$token" --output json)
  else page=$(aws logs get-log-events --region "$region" --log-group-name /jsc/public-beta/release-operator --log-stream-name "$log_stream" --start-from-head --output json); fi
  messages=$(jq -cn --argjson old "$messages" --argjson new "$(jq -c '[.events[].message]' <<<"$page")" '$old+$new'); next=$(jq -er '.nextForwardToken' <<<"$page")
  pages=$((pages + 1)); (( pages <= 100 )) || fail "log pagination exceeded bound" 3; [[ "$next" == "$token" ]] && break; token=$next
done
raw_lines=$(jq -c --arg prefix "$raw_prefix" '[.[]|select(contains($prefix))]' <<<"$messages"); [[ $(jq -r 'length' <<<"$raw_lines") == 1 ]] || fail "exactly one raw evidence line is required" 3
raw_line=$(jq -er '.[0]' <<<"$raw_lines"); [[ "$raw_line" == "$raw_prefix"* && "$raw_line" != *$'\n'* ]] || fail "raw evidence is not one exact line" 3
raw_b64=${raw_line#"$raw_prefix"}; [[ "$raw_b64" =~ ^[A-Za-z0-9+/]+={0,2}$ && ${#raw_b64} -le 65536 ]] || fail "raw base64 malformed" 3
new_temporary_file raw_file; printf '%s' "$raw_b64" | base64 --decode >"$raw_file" || fail "raw base64 decode failed" 3; raw_json=$(<"$raw_file")
jq -e --arg drill "$drill_id" --arg task "$verifier_task" --arg release "$release_id" --arg attestation "$release_attestation_id" --arg canary "$source_canary" \
  --arg source "$source_evidence_sha" --arg marker "$source_marker_sha" '.schemaVersion == "jsc-public-beta-restore-semantic-raw.v1" and .status == "RAW_VERIFIED" and
  .environment == "public-beta" and .drillId == $drill and .verifierTaskArn == $task and .releaseCandidate == {releaseId:$release,releaseAttestationId:$attestation} and
  .restoreSource == {canaryId:$canary,sourceEvidenceSha256:$source,sourceMarkerSha256:$marker} and (.localRuntimeAssertions|type == "object")' <<<"$raw_json" >/dev/null || fail "raw verifier binding invalid" 3

runtime=$(jq -cnS --arg clone "$clone_task" --arg source "$source_task" --arg replay "$replay_task" --arg cloneDef "$clone_definition" --arg appDef "$app_definition" \
  --arg verifierDef "$verifier_definition" --arg documentDigest "$document_digest" --arg operatorDigest "$operator_digest" --arg vpc "$vpc_id" --arg dbSg "$database_sg" \
  --arg semanticSg "$semantic_sg" --arg account "$account_id" --arg drill "$drill_id" --arg endpoint "$restored_endpoint" '{cloneTaskArn:$clone,
  sourceApplicationTaskArn:$source,replayApplicationTaskArn:$replay,cloneTaskDefinitionArn:$cloneDef,applicationTaskDefinitionArn:$appDef,
  verifierTaskDefinitionArn:$verifierDef,documentStoreImageDigest:$documentDigest,releaseOperatorImageDigest:$operatorDigest,vpcId:$vpc,
  restoreDatabaseSecurityGroupId:$dbSg,semanticSecurityGroupId:$semanticSg,restoredDatabaseArn:("arn:aws:rds:eu-west-2:"+$account+":db:jsc-public-beta-restore-"+$drill),
  restoredDatabaseEndpoint:$endpoint,applicationTasksUseDedicatedJournalOnlyRole:true,verifierHasNoJournalPut:true,cloneHasNoTaskRole:true,
  actualTaskImageDigestsVerified:true,securityCriticalTaskDefinitionContractsVerified:true,
  exactTaskTagsVerified:true,exactTaskLifecycleVerified:true}')
runtime_sha=$(printf '%s' "$runtime" | sha256sum | cut -d' ' -f1)
orchestration=$(jq -cnS --arg machine "$state_machine_arn" --arg execution "$execution_arn" --arg stateRole "$state_machine_role" --arg brokerTask "$broker_task" \
  --arg brokerDef "$broker_definition" --arg brokerExec "$broker_execution_role" --arg brokerRole "$broker_task_role" --arg digest "$operator_digest" --arg markerName "$marker_name" \
  --arg markerSha "$marker_sha" --arg binding "$expected_input_binding" --arg operation "$operation_id" --arg replay "$restore_replay_id" --arg replayDb "$replay_database" \
  --argjson attempt "$(jq -er '.attempt' <<<"$marker_json")" '{stateMachineArn:$machine,executionArn:$execution,executionStatus:"SUCCEEDED",stateMachineType:"STANDARD",
  stateMachineRoleArn:$stateRole,brokerTaskArn:$brokerTask,brokerTaskDefinitionArn:$brokerDef,brokerExecutionRoleArn:$brokerExec,brokerTaskRoleArn:$brokerRole,
  brokerImageDigest:$digest,brokerInjectedSecretCount:0,brokerTaskStoppedSuccessfully:true,
  securityCriticalStateMachineContractVerified:true,brokerRuntimeBindingsVerified:true,
  expectedIamBoundaryBindingsVerified:true,expectedInlinePolicyNamesAndActionsVerified:true,noDangerousIamActionsVerified:true,
  durableMarkerName:$markerName,durableMarkerSchemaVersion:"jsc-public-beta-restore-semantic-start-marker.v2",durableMarkerSha256:$markerSha,
  durableMarkerRetained:true,markerPhase:"COMPLETED",markerAttempt:$attempt,inputBindingSha256:$binding,operationId:$operation,restoreReplayId:$replay,replayDatabase:$replayDb}')
network=$(jq -cnS --arg vpc "$vpc_id" --arg db "$database_sg" --arg semantic "$semantic_sg" --arg broker "$broker_sg" --argjson subnets "$private_subnets" '{vpcId:$vpc,
  restoreDatabaseSecurityGroupId:$db,semanticSecurityGroupId:$semantic,brokerSecurityGroupId:$broker,privateSubnetIds:$subnets,staticRulesTerraformOwned:true,
  exactReviewedRuleTuplesVerified:true,securityGroupRuleCount:10,semanticDatabaseSecurityGroupRuleCount:7,brokerSecurityGroupRuleCount:3,
  restoreDatabaseIngressRuleCount:1,restoreDatabaseEgressRuleCount:0,semanticIngressRuleCount:1,semanticEgressRuleCount:5,restoreDatabasePublicIngressRuleCount:0,
  semanticEniCountBeforeStart:0,semanticEniCountAfterContainment:0,brokerEniCountAfterCompletion:0,restoredDatabasePubliclyAccessible:false,
  restoredDatabaseUsesOnlyRestoreSecurityGroup:true,semanticTasksUseOnlySemanticSecurityGroup:true,brokerTaskUsesOnlyBrokerSecurityGroup:true,taskPrivateSubnetBindingsVerified:true}')
public=$(jq -cnS '{publicEntrypointFixed503:true,applicationDesiredCount:0,runningApplicationTaskCount:0,pendingApplicationTaskCount:0,semanticTasksNotAttachedToPublicFleet:true}')
restore_control=$(jq -cnS '{restoreJobsExactBindingsVerified:true,restoredDatabaseExactControlsVerified:true,
  restoredBucketExactControlsVerified:true,restoreOwnershipTagsVerified:true}')
jq -nS --argjson raw "$raw_json" --argjson orchestration "$orchestration" --argjson runtime "$runtime" \
  --argjson network "$network" --argjson public "$public" --argjson restoreControl "$restore_control" '
  $raw|del(.localRuntimeAssertions)|.schemaVersion="jsc-public-beta-restore-semantic-observation.v1"|.status="VERIFIED"|
  .orchestrationBinding=$orchestration|.runtimeBinding=$runtime|.networkIsolation=$network|.publicSafety=$public|
  .restoreControlPlane=$restoreControl' >"$observation_output"
chmod 0600 "$observation_output"
python3 "$repository_root/scripts/aws/validate_restore_semantic_evidence.py" --evidence "$observation_output" --expected-account-id "$account_id" --expected-drill-id "$drill_id" \
  --expected-release-id "$release_id" --expected-release-attestation-id "$release_attestation_id" --expected-source-evidence-sha256 "$source_evidence_sha" \
  --expected-source-marker-sha256 "$source_marker_sha" --expected-document-store-image-digest "$document_digest" --expected-release-operator-image-digest "$operator_digest" \
  --expected-verifier-task-arn "$verifier_task" --expected-execution-arn "$execution_arn" --expected-marker-sha256 "$marker_sha" --expected-runtime-binding-sha256 "$runtime_sha"
echo "Restore semantic observation independently verified; permanent marker retained: $observation_output"
