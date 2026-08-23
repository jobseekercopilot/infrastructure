#!/bin/sh
set -eu

action=${1:-start}
region=${AWS_REGION:-}
account_id=${AWS_ACCOUNT_ID:-}
drill_id=${RESTORE_DRILL_ID:-}
release_id=${RELEASE_ID:-}
release_attestation_id=${RELEASE_ATTESTATION_ID:-}
source_canary_id=${RESTORE_SOURCE_CANARY_ID:-}
source_evidence_sha=${RESTORE_SOURCE_EVIDENCE_SHA256:-}
source_marker_sha=${RESTORE_SOURCE_MARKER_SHA256:-}
restore_start_evidence_sha=${RESTORE_START_EVIDENCE_SHA256:-}
rds_restore_job_id=${RDS_RESTORE_JOB_ID:-}
s3_restore_job_id=${S3_RESTORE_JOB_ID:-}
rds_recovery_point_arn=${RDS_RECOVERY_POINT_ARN:-}
s3_recovery_point_arn=${S3_RECOVERY_POINT_ARN:-}
restore_role_arn=${RESTORE_ROLE_ARN:-}
state_machine_execution_arn=${STATE_MACHINE_EXECUTION_ARN:-}

cluster_arn=${RESTORE_CLUSTER_ARN:-}
cluster_name=${RESTORE_CLUSTER_NAME:-}
vpc_id=${RESTORE_VPC_ID:-}
private_subnets_json=${RESTORE_PRIVATE_SUBNET_IDS_JSON:-}
data_subnets_json=${RESTORE_DATA_SUBNET_IDS_JSON:-}
data_kms_key_arn=${RESTORE_DATA_KMS_KEY_ARN:-}
database_subnet_group=${RESTORE_DB_SUBNET_GROUP_NAME:-}
database_parameter_group=${RESTORE_DB_PARAMETER_GROUP_NAME:-}
database_security_group=${RESTORE_DATABASE_SECURITY_GROUP_ID:-}
semantic_security_group=${RESTORE_SEMANTIC_SECURITY_GROUP_ID:-}
broker_security_group=${RESTORE_BROKER_SECURITY_GROUP_ID:-}
clone_task_definition=${RESTORE_CLONE_TASK_DEFINITION_ARN:-}
app_task_definition=${RESTORE_APP_TASK_DEFINITION_ARN:-}
verifier_task_definition=${RESTORE_VERIFIER_TASK_DEFINITION_ARN:-}
clone_execution_role=${RESTORE_CLONE_EXECUTION_ROLE_ARN:-}
app_execution_role=${RESTORE_APP_EXECUTION_ROLE_ARN:-}
app_task_role=${RESTORE_APP_TASK_ROLE_ARN:-}
verifier_execution_role=${RESTORE_VERIFIER_EXECUTION_ROLE_ARN:-}
verifier_task_role=${RESTORE_VERIFIER_TASK_ROLE_ARN:-}
document_store_image_digest=${DOCUMENT_STORE_IMAGE_DIGEST:-}
document_store_source_commit=${DOCUMENT_STORE_SOURCE_COMMIT:-}
release_operator_image_digest=${RELEASE_OPERATOR_IMAGE_DIGEST:-}
release_operator_source_commit=${RELEASE_OPERATOR_SOURCE_COMMIT:-}
broker_task_definition=${RESTORE_BROKER_TASK_DEFINITION_ARN:-}
broker_execution_role=${RESTORE_BROKER_EXECUTION_ROLE_ARN:-}
broker_task_role=${RESTORE_BROKER_TASK_ROLE_ARN:-}

marker_name="/jsc/public-beta/restore-semantic/${drill_id}/start"
source_marker_name=/jsc/public-beta/release/restore-source-canary
database="jsc-public-beta-restore-${drill_id}"
bucket="jsc-public-beta-restore-${account_id}-${drill_id}"
managed_by=RestoreSemanticVerification
children_started=false

fail() {
  echo "restore semantic broker refused: $1" >&2
  exit "${2:-2}"
}

case "$action" in start|contain) ;; *) fail "action must be start or contain" ;; esac
for command_name in aws base64 curl cut date jq mktemp sha256sum sort tr wc; do
  command -v "$command_name" >/dev/null || fail "missing required command: $command_name"
done
[ "$region" = eu-west-2 ] || fail "region must be eu-west-2"
case "$account_id" in *[!0-9]*|'') fail "account ID is malformed" ;; esac
[ "${#account_id}" -eq 12 ] || fail "account ID is malformed"
case "$drill_id" in *[!a-z0-9-]*|'') fail "drill ID is malformed" ;; esac
[ "${#drill_id}" -ge 8 ] && [ "${#drill_id}" -le 32 ] || fail "drill ID is malformed"
case "$drill_id" in -*|*-) fail "drill ID is malformed" ;; esac
[ "$cluster_name" = jsc-public-beta ] || fail "cluster name is out of scope"
[ "$cluster_arn" = "arn:aws:ecs:${region}:${account_id}:cluster/${cluster_name}" ] || fail "cluster ARN is out of scope"
printf '%s' "$semantic_security_group" | jq -eR 'test("^sg-[0-9a-f]{8,17}$")' >/dev/null || \
  fail "semantic SG binding is malformed"

task_tags=$(jq -cnS --arg drill "$drill_id" --arg managed "$managed_by" '[
  {key:"Application",value:"Job Seeker Copilot"},
  {key:"Environment",value:"public-beta"},
  {key:"ManagedBy",value:$managed},
  {key:"RestoreDrillId",value:$drill}
]')

task_matches_drill() {
  task=$1
  tags=$(aws ecs list-tags-for-resource --region "$region" --resource-arn "$task" --output json)
  printf '%s' "$tags" | jq -e --arg drill "$drill_id" --arg managed "$managed_by" '
    (.tags | from_entries) as $tags |
    $tags.Application == "Job Seeker Copilot" and $tags.Environment == "public-beta" and
    $tags.ManagedBy == $managed and $tags.RestoreDrillId == $drill and
    ($tags | keys | sort) == ["Application","Environment","ManagedBy","RestoreDrillId"]
  ' >/dev/null
}

marker_tags_are_exact() {
  tags=$(aws ssm list-tags-for-resource --region "$region" --resource-type Parameter \
    --resource-id "$marker_name" --output json) || return 1
  printf '%s' "$tags" | jq -e --arg drill "$drill_id" --arg managed "$managed_by" '
    (.TagList | from_entries) == {Application:"Job Seeker Copilot",Environment:"public-beta",
      ManagedBy:$managed,RestoreDrillId:$drill}
  ' >/dev/null
}

contain_children() {
  recorded_tasks=
  marker_parse_failed=false
  if marker=$(aws ssm get-parameter --region "$region" --name "$marker_name" --query Parameter.Value --output text 2>/dev/null); then
    if ! marker_tags_are_exact; then
      echo "restore semantic broker containment found drifted durable-marker ownership tags" >&2
      marker_parse_failed=true
    fi
    if ! printf '%s' "$marker" | jq -e --arg account "$account_id" '
      (.childTasks // {}) as $tasks |
      ($tasks | type) == "object" and
      (($tasks | keys) - ["clone","sourceApplication","replayApplication","verifier"] | length) == 0 and
      all($tasks[]?; type == "string" and
        test("^arn:aws:ecs:eu-west-2:"+$account+":task/jsc-public-beta/[0-9a-f]{32}$"))
    ' >/dev/null; then
      echo "restore semantic broker containment could not parse the owned marker" >&2
      recorded_tasks=
      marker_parse_failed=true
    else
      recorded_tasks=$(printf '%s' "$marker" | jq -r '(.childTasks // {})[]?')
    fi
  fi
  candidate_tasks=$recorded_tasks
  for desired in PENDING RUNNING; do
    listing=$(aws ecs list-tasks --region "$region" --cluster "$cluster_arn" --desired-status "$desired" --output json)
    candidate_tasks="$candidate_tasks
$(printf '%s' "$listing" | jq -r '.taskArns[]?')"
  done
  # Marker-recorded ARNs are authoritative. Missing/drifted tags are a failure,
  # never a reason to silently skip a potentially live child.
  for task in $recorded_tasks; do
    [ -n "$task" ] || continue
    if ! task_matches_drill "$task"; then
      echo "restore semantic broker containment found a marker-recorded child with missing/drifted tags: $task" >&2
      return 1
    fi
  done

  tasks_to_wait=
  for task in $(printf '%s\n' "$candidate_tasks" | sort -u); do
    [ -n "$task" ] || continue
    if task_matches_drill "$task"; then
      described=$(aws ecs describe-tasks --region "$region" --cluster "$cluster_arn" --tasks "$task" --output json)
      [ "$(printf '%s' "$described" | jq -r '.tasks[0].lastStatus // "MISSING"')" != MISSING ] || {
        echo "restore semantic broker containment lost a recorded task: $task" >&2
        return 1
      }
      family=$(printf '%s' "$described" | jq -er '.tasks[0].group')
      case "$family" in
        family:jsc-public-beta-restore-semantic-clone|\
        family:jsc-public-beta-restore-semantic-document-store|\
        family:jsc-public-beta-restore-semantic-verifier) ;;
        *) echo "restore semantic broker containment found out-of-scope family: $family" >&2; return 1 ;;
      esac
      if [ "$(printf '%s' "$described" | jq -r '.tasks[0].lastStatus')" != STOPPED ]; then
        aws ecs stop-task --region "$region" --cluster "$cluster_arn" --task "$task" \
          --reason "bounded restore semantic broker containment" >/dev/null || return 1
      fi
      tasks_to_wait="$tasks_to_wait $task"
    fi
  done

  # StopTask is asynchronous. Poll exact ARNs for a shared eight-minute bound,
  # bounded below the 15-minute containment state timeout.
  containment_deadline=$(( $(date +%s) + 480 ))
  for task in $tasks_to_wait; do
    while :; do
      described=$(aws ecs describe-tasks --region "$region" --cluster "$cluster_arn" --tasks "$task" --output json) || return 1
      last_status=$(printf '%s' "$described" | jq -er '
        if (.failures | length) == 0 and (.tasks | length) == 1 then .tasks[0].lastStatus
        else error("contained task missing") end') || return 1
      [ "$last_status" != STOPPED ] || break
      [ "$(date +%s)" -lt "$containment_deadline" ] || {
        echo "restore semantic broker containment timed out waiting for STOPPED: $task" >&2
        return 1
      }
      sleep 5
    done
  done

  for desired in PENDING RUNNING; do
    listing=$(aws ecs list-tasks --region "$region" --cluster "$cluster_arn" --desired-status "$desired" --output json)
    for task in $(printf '%s' "$listing" | jq -r '.taskArns[]?'); do
      if task_matches_drill "$task"; then
        echo "restore semantic broker containment left a $desired child: $task" >&2
        return 1
      fi
    done
  done


  # ENI deletion can lag task STOPPED. Prove the semantic SG is detached from
  # every ENI before containment succeeds.
  eni_deadline=$(( $(date +%s) + 180 ))
  while :; do
    eni_count=$(aws ec2 describe-network-interfaces --region "$region" \
      --filters Name=group-id,Values="$semantic_security_group" --output json | jq -er '.NetworkInterfaces | length') || return 1
    [ "$eni_count" -ne 0 ] || break
    [ "$(date +%s)" -lt "$eni_deadline" ] || {
      echo "restore semantic broker containment left $eni_count semantic ENI(s)" >&2
      return 1
    }
    sleep 5
  done
  [ "$marker_parse_failed" = false ] || {
    echo "restore semantic broker contained discoverable children but the durable marker remains malformed" >&2
    return 1
  }
}

if [ "$action" = contain ]; then
  contain_children || fail "containment could not stop and prove every exact child" 3
  echo "restore semantic broker containment completed for exact drill $drill_id"
  exit 0
fi

printf '%s' "$data_subnets_json" | jq -e '
  type == "array" and length == 2 and all(.[]; type == "string" and test("^subnet-[0-9a-f]{8,17}$")) and
  (unique | length) == 2
' >/dev/null || fail "data subnet binding is malformed"
[ "$data_kms_key_arn" != "arn:aws:kms:${region}:000000000000:key/00000000-0000-0000-0000-000000000000" ] || \
  fail "data KMS key is still the invalid sentinel"
printf '%s' "$data_kms_key_arn" | jq -eR --arg account "$account_id" '
  test("^arn:aws:kms:eu-west-2:"+$account+":key/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
' >/dev/null || fail "data KMS key ARN is malformed or out of scope"
[ "$database_subnet_group" = jsc-public-beta-postgres ] || fail "database subnet group is out of scope"
printf '%s' "$database_parameter_group" | jq -eR '
  test("^jsc-public-beta-postgres15-[a-z0-9-]+$")
' >/dev/null || fail "database parameter group is out of scope"

case "$release_id" in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) fail "release ID is malformed" ;;
esac
for digest in "$release_attestation_id" "$source_evidence_sha" "$source_marker_sha" "$restore_start_evidence_sha"; do
  case "$digest" in *[!0-9a-f]*|'') fail "evidence digest is malformed" ;; esac
  [ "${#digest}" -eq 64 ] || fail "evidence digest is malformed"
done
case "$source_canary_id" in *[!a-z0-9-]*|'') fail "source canary ID is malformed" ;; esac
[ "${#source_canary_id}" -ge 8 ] && [ "${#source_canary_id}" -le 32 ] || fail "source canary ID is malformed"
for job_id in "$rds_restore_job_id" "$s3_restore_job_id"; do
  printf '%s' "$job_id" | jq -eR 'test("^[A-Za-z0-9-]{8,128}$")' >/dev/null || fail "restore job binding is malformed"
done
printf '%s' "$rds_recovery_point_arn" | jq -eR --arg account "$account_id" '
  test("^arn:aws:rds:eu-west-2:"+$account+":snapshot:awsbackup:job-[A-Za-z0-9-]+$")' >/dev/null || \
  fail "RDS recovery point is out of scope"
printf '%s' "$s3_recovery_point_arn" | jq -eR --arg account "$account_id" '
  test("^arn:aws:backup:eu-west-2:"+$account+":recovery-point:[A-Za-z0-9-]+$")' >/dev/null || \
  fail "S3 recovery point is out of scope"
[ "$restore_role_arn" = "arn:aws:iam::${account_id}:role/jsc-public-beta-backup-restore" ] || \
  fail "restore role is out of scope"
printf '%s' "$state_machine_execution_arn" | jq -eR --arg account "$account_id" '
  test("^arn:aws:states:eu-west-2:"+$account+":execution:jsc-public-beta-restore-semantic:[A-Za-z0-9_-]{1,80}$")
' >/dev/null || fail "state-machine execution ARN is out of scope"

printf '%s\n%s\n%s\n%s\n' "$vpc_id" "$database_security_group" "$semantic_security_group" \
  "$broker_security_group" | jq -eRs '
    split("\n")[:-1] as $ids |
    ($ids | length) == 4 and
    ($ids[0] | test("^vpc-[0-9a-f]{8,17}$")) and
    all($ids[1:]; test("^sg-[0-9a-f]{8,17}$"))
  ' >/dev/null || fail "static network binding is malformed"
[ "$database_security_group" != "$semantic_security_group" ] && \
  [ "$database_security_group" != "$broker_security_group" ] && \
  [ "$semantic_security_group" != "$broker_security_group" ] || fail "network groups are not distinct"
printf '%s' "$private_subnets_json" | jq -e '
  type == "array" and length == 2 and (unique | length) == 2 and
  all(.[]; type == "string" and test("^subnet-[0-9a-f]{8,17}$"))
' >/dev/null || fail "private subnet binding is malformed"

printf '%s\n%s\n%s\n' "$clone_task_definition" "$app_task_definition" "$verifier_task_definition" | jq -eRs \
  --arg account "$account_id" '
    split("\n")[:-1] as $a |
    ($a | length == 3 and (unique | length) == 3) and
    ($a[0] | test("^arn:aws:ecs:eu-west-2:"+$account+":task-definition/jsc-public-beta-restore-semantic-clone:[1-9][0-9]*$")) and
    ($a[1] | test("^arn:aws:ecs:eu-west-2:"+$account+":task-definition/jsc-public-beta-restore-semantic-document-store:[1-9][0-9]*$")) and
    ($a[2] | test("^arn:aws:ecs:eu-west-2:"+$account+":task-definition/jsc-public-beta-restore-semantic-verifier:[1-9][0-9]*$"))
  ' >/dev/null || fail "child task-definition binding is malformed"
printf '%s' "$broker_task_definition" | jq -eR --arg account "$account_id" '
  test("^arn:aws:ecs:eu-west-2:"+$account+":task-definition/jsc-public-beta-restore-semantic-broker:[1-9][0-9]*$")
' >/dev/null || fail "broker task-definition binding is malformed"
printf '%s\n%s\n' "$broker_execution_role" "$broker_task_role" | jq -eRs --arg account "$account_id" '
  split("\n")[:-1] == [
    "arn:aws:iam::"+$account+":role/jsc-public-beta-restore-semantic-broker-execution",
    "arn:aws:iam::"+$account+":role/jsc-public-beta-restore-semantic-broker-task"
  ]
' >/dev/null || fail "broker role binding is malformed"
printf '%s\n%s\n%s\n%s\n%s\n' "$clone_execution_role" "$app_execution_role" "$app_task_role" \
  "$verifier_execution_role" "$verifier_task_role" | jq -eRs --arg account "$account_id" '
  split("\n")[:-1] == [
    "arn:aws:iam::"+$account+":role/jsc-public-beta-restore-semantic-clone-execution",
    "arn:aws:iam::"+$account+":role/jsc-public-beta-restore-semantic-document-store-execution",
    "arn:aws:iam::"+$account+":role/jsc-public-beta-restore-semantic-document-store-task",
    "arn:aws:iam::"+$account+":role/jsc-public-beta-restore-semantic-verifier-execution",
    "arn:aws:iam::"+$account+":role/jsc-public-beta-restore-semantic-verifier-task"
  ]
' >/dev/null || fail "child role binding is malformed"
for digest in "$document_store_image_digest" "$release_operator_image_digest"; do
  printf '%s' "$digest" | jq -eR 'test("^sha256:[0-9a-f]{64}$")' >/dev/null || fail "image digest is malformed"
done
printf '%s\n%s\n' "$document_store_source_commit" "$release_operator_source_commit" | jq -eRs '
  split("\n")[:-1] | length == 2 and all(.[]; test("^[0-9a-f]{40}$"))
' >/dev/null || fail "image source revision binding is malformed"

seed=$(printf '%s:%s:%s' "$drill_id" "$release_id" "$source_marker_sha" | sha256sum | cut -d' ' -f1)
replay_seed=$(printf 'replay:%s:%s:%s' "$drill_id" "$release_id" "$source_marker_sha" | sha256sum | cut -d' ' -f1)
operation_id="7e57c0de-$(printf '%s' "$seed" | cut -c1-4)-4$(printf '%s' "$seed" | cut -c5-7)-8$(printf '%s' "$seed" | cut -c8-10)-$(printf '%s' "$seed" | cut -c11-22)"
restore_replay_id="$(printf '%s' "$replay_seed" | cut -c1-8)-$(printf '%s' "$replay_seed" | cut -c9-12)-4$(printf '%s' "$replay_seed" | cut -c13-15)-8$(printf '%s' "$replay_seed" | cut -c16-18)-$(printf '%s' "$replay_seed" | cut -c19-30)"
replay_database="restore_replay_$(printf '%s' "$seed" | cut -c1-12)"
input_binding=$(jq -cnS --arg execution "$state_machine_execution_arn" --arg drill "$drill_id" \
  --arg release "$release_id" --arg attestation "$release_attestation_id" --arg canary "$source_canary_id" \
  --arg source "$source_evidence_sha" --arg marker "$source_marker_sha" --arg start "$restore_start_evidence_sha" \
  --arg rds "$rds_restore_job_id" --arg s3 "$s3_restore_job_id" --arg rdsRecovery "$rds_recovery_point_arn" \
  --arg s3Recovery "$s3_recovery_point_arn" --arg restoreRole "$restore_role_arn" --arg operation "$operation_id" \
  --arg replay "$restore_replay_id" --arg replayDb "$replay_database" '{executionArn:$execution,drillId:$drill,releaseId:$release,
    releaseAttestationId:$attestation,sourceCanaryId:$canary,sourceEvidenceSha256:$source,
    sourceMarkerSha256:$marker,restoreStartEvidenceSha256:$start,rdsRestoreJobId:$rds,
    s3RestoreJobId:$s3,rdsRecoveryPointArn:$rdsRecovery,s3RecoveryPointArn:$s3Recovery,
    restoreRoleArn:$restoreRole,operationId:$operation,restoreReplayId:$replay,replayDatabase:$replayDb}' | sha256sum | cut -d' ' -f1)

marker_exists=false
if existing_marker=$(aws ssm get-parameter --region "$region" --name "$marker_name" --query Parameter.Value --output text 2>/dev/null); then
  marker_exists=true
  marker_tags_are_exact || fail "durable marker ownership tags are missing or drifted" 3
  printf '%s' "$existing_marker" | jq -e --arg execution "$state_machine_execution_arn" \
    --arg binding "$input_binding" --arg operation "$operation_id" --arg replay "$restore_replay_id" \
    --arg replayDb "$replay_database" '
      .schemaVersion == "jsc-public-beta-restore-semantic-start-marker.v2" and
      .executionArn == $execution and .inputBindingSha256 == $binding and
      .operationId == $operation and .restoreReplayId == $replay and .replayDatabase == $replayDb and
      (.attempt | type == "number" and . >= 1 and . <= 3 and floor == .) and
      ((.childTasks // {}) | type == "object") and
      (.phase == "INITIALIZED" or .phase == "CHILDREN_RUNNING" or .phase == "COMPLETED")
    ' >/dev/null || fail "another execution or input already owns this drill marker" 3
  if [ "$(printf '%s' "$existing_marker" | jq -r .phase)" = COMPLETED ]; then
    echo "restore semantic broker already completed this exact execution"
    exit 0
  fi
  current_marker=$existing_marker
  [ "$(printf '%s' "$current_marker" | jq -r '(.childTasks // {}) | length')" -eq 0 ] || children_started=true
else
  initial_marker=$(jq -cnS --arg execution "$state_machine_execution_arn" --arg binding "$input_binding" \
    --arg drill "$drill_id" --arg operation "$operation_id" --arg replay "$restore_replay_id" --arg replayDb "$replay_database" \
    --arg created "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '{
      schemaVersion:"jsc-public-beta-restore-semantic-start-marker.v2",phase:"INITIALIZED",attempt:1,childTasks:{},
      executionArn:$execution,inputBindingSha256:$binding,drillId:$drill,operationId:$operation,
      restoreReplayId:$replay,replayDatabase:$replayDb,createdAt:$created,lastAttemptStartedAt:$created
    }')
  aws ssm put-parameter --region "$region" --name "$marker_name" --type String \
    --value "$initial_marker" --tags Key=Application,Value="Job Seeker Copilot" \
    Key=Environment,Value=public-beta Key=ManagedBy,Value="$managed_by" Key=RestoreDrillId,Value="$drill_id" >/dev/null
  marker_tags_are_exact || fail "new durable marker ownership tags were not persisted exactly" 3
  current_marker=$initial_marker
fi

on_exit() {
  status=$?
  trap - EXIT HUP INT TERM
  rm -f -- ${clone_overrides:-} ${source_overrides:-} ${replay_overrides:-} ${verifier_overrides:-} 2>/dev/null || true
  if [ "$children_started" = true ]; then
    if ! contain_children; then
      echo "restore semantic broker failed to contain every child" >&2
      [ "$status" -ne 0 ] || status=3
    fi
  fi
  exit "$status"
}
trap on_exit EXIT
# Convert signals to an explicit non-zero exit; the single EXIT handler remains
# the only cleanup/containment path and therefore cannot be replaced by a
# signal-specific trap with an accidentally successful status.
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ "$marker_exists" = true ]; then
  prior_attempt=$(printf '%s' "$current_marker" | jq -er '.attempt')
  [ "$prior_attempt" -lt 3 ] || fail "durable drill retry limit is exhausted; a new drill ID is required" 3
  # A process may fail after RunTask succeeds but before the child ARN is
  # appended to the marker. Scan the exact drill tags even when childTasks is
  # empty; recorded ARNs alone are not a complete redrive containment proof.
  contain_children || fail "prior attempt children could not be contained before redrive" 3
  children_started=false
  attempt=$((prior_attempt + 1))
  current_marker=$(printf '%s' "$current_marker" | jq -cS --argjson attempt "$attempt" \
    --arg started "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
      .phase="INITIALIZED" | .attempt=$attempt | .lastAttemptStartedAt=$started | .childTasks={} |
      del(.completedAt,.verifierLogStream,.runtimeBinding,.network,.publicSafety)')
  aws ssm put-parameter --region "$region" --name "$marker_name" --type String --overwrite \
    --value "$current_marker" >/dev/null
else
  attempt=1
fi

assert_public_dark() {
  load_balancer=$(aws elbv2 describe-load-balancers --region "$region" --names jsc-public-beta-app --output json)
  load_balancer_arn=$(printf '%s' "$load_balancer" | jq -er '
    .LoadBalancers | if length == 1 and .[0].Scheme == "internet-facing" and
      .[0].State.Code == "active" then .[0].LoadBalancerArn else error("ALB mismatch") end')
  listeners=$(aws elbv2 describe-listeners --region "$region" --load-balancer-arn "$load_balancer_arn" --output json)
  https_listener=$(printf '%s' "$listeners" | jq -er '
    [.Listeners[] | select(.Port == 443 and .Protocol == "HTTPS" and
      (.DefaultActions | length) == 1 and .DefaultActions[0].Type == "fixed-response" and
      .DefaultActions[0].FixedResponseConfig.StatusCode == "503")] |
    if length == 1 then .[0].ListenerArn else error("fixed-503 listener mismatch") end')
  rules=$(aws elbv2 describe-rules --region "$region" --listener-arn "$https_listener" --output json)
  printf '%s' "$rules" | jq -e '
    (.Rules | length) == 1 and .Rules[0].IsDefault == true and
    (.Rules[0].Actions | length) == 1 and .Rules[0].Actions[0].Type == "fixed-response" and
    .Rules[0].Actions[0].FixedResponseConfig.StatusCode == "503"
  ' >/dev/null || fail "public HTTPS listener can forward traffic" 3
  service_arns=$(aws ecs list-services --region "$region" --cluster "$cluster_arn" --output json)
  printf '%s' "$service_arns" | jq -r '.serviceArns[]?' | while IFS= read -r service_arn; do
    [ -n "$service_arn" ] || continue
    service=${service_arn##*/}
    status=$(aws ecs describe-services --region "$region" --cluster "$cluster_arn" --services "$service" --output json)
    printf '%s' "$status" | jq -e '
      (.failures | length) == 0 and (.services | length) == 1 and
      .services[0].desiredCount == 0 and .services[0].runningCount == 0 and .services[0].pendingCount == 0
    ' >/dev/null || fail "public application service is not quiesced: $service" 3
  done
}

assert_broker_network() {
  [ -n "${ECS_CONTAINER_METADATA_URI_V4:-}" ] || fail "ECS task metadata is unavailable"
  metadata=$(curl --fail --silent --show-error --connect-timeout 5 --max-time 10 "${ECS_CONTAINER_METADATA_URI_V4}/task")
  broker_task_arn=$(printf '%s' "$metadata" | jq -er --arg account "$account_id" '
    .TaskARN | select(test("^arn:aws:ecs:eu-west-2:"+$account+":task/jsc-public-beta/[0-9a-f]{32}$"))')
  described=$(aws ecs describe-tasks --region "$region" --cluster "$cluster_arn" --tasks "$broker_task_arn" --output json)
  printf '%s' "$described" | jq -e --arg definition "$broker_task_definition" \
    --arg exec "$broker_execution_role" --arg task "$broker_task_role" --arg execution "$state_machine_execution_arn" \
    --arg drill "$drill_id" --arg release "$release_id" --arg attestation "$release_attestation_id" \
    --arg canary "$source_canary_id" --arg source "$source_evidence_sha" --arg marker "$source_marker_sha" \
    --arg start "$restore_start_evidence_sha" --arg rds "$rds_restore_job_id" --arg s3 "$s3_restore_job_id" \
    --arg rdsRecovery "$rds_recovery_point_arn" --arg s3Recovery "$s3_recovery_point_arn" \
    --arg restoreRole "$restore_role_arn" '
    (.failures | length) == 0 and (.tasks | length) == 1 and
    .tasks[0].taskDefinitionArn == $definition and .tasks[0].group == "jsc-restore-semantic-broker" and
    .tasks[0].launchType == "EC2" and .tasks[0].startedBy == "AWS Step Functions" and
    .tasks[0].overrides.executionRoleArn == $exec and .tasks[0].overrides.taskRoleArn == $task and
    (.tasks[0].overrides.containerOverrides | length) == 1 and
    .tasks[0].overrides.containerOverrides[0].name == "restore-semantic-broker" and
    .tasks[0].overrides.containerOverrides[0].command == ["/opt/jsc/run-restore-semantic-broker.sh","start"] and
    (.tasks[0].overrides.containerOverrides[0].environment | length) == 16 and
    ([.tasks[0].overrides.containerOverrides[0].environment[].name] | unique | length) == 16 and
    (.tasks[0].overrides.containerOverrides[0].environment | from_entries) == {
      RESTORE_BROKER_TASK_DEFINITION_ARN:$definition,
      RESTORE_BROKER_EXECUTION_ROLE_ARN:$exec,
      RESTORE_BROKER_TASK_ROLE_ARN:$task,
      RESTORE_DRILL_ID:$drill,RELEASE_ID:$release,RELEASE_ATTESTATION_ID:$attestation,
      RESTORE_SOURCE_CANARY_ID:$canary,RESTORE_SOURCE_EVIDENCE_SHA256:$source,
      RESTORE_SOURCE_MARKER_SHA256:$marker,RESTORE_START_EVIDENCE_SHA256:$start,
      RDS_RESTORE_JOB_ID:$rds,S3_RESTORE_JOB_ID:$s3,RDS_RECOVERY_POINT_ARN:$rdsRecovery,
      S3_RECOVERY_POINT_ARN:$s3Recovery,RESTORE_ROLE_ARN:$restoreRole,
      STATE_MACHINE_EXECUTION_ARN:$execution
    }
  ' >/dev/null || fail "state machine did not run the exact broker task-definition revision" 3
  broker_tags=$(aws ecs list-tags-for-resource --region "$region" --resource-arn "$broker_task_arn" --output json)
  printf '%s' "$broker_tags" | jq -e --arg drill "$drill_id" '
    (.tags | from_entries) == {Application:"Job Seeker Copilot",Environment:"public-beta",
      ManagedBy:"RestoreSemanticBroker",RestoreDrillId:$drill}
  ' >/dev/null || fail "state machine did not apply the exact broker ownership tags" 3
  broker_eni=$(printf '%s' "$described" | jq -er '
    [.tasks[0].attachments[]?.details[]? | select(.name == "networkInterfaceId") | .value] |
    if length == 1 then .[0] else error("broker ENI mismatch") end')
  eni=$(aws ec2 describe-network-interfaces --region "$region" --network-interface-ids "$broker_eni" --output json)
  printf '%s' "$eni" | jq -e --arg sg "$broker_security_group" --argjson subnets "$private_subnets_json" '
    .NetworkInterfaces[0] as $eni |
    (.NetworkInterfaces | length) == 1 and [$eni.Groups[].GroupId] == [$sg] and
    ($subnets | index($eni.SubnetId)) != null and ($eni.Association.PublicIp // null) == null
  ' >/dev/null || fail "state machine did not hard-bind the broker ENI" 3
  broker_private_ip=$(printf '%s' "$eni" | jq -er '.NetworkInterfaces[0].PrivateIpAddress')
  broker_subnet_id=$(printf '%s' "$eni" | jq -er '.NetworkInterfaces[0].SubnetId')
  broker_definition=$(aws ecs describe-task-definition --region "$region" --task-definition "$broker_task_definition" \
    --include TAGS --output json)
  printf '%s' "$broker_definition" | jq -e --arg definition "$broker_task_definition" \
    --arg exec "$broker_execution_role" --arg task "$broker_task_role" --arg image "$release_operator_image_digest" \
    --arg account "$account_id" --arg region "$region" --arg cluster "$cluster_arn" --arg clusterName "$cluster_name" \
    --arg vpc "$vpc_id" --arg privateSubnets "$private_subnets_json" --arg dataSubnets "$data_subnets_json" \
    --arg dataKms "$data_kms_key_arn" --arg subnetGroup "$database_subnet_group" \
    --arg parameterGroup "$database_parameter_group" --arg databaseSg "$database_security_group" \
    --arg semanticSg "$semantic_security_group" --arg brokerSg "$broker_security_group" \
    --arg cloneDefinition "$clone_task_definition" --arg appDefinition "$app_task_definition" \
    --arg verifierDefinition "$verifier_task_definition" --arg cloneExec "$clone_execution_role" \
    --arg appExec "$app_execution_role" --arg appTask "$app_task_role" \
    --arg verifierExec "$verifier_execution_role" --arg verifierTask "$verifier_task_role" \
    --arg documentImage "$document_store_image_digest" --arg documentCommit "$document_store_source_commit" \
    --arg operatorCommit "$release_operator_source_commit" '
    .taskDefinition.taskDefinitionArn == $definition and .taskDefinition.executionRoleArn == $exec and
    .taskDefinition.taskRoleArn == $task and .taskDefinition.networkMode == "awsvpc" and
    .taskDefinition.requiresCompatibilities == ["EC2"] and (.taskDefinition.containerDefinitions | length) == 1 and
    .taskDefinition.containerDefinitions[0].name == "restore-semantic-broker" and
    (.taskDefinition.containerDefinitions[0].image | endswith("@"+$image)) and
    .taskDefinition.containerDefinitions[0].command == ["/opt/jsc/run-restore-semantic-broker.sh","start"] and
    .taskDefinition.containerDefinitions[0].essential == true and
    .taskDefinition.containerDefinitions[0].cpu == 256 and .taskDefinition.containerDefinitions[0].memory == 512 and
    .taskDefinition.containerDefinitions[0].readonlyRootFilesystem == true and
    (.taskDefinition.containerDefinitions[0].secrets // []) == [] and
    (.taskDefinition.containerDefinitions[0].environment | length) == 25 and
    ([.taskDefinition.containerDefinitions[0].environment[].name] | unique | length) == 25 and
    (.taskDefinition.containerDefinitions[0].environment | from_entries) == {
      AWS_ACCOUNT_ID:$account,AWS_REGION:$region,RESTORE_CLUSTER_ARN:$cluster,RESTORE_CLUSTER_NAME:$clusterName,
      RESTORE_VPC_ID:$vpc,RESTORE_PRIVATE_SUBNET_IDS_JSON:$privateSubnets,
      RESTORE_DATA_SUBNET_IDS_JSON:$dataSubnets,RESTORE_DATA_KMS_KEY_ARN:$dataKms,
      RESTORE_DB_SUBNET_GROUP_NAME:$subnetGroup,RESTORE_DB_PARAMETER_GROUP_NAME:$parameterGroup,
      RESTORE_DATABASE_SECURITY_GROUP_ID:$databaseSg,RESTORE_SEMANTIC_SECURITY_GROUP_ID:$semanticSg,
      RESTORE_BROKER_SECURITY_GROUP_ID:$brokerSg,RESTORE_CLONE_TASK_DEFINITION_ARN:$cloneDefinition,
      RESTORE_APP_TASK_DEFINITION_ARN:$appDefinition,RESTORE_VERIFIER_TASK_DEFINITION_ARN:$verifierDefinition,
      RESTORE_CLONE_EXECUTION_ROLE_ARN:$cloneExec,RESTORE_APP_EXECUTION_ROLE_ARN:$appExec,
      RESTORE_APP_TASK_ROLE_ARN:$appTask,RESTORE_VERIFIER_EXECUTION_ROLE_ARN:$verifierExec,
      RESTORE_VERIFIER_TASK_ROLE_ARN:$verifierTask,DOCUMENT_STORE_IMAGE_DIGEST:$documentImage,
      DOCUMENT_STORE_SOURCE_COMMIT:$documentCommit,RELEASE_OPERATOR_IMAGE_DIGEST:$image,
      RELEASE_OPERATOR_SOURCE_COMMIT:$operatorCommit
    } and
    (.tags | from_entries) == {Application:"Job Seeker Copilot",Environment:"public-beta",ManagedBy:"Terraform",
      Repository:"jobseekercopilot/infrastructure",CostCentre:"public-beta",Purpose:"restore-semantic-broker",
      ImageDigest:$image,SourceCommit:$operatorCommit}
  ' >/dev/null || fail "broker task definition escaped its exact secret-free image/role/command contract" 3
  state_machine_arn="arn:aws:states:${region}:${account_id}:stateMachine:jsc-public-beta-restore-semantic"
}

assert_restore_control_plane() {
  for binding in "RDS:$rds_restore_job_id:$rds_recovery_point_arn:arn:aws:rds:${region}:${account_id}:db:jsc-public-beta-postgres" \
    "S3:$s3_restore_job_id:$s3_recovery_point_arn:arn:aws:s3:::jsc-public-beta-documents-${account_id}"; do
    type=${binding%%:*}
    remainder=${binding#*:}; job=${remainder%%:*}; remainder=${remainder#*:}
    if [ "$type" = RDS ]; then recovery=$rds_recovery_point_arn; source="arn:aws:rds:${region}:${account_id}:db:jsc-public-beta-postgres"
    else recovery=$s3_recovery_point_arn; source="arn:aws:s3:::jsc-public-beta-documents-${account_id}"; fi
    if [ "$type" = RDS ]; then destination="arn:aws:rds:${region}:${account_id}:db:${database}"; else destination="arn:aws:s3:::${bucket}"; fi
    observed=$(aws backup describe-restore-job --region "$region" --restore-job-id "$job" --output json)
    printf '%s' "$observed" | jq -e --arg account "$account_id" --arg job "$job" --arg type "$type" \
      --arg destination "$destination" --arg recovery "$recovery" --arg role "$restore_role_arn" '
      .AccountId == $account and .RestoreJobId == $job and .ResourceType == $type and
      .Status == "COMPLETED" and .CreatedResourceArn == $destination and .RecoveryPointArn == $recovery and
      .IamRoleArn == $role and .CompletionDate != null
    ' >/dev/null || fail "$type restore job is not complete and destination-bound" 3
  done
  rds=$(aws rds describe-db-instances --region "$region" --db-instance-identifier "$database" --output json)
  restored_database_arn="arn:aws:rds:${region}:${account_id}:db:${database}"
  restored_endpoint=$(printf '%s' "$rds" | jq -er --arg sg "$database_security_group" --arg arn "$restored_database_arn" \
    --arg vpc "$vpc_id" --arg kms "$data_kms_key_arn" --arg subnetGroup "$database_subnet_group" \
    --arg parameterGroup "$database_parameter_group" --argjson subnets "$data_subnets_json" '
    .DBInstances | if length == 1 and .[0].DBInstanceArn == $arn and .[0].DBInstanceStatus == "available" and
      .[0].PubliclyAccessible == false and .[0].Endpoint.Port == 5432 and .[0].Port == 5432 and
      .[0].Engine == "postgres" and (.[0].EngineVersion | test("^15\\.")) and
      .[0].StorageEncrypted == true and .[0].KmsKeyId == $kms and
      .[0].MultiAZ == false and .[0].DeletionProtection == false and
      .[0].DBSubnetGroup.DBSubnetGroupName == $subnetGroup and
      .[0].DBSubnetGroup.SubnetGroupStatus == "Complete" and .[0].DBSubnetGroup.VpcId == $vpc and
      ([.[0].DBSubnetGroup.Subnets[].SubnetIdentifier] | sort) == ($subnets | sort) and
      .[0].DBParameterGroups == [{DBParameterGroupName:$parameterGroup,ParameterApplyStatus:"in-sync"}] and
      ([.[0].VpcSecurityGroups[].VpcSecurityGroupId] == [$sg])
    then .[0].Endpoint.Address else error("restored RDS mismatch") end')
  all_rds=$(aws rds describe-db-instances --region "$region" --output json)
  printf '%s' "$all_rds" | jq -e --arg arn "$restored_database_arn" --arg sg "$database_security_group" '
    [.DBInstances[] | select(any(.VpcSecurityGroups[]?; .VpcSecurityGroupId == $sg)) | .DBInstanceArn] == [$arn]
  ' >/dev/null || fail "restore database SG is attached outside this exact drill" 3
  rds_tags=$(aws rds list-tags-for-resource --region "$region" --resource-name "$restored_database_arn" --output json)
  printf '%s' "$rds_tags" | jq -e --arg drill "$drill_id" '
    (.TagList | from_entries | with_entries(select(.key|startswith("aws:")|not))) == {
      Application:"Job Seeker Copilot",CostCentre:"public-beta",Environment:"public-beta",
      ManagedBy:"RestoreDrill",RestoreDrillId:$drill
    }
  ' >/dev/null || fail "restored database ownership tags are not exact" 3
  controls=$(aws s3api get-public-access-block --region "$region" --bucket "$bucket" --output json)
  printf '%s' "$controls" | jq -e '.PublicAccessBlockConfiguration |
    .BlockPublicAcls and .IgnorePublicAcls and .BlockPublicPolicy and .RestrictPublicBuckets' >/dev/null || \
    fail "restore bucket public-access block is incomplete" 3
  [ "$(aws s3api get-bucket-versioning --region "$region" --bucket "$bucket" --query Status --output text)" = Enabled ] || \
    fail "restore bucket versioning is not enabled" 3
  [ "$(aws s3api get-bucket-location --region "$region" --bucket "$bucket" --query LocationConstraint --output text)" = "$region" ] || \
    fail "restore bucket is not in the exact region" 3
  [ "$(aws s3api get-bucket-ownership-controls --region "$region" --bucket "$bucket" \
      --query 'OwnershipControls.Rules[0].ObjectOwnership' --output text)" = BucketOwnerEnforced ] || \
    fail "restore bucket does not enforce bucket-owner ownership" 3
  encryption=$(aws s3api get-bucket-encryption --region "$region" --bucket "$bucket" --output json)
  printf '%s' "$encryption" | jq -e --arg key "$data_kms_key_arn" '
    .ServerSideEncryptionConfiguration.Rules == [{
      ApplyServerSideEncryptionByDefault:{SSEAlgorithm:"aws:kms",KMSMasterKeyID:$key},
      BucketKeyEnabled:true
    }]
  ' >/dev/null || fail "restore bucket encryption controls are not exact" 3
  live_policy=$(aws s3api get-bucket-policy --region "$region" --bucket "$bucket" --query Policy --output text)
  printf '%s' "$live_policy" | jq -e --arg bucket "$bucket" --arg key "$data_kms_key_arn" '
    .Version == "2012-10-17" and
    (.Statement | sort_by(.Sid)) == ([
      {Sid:"DenyInsecureTransport",Effect:"Deny",Principal:"*",Action:"s3:*",
       Resource:["arn:aws:s3:::"+$bucket,"arn:aws:s3:::"+$bucket+"/*"],
       Condition:{Bool:{"aws:SecureTransport":"false"}}},
      {Sid:"DenyWrongRestoreObjectEncryption",Effect:"Deny",Principal:"*",Action:"s3:PutObject",
       Resource:"arn:aws:s3:::"+$bucket+"/*",
       Condition:{StringNotEquals:{"s3:x-amz-server-side-encryption":"aws:kms"}}},
      {Sid:"DenyWrongRestoreKmsKey",Effect:"Deny",Principal:"*",Action:"s3:PutObject",
       Resource:"arn:aws:s3:::"+$bucket+"/*",
       Condition:{StringNotEquals:{"s3:x-amz-server-side-encryption-aws-kms-key-id":$key}}}
    ] | sort_by(.Sid))
  ' >/dev/null || fail "restore bucket policy is not exact" 3
  [ "$(aws s3api get-bucket-policy-status --region "$region" --bucket "$bucket" \
      --query PolicyStatus.IsPublic --output text)" = False ] || \
    fail "restore bucket policy is public" 3
  bucket_tags=$(aws s3api get-bucket-tagging --region "$region" --bucket "$bucket" --output json)
  printf '%s' "$bucket_tags" | jq -e --arg drill "$drill_id" '
    (.TagSet | from_entries) == {Application:"Job Seeker Copilot",CostCentre:"public-beta",
      Environment:"public-beta",ManagedBy:"RestoreDrill",RestoreDrillId:$drill}
  ' >/dev/null || fail "restored bucket ownership tags are not exact" 3
}

assert_static_network() {
  groups=$(aws ec2 describe-security-groups --region "$region" --group-ids \
    "$database_security_group" "$semantic_security_group" "$broker_security_group" --output json)
  printf '%s' "$groups" | jq -e --arg vpc "$vpc_id" --arg db "$database_security_group" \
    --arg semantic "$semantic_security_group" --arg broker "$broker_security_group" '
    def exact_tags($name;$purpose):
      (.Tags | from_entries) == {Application:"Job Seeker Copilot",Environment:"public-beta",ManagedBy:"Terraform",
        Repository:"jobseekercopilot/infrastructure",CostCentre:"public-beta",Name:$name,Purpose:$purpose};
    (.SecurityGroups | length) == 3 and all(.[]; .VpcId == $vpc) and
    any(.SecurityGroups[]; .GroupId == $db and exact_tags("jsc-public-beta-restore-database";"RestoreDatabase")) and
    any(.SecurityGroups[]; .GroupId == $semantic and exact_tags("jsc-public-beta-restore-semantic-verifier";"RestoreSemanticVerifier")) and
    any(.SecurityGroups[]; .GroupId == $broker and exact_tags("jsc-public-beta-restore-semantic-broker";"RestoreSemanticBroker"))
  ' >/dev/null || fail "restore semantic groups are not exact Terraform resources" 3
  prefix_lists=$(aws ec2 describe-prefix-lists --region "$region" --filters \
    Name=prefix-list-name,Values="com.amazonaws.${region}.s3" --output json)
  s3_prefix=$(printf '%s' "$prefix_lists" | jq -er '.PrefixLists | if length == 1 then .[0].PrefixListId else error("S3 prefix mismatch") end')
  rules=$(aws ec2 describe-security-group-rules --region "$region" --filters \
    Name=group-id,Values="$database_security_group,$semantic_security_group,$broker_security_group" --output json)
  printf '%s' "$rules" | jq -e --arg db "$database_security_group" --arg semantic "$semantic_security_group" \
    --arg broker "$broker_security_group" --arg s3 "$s3_prefix" '
    [.SecurityGroupRules[] | {group:.GroupId,egress:.IsEgress,protocol:.IpProtocol,
      from:(.FromPort//null),to:(.ToPort//null),referenced:(.ReferencedGroupInfo.GroupId//null),
      cidr:(.CidrIpv4//null),prefix:(.PrefixListId//null)}] |
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
      {group:$broker,egress:true,protocol:"udp",from:53,to:53,referenced:null,cidr:"10.42.0.2/32",prefix:null}
    ] | sort_by(.group,.egress,.protocol,.from,.to,.referenced,.cidr,.prefix))
  ' >/dev/null || fail "restore SG allowlist is not the exact seven-child plus three-broker rule contract" 3
  semantic_eni_count_before_start=$(aws ec2 describe-network-interfaces --region "$region" \
    --filters Name=group-id,Values="$semantic_security_group" --output json | jq -er '.NetworkInterfaces|length')
  [ "$semantic_eni_count_before_start" -eq 0 ] || fail "semantic child SG has a pre-existing ENI" 3
}

assert_child_task_definition() {
  definition=$1
  kind=$2
  described=$(aws ecs describe-task-definition --region "$region" --task-definition "$definition" --include TAGS --output json)
  case "$kind" in
    clone)
      expected_image=$release_operator_image_digest; expected_commit=$release_operator_source_commit
      expected_exec=$clone_execution_role; expected_task=null
      expected_name=restore-semantic-clone; expected_purpose=restore-semantic-clone
      expected_command=/opt/jsc/clone-restored-document-store.sh ;;
    app)
      expected_image=$document_store_image_digest; expected_commit=$document_store_source_commit
      expected_exec=$app_execution_role; expected_task=$app_task_role
      expected_name=restore-semantic-document-store; expected_purpose=restore-semantic-document-store
      expected_command= ;;
    verifier)
      expected_image=$release_operator_image_digest; expected_commit=$release_operator_source_commit
      expected_exec=$verifier_execution_role; expected_task=$verifier_task_role
      expected_name=restore-semantic-verifier; expected_purpose=restore-semantic-verifier
      expected_command=/opt/jsc/verify-restored-semantics.sh ;;
  esac
  printf '%s' "$described" | jq -e --arg arn "$definition" --arg image "$expected_image" \
    --arg exec "$expected_exec" --arg task "$expected_task" --arg name "$expected_name" \
    --arg command "$expected_command" --arg kind "$kind" --arg commit "$expected_commit" \
    --arg purpose "$expected_purpose" '
    .taskDefinition.taskDefinitionArn == $arn and .taskDefinition.networkMode == "awsvpc" and
    .taskDefinition.requiresCompatibilities == ["EC2"] and
    .taskDefinition.executionRoleArn == $exec and
    (($task == "null" and (.taskDefinition.taskRoleArn // null) == null) or .taskDefinition.taskRoleArn == $task) and
    (.taskDefinition.containerDefinitions | length) == 1 and
    .taskDefinition.containerDefinitions[0].name == $name and
    (.taskDefinition.containerDefinitions[0].image | endswith("@"+$image)) and
    ((.taskDefinition.containerDefinitions[0].environment // []) as $environment |
      ([$environment[].name] | unique | length) == ($environment | length)) and
    ((.taskDefinition.containerDefinitions[0].secrets // []) as $secrets |
      ([$secrets[].name] | unique | length) == ($secrets | length)) and
    (($command == "" and (.taskDefinition.containerDefinitions[0].command // null) == null) or
      ($command != "" and .taskDefinition.containerDefinitions[0].command == [$command])) and
    (.taskDefinition.containerDefinitions[0].readonlyRootFilesystem == true) and
    (if $kind == "clone" then
      ([.taskDefinition.containerDefinitions[0].secrets[].name] | sort) ==
        ["DOCUMENT_STORE_PASSWORD","MASTER_PASSWORD","MASTER_USERNAME"]
     elif $kind == "app" then
      [.taskDefinition.containerDefinitions[0].secrets[].name] == ["DOCUMENT_STORE_DATABASE_PASSWORD"] and
      (.taskDefinition.containerDefinitions[0].environment | from_entries) as $env and
      $env.DOCUMENT_STORE_OBJECT_BUCKET == "jsc-public-beta-invalid-restore" and
      $env.DOCUMENT_STORE_RECONCILIATION_ENABLED == "true" and
      $env.DOCUMENT_STORE_RECONCILIATION_RUN_ON_STARTUP == "false" and
      $env.DOCUMENT_STORE_RECONCILIATION_INITIAL_DELAY_MS == "28800000" and
      $env.DOCUMENT_STORE_RECONCILIATION_FIXED_DELAY_MS == "28800000" and
      $env.DOCUMENT_STORE_PURGE_ENABLED == "true" and
      $env.DOCUMENT_STORE_PERMANENT_ERASURE_ENABLED == "true" and
      $env.DOCUMENT_STORE_PERMANENT_ERASURE_WRITE_FENCE_ENABLED == "true" and
      $env.DOCUMENT_STORE_VERSIONED_OBJECT_ERASURE_ENABLED == "true" and
      $env.DOCUMENT_STORE_PERMANENT_ERASURE_FIXED_DELAY_MS == "28800000" and
      $env.DOCUMENT_STORE_RETENTION_FIXED_DELAY_MS == "28800000" and
      $env.DOCUMENT_STORE_RETENTION_MAINTENANCE_ENABLED == "false" and
      $env.DOCUMENT_STORE_UPLOAD_CLEANUP_ENABLED == "false" and
      $env.DOCUMENT_STORE_RETENTION_ADMIN_TOKEN == "invalid-restore-semantic-admin-token-0000" and
      $env.DOCUMENT_STORE_ERASURE_FINGERPRINT_KEY == "invalid-restore-semantic-fingerprint" and
      .taskDefinition.containerDefinitions[0].healthCheck.command ==
        ["CMD-SHELL","wget -q --spider http://127.0.0.1:8089/actuator/health/liveness || exit 1"]
     else
      ([.taskDefinition.containerDefinitions[0].secrets[].name] | sort) ==
        ["APPLICATION_TRACKER_PASSWORD","AUTHENTICATION_PASSWORD","DOCUMENT_GENERATION_PASSWORD","DOCUMENT_STORE_PASSWORD","JOB_SERVICE_PASSWORD","PAYMENT_PASSWORD","USER_PROFILE_PASSWORD"] and
      (.taskDefinition.containerDefinitions[0].environment | from_entries).DOCUMENT_STORE_RETENTION_ADMIN_TOKEN ==
        "invalid-restore-semantic-admin-token-0000"
     end) and
    (.tags | from_entries) == {Application:"Job Seeker Copilot",Environment:"public-beta",ManagedBy:"Terraform",
      Repository:"jobseekercopilot/infrastructure",CostCentre:"public-beta",Purpose:$purpose,
      ImageDigest:$image,SourceCommit:$commit}
  ' >/dev/null || fail "$kind child task definition escaped its exact image/role/command contract" 3
}

assert_public_dark
assert_broker_network
assert_restore_control_plane
assert_static_network
assert_child_task_definition "$clone_task_definition" clone
assert_child_task_definition "$app_task_definition" app
assert_child_task_definition "$verifier_task_definition" verifier

current_marker=$(printf '%s' "$current_marker" | jq -cS \
  --arg machine "$state_machine_arn" --arg brokerTask "$broker_task_arn" \
  --arg brokerDefinition "$broker_task_definition" --arg brokerImage "$release_operator_image_digest" \
  --arg brokerExec "$broker_execution_role" --arg brokerRole "$broker_task_role" \
  --arg brokerEni "$broker_eni" --arg brokerIp "$broker_private_ip" --arg brokerSubnet "$broker_subnet_id" \
  --arg brokerSg "$broker_security_group" --argjson subnets "$private_subnets_json" '
    .runtimeBinding={stateMachineArn:$machine,executionArn:.executionArn,
      broker:{taskArn:$brokerTask,taskDefinitionArn:$brokerDefinition,imageDigest:$brokerImage,
        executionRoleArn:$brokerExec,taskRoleArn:$brokerRole,eniId:$brokerEni,privateIp:$brokerIp,
        subnetId:$brokerSubnet,securityGroupId:$brokerSg,injectedSecretCount:0},
      privateSubnetIds:$subnets}' )
aws ssm put-parameter --region "$region" --name "$marker_name" --type String --overwrite \
  --value "$current_marker" >/dev/null

source_marker=$(aws ssm get-parameter --region "$region" --name "$source_marker_name" --query Parameter.Value --output text)
[ "$(printf '%s' "$source_marker" | sha256sum | cut -d' ' -f1)" = "$source_marker_sha" ] || \
  fail "source marker bytes do not match the restore-start binding" 3
  printf '%s' "$source_marker" | jq -e --arg release "$release_id" --arg attestation "$release_attestation_id" \
  --arg canary "$source_canary_id" --arg account "$account_id" '
    keys == ["canaryId","databaseBootstrapMarkerVerified","document","flywayHistoriesVerified","logicalDatabases","preparedAt","releaseAttestationId","releaseId","schemaVersion"] and
    .schemaVersion == "jsc-public-beta-restore-source-canary.v1" and .releaseId == $release and
    .releaseAttestationId == $attestation and .canaryId == $canary and
    .databaseBootstrapMarkerVerified == true and .flywayHistoriesVerified == true and
    (.preparedAt | test("^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
    .logicalDatabases == ["authentication","user_profile","job_service","document_generation","document_store","application_tracker","payment"] and
    (.document | keys == ["bucket","key","versions"]) and
    .document.bucket == ("jsc-public-beta-documents-"+$account) and
    .document.key == ("restore-canary/v1/"+$canary+"/document.json") and
    (.document.versions | length) == 2 and [.document.versions[].generation] == [1,2] and
    (.document.versions[0].versionId != .document.versions[1].versionId) and
    all(.document.versions[]; keys == ["generation","sha256","sizeBytes","versionId"] and
      (.versionId | type == "string" and length > 0 and length <= 1024) and
      (.sha256 | test("^[0-9a-f]{64}$")) and (.sizeBytes | type == "number" and . > 0 and . <= 4096))
  ' >/dev/null || fail "source marker semantic binding is incomplete" 3
source_marker_b64=$(printf '%s' "$source_marker" | base64 | tr -d '\n')

derive_synthetic_value() {
  label=$1
  printf 'jsc-restore-semantic-v1:%s:%s' "$label" "$input_binding" | sha256sum | cut -d' ' -f1
}
synthetic_admin_token=$(derive_synthetic_value retention-admin)
synthetic_fingerprint_key=$(derive_synthetic_value erasure-fingerprint)
synthetic_producer_token=$(derive_synthetic_value document-producer)
synthetic_reader_token=$(derive_synthetic_value document-reader)
synthetic_tracker_producer_token=$(derive_synthetic_value tracker-producer)
synthetic_tracker_reader_token=$(derive_synthetic_value tracker-reader)
synthetic_environment_token=$(derive_synthetic_value environment-data)
printf '%s\n' "$synthetic_admin_token" "$synthetic_fingerprint_key" "$synthetic_producer_token" \
  "$synthetic_reader_token" "$synthetic_tracker_producer_token" "$synthetic_tracker_reader_token" \
  "$synthetic_environment_token" | jq -eRs '
    split("\n")[:-1] | length == 7 and (unique | length) == 7 and
    all(.[]; test("^[A-Za-z0-9_-]{64}$"))
  ' >/dev/null || fail "synthetic drill credential derivation failed" 3

network_configuration=$(jq -cnS --argjson subnets "$private_subnets_json" --arg sg "$semantic_security_group" '{
  awsvpcConfiguration:{subnets:$subnets,securityGroups:[$sg],assignPublicIp:"DISABLED"}
}')
started_by="jsc-rs-$(printf '%s' "$drill_id" | sha256sum | cut -c1-20)"

run_child() {
  definition=$1
  token=$2
  overrides_file=$3
  response=$(aws ecs run-task --region "$region" --cluster "$cluster_arn" \
    --task-definition "$definition" --launch-type EC2 --count 1 --client-token "$token" --started-by "$started_by" \
    --network-configuration "$network_configuration" --overrides "file://${overrides_file}" \
    --tags "$task_tags" --output json)
  printf '%s' "$response" | jq -e '(.failures | length) == 0 and (.tasks | length) == 1' >/dev/null || \
    fail "child RunTask returned a placement failure" 3
  printf '%s' "$response" | jq -er '.tasks[0].taskArn'
}

assert_override_size() {
  label=$1
  file=$2
  bytes=$(wc -c < "$file" | tr -d ' ')
  [ "$bytes" -le 8192 ] || fail "$label ECS overrides exceed the 8192-byte RunTask limit ($bytes)" 3
}

assert_task_tags() {
  task=$1
  task_matches_drill "$task" || fail "child task tags are not exact" 3
}

task_eni_and_ip() {
  task=$1
  attempts=0
  while [ "$attempts" -lt 120 ]; do
    described=$(aws ecs describe-tasks --region "$region" --cluster "$cluster_arn" --tasks "$task" --output json)
    eni_id=$(printf '%s' "$described" | jq -r '
      [.tasks[0].attachments[]?.details[]? | select(.name == "networkInterfaceId") | .value] |
      if length == 1 then .[0] else "" end')
    if [ -n "$eni_id" ]; then
      if eni=$(aws ec2 describe-network-interfaces --region "$region" --network-interface-ids "$eni_id" --output json 2>/dev/null); then
        printf '%s' "$eni" | jq -e --arg sg "$semantic_security_group" --argjson subnets "$private_subnets_json" '
          .NetworkInterfaces[0] as $eni |
          (.NetworkInterfaces | length) == 1 and [$eni.Groups[].GroupId] == [$sg] and
          ($subnets | index($eni.SubnetId)) != null and ($eni.Association.PublicIp // null) == null
        ' >/dev/null || fail "child ENI escaped the fixed semantic SG/private subnets" 3
        printf '%s' "$eni" | jq -ec '
          .NetworkInterfaces[0] | {eniId:.NetworkInterfaceId,privateIp:.PrivateIpAddress,
            subnetId:.SubnetId,securityGroupId:.Groups[0].GroupId}'
        return 0
      fi
    fi
    last_status=$(printf '%s' "$described" | jq -r '.tasks[0].lastStatus // ""')
    [ "$last_status" != STOPPED ] || fail "child stopped before its fixed ENI could be evidenced" 3
    attempts=$((attempts + 1))
    sleep 1
  done
  fail "timed out binding child ENI to the semantic SG" 3
}

wait_stopped_success() {
  task=$1
  deadline=$(( $(date +%s) + 2100 ))
  while :; do
    described=$(aws ecs describe-tasks --region "$region" --cluster "$cluster_arn" --tasks "$task" --output json)
    printf '%s' "$described" | jq -e '(.failures | length) == 0 and (.tasks | length) == 1' >/dev/null || \
      fail "child task disappeared while awaiting completion" 3
    if [ "$(printf '%s' "$described" | jq -r '.tasks[0].lastStatus')" = STOPPED ]; then
      printf '%s' "$described" | jq -e '
        .tasks[0].stopCode == "EssentialContainerExited" and
        (.tasks[0].containers | length) == 1 and .tasks[0].containers[0].exitCode == 0
      ' >/dev/null || fail "child task did not stop successfully" 3
      return 0
    fi
    [ "$(date +%s)" -lt "$deadline" ] || fail "child task exceeded its 35-minute bounded completion window" 3
    sleep 10
  done
}

wait_application_healthy() {
  task=$1
  attempts=0
  while [ "$attempts" -lt 120 ]; do
    described=$(aws ecs describe-tasks --region "$region" --cluster "$cluster_arn" --tasks "$task" --output json)
    if printf '%s' "$described" | jq -e '
      (.failures | length) == 0 and (.tasks | length) == 1 and
      .tasks[0].lastStatus == "RUNNING" and .tasks[0].healthStatus == "HEALTHY" and
      (.tasks[0].containers | length) == 1 and .tasks[0].containers[0].lastStatus == "RUNNING"
    ' >/dev/null; then return 0; fi
    printf '%s' "$described" | jq -e '.tasks[0].lastStatus != "STOPPED"' >/dev/null || \
      fail "candidate application stopped before liveness" 3
    attempts=$((attempts + 1))
    sleep 10
  done
  fail "candidate application did not reach liveness before the bounded timeout" 3
}

record_child() {
  child_name=$1
  child_arn=$2
  current_marker=$(printf '%s' "$current_marker" | jq -cS --arg name "$child_name" --arg task "$child_arn" '
    .phase="CHILDREN_RUNNING" | .childTasks=((.childTasks // {}) + {($name):$task})')
  aws ssm put-parameter --region "$region" --name "$marker_name" --type String --overwrite \
    --value "$current_marker" >/dev/null
}

clone_overrides=$(mktemp /tmp/jsc-restore-clone-overrides.XXXXXX.json)
source_overrides=$(mktemp /tmp/jsc-restore-source-overrides.XXXXXX.json)
replay_overrides=$(mktemp /tmp/jsc-restore-replay-overrides.XXXXXX.json)
verifier_overrides=$(mktemp /tmp/jsc-restore-verifier-overrides.XXXXXX.json)
jq -cnS --arg host "$restored_endpoint" --arg replayDb "$replay_database" --arg drill "$drill_id" \
  --arg canary "$source_canary_id" --arg marker "$source_marker_sha" --arg release "$release_id" \
  --arg attempt "$attempt" --arg operation "$operation_id" --arg replay "$restore_replay_id" '{
    containerOverrides:[{name:"restore-semantic-clone",environment:[
      {name:"PGHOST",value:$host},{name:"RESTORE_REPLAY_DATABASE",value:$replayDb},
      {name:"RESTORE_DRILL_ID",value:$drill},{name:"RESTORE_SOURCE_CANARY_ID",value:$canary},
      {name:"RESTORE_SOURCE_MARKER_SHA256",value:$marker},{name:"RELEASE_ID",value:$release},
      {name:"RESTORE_ATTEMPT",value:$attempt},{name:"RESTORE_ERASURE_OPERATION_ID",value:$operation},
      {name:"RESTORE_ERASURE_REPLAY_ID",value:$replay}
    ]}]
  }' > "$clone_overrides"
assert_override_size clone "$clone_overrides"

clone_token=$(printf '%s:attempt-%s:clone:%s' "$input_binding" "$attempt" "$clone_task_definition" | sha256sum | cut -d' ' -f1)
children_started=true
clone_task_arn=$(run_child "$clone_task_definition" "$clone_token" "$clone_overrides")
record_child clone "$clone_task_arn"
assert_task_tags "$clone_task_arn"
clone_network=$(task_eni_and_ip "$clone_task_arn")
clone_ip=$(printf '%s' "$clone_network" | jq -er .privateIp)
wait_stopped_success "$clone_task_arn"

render_app_overrides() {
  target_database=$1
  output=$2
  jq -cnS --arg url "jdbc:postgresql://${restored_endpoint}:5432/${target_database}?sslmode=verify-full&sslrootcert=/etc/jsc/rds/global-bundle.pem" \
    --arg bucket "$bucket" --arg admin "$synthetic_admin_token" --arg fingerprint "$synthetic_fingerprint_key" \
    --arg producer "$synthetic_producer_token" --arg reader "$synthetic_reader_token" \
    --arg trackerProducer "$synthetic_tracker_producer_token" --arg trackerReader "$synthetic_tracker_reader_token" \
    --arg environmentToken "$synthetic_environment_token" '{containerOverrides:[{name:"restore-semantic-document-store",environment:[
      {name:"DOCUMENT_STORE_DATABASE_URL",value:$url},
      {name:"DOCUMENT_STORE_OBJECT_BUCKET",value:$bucket},
      {name:"DOCUMENT_STORE_RETENTION_ADMIN_TOKEN",value:$admin},
      {name:"DOCUMENT_STORE_ERASURE_FINGERPRINT_KEY",value:$fingerprint},
      {name:"DOCUMENT_STORE_PRODUCER_TOKEN",value:$producer},
      {name:"DOCUMENT_STORE_READER_TOKEN",value:$reader},
      {name:"APPLICATION_TRACKER_PRODUCER_TOKEN",value:$trackerProducer},
      {name:"APPLICATION_TRACKER_READER_TOKEN",value:$trackerReader},
      {name:"ENVIRONMENT_DATA_TOKEN",value:$environmentToken}
    ]}]}' > "$output"
  assert_override_size "document-store-${target_database}" "$output"
}
render_app_overrides document_store "$source_overrides"
render_app_overrides "$replay_database" "$replay_overrides"
source_token=$(printf '%s:attempt-%s:source:%s' "$input_binding" "$attempt" "$app_task_definition" | sha256sum | cut -d' ' -f1)
replay_token=$(printf '%s:attempt-%s:replay:%s' "$input_binding" "$attempt" "$app_task_definition" | sha256sum | cut -d' ' -f1)
source_task_arn=$(run_child "$app_task_definition" "$source_token" "$source_overrides")
record_child sourceApplication "$source_task_arn"
replay_task_arn=$(run_child "$app_task_definition" "$replay_token" "$replay_overrides")
record_child replayApplication "$replay_task_arn"
assert_task_tags "$source_task_arn"
assert_task_tags "$replay_task_arn"
source_network=$(task_eni_and_ip "$source_task_arn")
replay_network=$(task_eni_and_ip "$replay_task_arn")
source_ip=$(printf '%s' "$source_network" | jq -er .privateIp)
replay_ip=$(printf '%s' "$replay_network" | jq -er .privateIp)
[ "$source_ip" != "$replay_ip" ] || fail "source and replay applications share an address" 3
wait_application_healthy "$source_task_arn"
wait_application_healthy "$replay_task_arn"

running_marker=$(printf '%s' "$current_marker" | jq -cS --arg clone "$clone_task_arn" --arg source "$source_task_arn" \
  --arg replay "$replay_task_arn" '.phase="CHILDREN_RUNNING" | .childTasks={clone:$clone,sourceApplication:$source,replayApplication:$replay}')
aws ssm put-parameter --region "$region" --name "$marker_name" --type String --overwrite --value "$running_marker" >/dev/null

jq -cnS --arg host "$restored_endpoint" --arg bucket "$bucket" --arg drill "$drill_id" \
  --arg canary "$source_canary_id" --arg sourceEvidence "$source_evidence_sha" --arg marker "$source_marker_sha" \
  --arg release "$release_id" --arg replayDb "$replay_database" --arg operation "$operation_id" \
  --arg replayId "$restore_replay_id" --arg sourceUrl "http://${source_ip}:8089" --arg replayUrl "http://${replay_ip}:8089" \
  --arg cloneTask "$clone_task_arn" --arg sourceTask "$source_task_arn" --arg replayTask "$replay_task_arn" \
  --arg cloneDefinition "$clone_task_definition" --arg appDefinition "$app_task_definition" \
  --arg verifierDefinition "$verifier_task_definition" --arg documentImage "$document_store_image_digest" \
  --arg operatorImage "$release_operator_image_digest" --arg vpc "$vpc_id" --arg databaseSg "$database_security_group" \
  --arg semanticSg "$semantic_security_group" --arg restoredArn "$restored_database_arn" \
  --arg markerB64 "$source_marker_b64" --arg admin "$synthetic_admin_token" --arg attempt "$attempt" '{
    containerOverrides:[{name:"restore-semantic-verifier",environment:[
      {name:"PGHOST",value:$host},{name:"RESTORE_DOCUMENT_BUCKET",value:$bucket},
      {name:"RESTORE_DRILL_ID",value:$drill},{name:"RESTORE_SOURCE_CANARY_ID",value:$canary},
      {name:"RESTORE_SOURCE_EVIDENCE_SHA256",value:$sourceEvidence},{name:"RESTORE_SOURCE_MARKER_SHA256",value:$marker},
      {name:"RESTORE_SOURCE_MARKER_B64",value:$markerB64},{name:"RELEASE_ID",value:$release},
      {name:"RESTORE_REPLAY_DATABASE",value:$replayDb},{name:"RESTORE_ERASURE_OPERATION_ID",value:$operation},
      {name:"RESTORE_ERASURE_REPLAY_ID",value:$replayId},{name:"SOURCE_DOCUMENT_STORE_URL",value:$sourceUrl},
      {name:"REPLAY_DOCUMENT_STORE_URL",value:$replayUrl},{name:"RESTORE_CLONE_TASK_ARN",value:$cloneTask},
      {name:"RESTORE_SOURCE_APP_TASK_ARN",value:$sourceTask},{name:"RESTORE_REPLAY_APP_TASK_ARN",value:$replayTask},
      {name:"RESTORE_CLONE_TASK_DEFINITION_ARN",value:$cloneDefinition},
      {name:"RESTORE_APP_TASK_DEFINITION_ARN",value:$appDefinition},
      {name:"RESTORE_VERIFIER_TASK_DEFINITION_ARN",value:$verifierDefinition},
      {name:"DOCUMENT_STORE_IMAGE_DIGEST",value:$documentImage},{name:"RELEASE_OPERATOR_IMAGE_DIGEST",value:$operatorImage},
      {name:"RESTORE_VPC_ID",value:$vpc},{name:"RESTORE_DATABASE_SECURITY_GROUP_ID",value:$databaseSg},
      {name:"RESTORE_SEMANTIC_SECURITY_GROUP_ID",value:$semanticSg},{name:"RESTORED_DATABASE_ARN",value:$restoredArn}
      ,{name:"DOCUMENT_STORE_RETENTION_ADMIN_TOKEN",value:$admin},{name:"RESTORE_ATTEMPT",value:$attempt}
    ]}]
  }' > "$verifier_overrides"
assert_override_size verifier "$verifier_overrides"
verifier_token=$(printf '%s:attempt-%s:verifier:%s' "$input_binding" "$attempt" "$verifier_task_definition" | sha256sum | cut -d' ' -f1)
verifier_task_arn=$(run_child "$verifier_task_definition" "$verifier_token" "$verifier_overrides")
record_child verifier "$verifier_task_arn"
assert_task_tags "$verifier_task_arn"
verifier_network=$(task_eni_and_ip "$verifier_task_arn")
verifier_ip=$(printf '%s' "$verifier_network" | jq -er .privateIp)
wait_stopped_success "$verifier_task_arn"

contain_children
children_started=false
assert_public_dark
remaining=$(aws ecs list-tasks --region "$region" --cluster "$cluster_arn" --desired-status RUNNING --output json)
printf '%s' "$remaining" | jq -e --arg broker "$broker_task_arn" '.taskArns == [$broker]' >/dev/null || \
  fail "an unmanaged or semantic ECS task remains after broker containment" 3
pending=$(aws ecs list-tasks --region "$region" --cluster "$cluster_arn" --desired-status PENDING --output json)
printf '%s' "$pending" | jq -e '.taskArns == []' >/dev/null || \
  fail "a pending ECS task remains after serialized broker containment" 3
semantic_eni_count_after_containment=$(aws ec2 describe-network-interfaces --region "$region" \
  --filters Name=group-id,Values="$semantic_security_group" --output json | jq -er '.NetworkInterfaces|length')
[ "$semantic_eni_count_after_containment" -eq 0 ] || fail "semantic ENIs remain after containment" 3

verifier_task_id=${verifier_task_arn##*/}
completed_marker=$(printf '%s' "$current_marker" | jq -cS \
  --arg verifier "$verifier_task_arn" --arg completed "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg logStream "restore-semantic-verifier/restore-semantic-verifier/${verifier_task_id}" \
  --arg vpc "$vpc_id" \
  --arg databaseSg "$database_security_group" --arg semanticSg "$semantic_security_group" \
  --arg brokerSg "$broker_security_group" --arg restoredArn "$restored_database_arn" \
  --arg endpoint "$restored_endpoint" --argjson cloneNetwork "$clone_network" \
  --argjson sourceNetwork "$source_network" --argjson replayNetwork "$replay_network" \
  --argjson verifierNetwork "$verifier_network" '
    .phase="COMPLETED" | .completedAt=$completed |
    .childTasks.verifier=$verifier | .verifierLogStream=$logStream |
    .runtimeBinding.childNetwork={clone:$cloneNetwork,sourceApplication:$sourceNetwork,
      replayApplication:$replayNetwork,verifier:$verifierNetwork} |
    .network={vpcId:$vpc,restoreDatabaseSecurityGroupId:$databaseSg,semanticSecurityGroupId:$semanticSg,
      brokerSecurityGroupId:$brokerSg,childStaticRuleCount:7,brokerStaticRuleCount:3,
      semanticEniCountBeforeStart:0,semanticEniCountAfterContainment:0,
      restoredDatabaseArn:$restoredArn,restoredDatabaseEndpoint:$endpoint} |
    .publicSafety={publicEntrypointFixed503:true,applicationDesiredCount:0,runningPublicApplicationTaskCount:0,
      pendingClusterTaskCountAfterContainment:0,semanticTasksNotAttachedToPublicFleet:true}
  ')
[ "$(printf '%s' "$completed_marker" | wc -c | tr -d ' ')" -le 4096 ] || \
  fail "completed durable marker exceeds the SSM Standard 4096-byte limit" 3
aws ssm put-parameter --region "$region" --name "$marker_name" --type String --overwrite --value "$completed_marker" >/dev/null
rm -f -- "$clone_overrides" "$source_overrides" "$replay_overrides" "$verifier_overrides"
trap - EXIT HUP INT TERM
echo "restore semantic broker completed exact isolated application-path verification and contained all child tasks"
