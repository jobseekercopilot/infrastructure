#!/usr/bin/env bash
set -euo pipefail
umask 077

action=${1:-}
region=${AWS_REGION:-eu-west-2}
confirmation=${RELEASE_CONFIRMATION:-}
tfvars_file=${TF_VARS_FILE:-}
image_manifest=${IMAGE_MANIFEST:-}
approval_manifest=${APPROVAL_MANIFEST:-}
landing_archive=${LANDING_ARCHIVE:-}
restore_drill_evidence=${RESTORE_DRILL_EVIDENCE:-}
release_provenance=${RELEASE_PROVENANCE:-}
restore_source_canary_id=${RESTORE_SOURCE_CANARY_ID:-}
restore_source_output_directory=${RESTORE_SOURCE_OUTPUT_DIRECTORY:-}
candidate_build_run_id=${CANDIDATE_BUILD_RUN_ID:-}

case "$action" in foundation|plan|prepare|prepare-restore-source|activate|rollback) ;;
  *) echo "Usage: $0 {foundation|plan|prepare|prepare-restore-source|activate|rollback}" >&2; exit 2 ;;
esac
if [[ "$region" != "eu-west-2" || -z "$tfvars_file" || -z "$approval_manifest" ]]; then
  echo "Refusing: eu-west-2, TF_VARS_FILE and APPROVAL_MANIFEST are required." >&2
  exit 2
fi

for command_name in aws base64 jq mktemp terraform; do
  command -v "$command_name" >/dev/null || { echo "Missing required command: $command_name" >&2; exit 2; }
done

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
module="$repository_root/aws/public-beta"
template_manifest="$module/config/image-manifest.json"
backup_policy_contract="$module/config/aws-backup-managed-policy-contract.json"
manifest=${image_manifest:-$template_manifest}

for path in "$tfvars_file" "$approval_manifest" "$manifest"; do
  [[ -f "$path" ]] || { echo "Missing release input: $path" >&2; exit 2; }
done
[[ -f "$backup_policy_contract" ]] || {
  echo "Missing reviewed AWS Backup managed-policy contract." >&2
  exit 2
}

if [[ "${GITHUB_REF:-}" != "refs/heads/main" ]]; then
  echo "Refusing AWS release work outside main." >&2
  exit 2
fi

release_id=$(jq -er '.releaseId' "$manifest")
restore_source_mode=false
if [[ "$action" == "prepare-restore-source" ]]; then
  restore_source_mode=true
  [[ "$candidate_build_run_id" =~ ^[0-9]+$ ]] || {
    echo "Restore-source preparation requires the numeric immutable candidate build run ID." >&2
    exit 2
  }
  [[ "$restore_source_canary_id" =~ ^[a-z0-9][a-z0-9-]{6,30}[a-z0-9]$ ]] || {
    echo "Restore-source preparation requires an 8-32 character lowercase canary ID." >&2
    exit 2
  }
  [[ -n "$restore_source_output_directory" && ! -L "$restore_source_output_directory" ]] || {
    echo "Restore-source preparation requires a safe output directory." >&2
    exit 2
  }
fi
if [[ "$action" != "foundation" ]]; then
  [[ -f "$landing_archive" ]] || { echo "Missing checksum-bound Landing release artifact." >&2; exit 2; }
  [[ -f "$release_provenance" && ! -L "$release_provenance" ]] || {
    echo "Missing checksum-bound release provenance." >&2
    exit 2
  }
  infrastructure_revision=$(jq -er '.infrastructureRevision | select(test("^[0-9a-f]{40}$"))' "$release_provenance")
  [[ "$(jq -er .releaseId "$release_provenance")" == "$release_id" ]] || {
    echo "Release provenance does not match the image manifest." >&2
    exit 2
  }
  [[ "$(jq -er .imageManifestSha256 "$release_provenance")" == "$(sha256sum "$manifest" | cut -d' ' -f1)" ]] || {
    echo "Release provenance does not bind the image manifest." >&2
    exit 2
  }
  if [[ "$restore_source_mode" == true ]]; then
    [[ "$(jq -er .buildPurpose "$release_provenance")" == restore-candidate ]] || {
      echo "Restore-source preparation accepts only restore-candidate provenance." >&2
      exit 2
    }
    python3 "$repository_root/scripts/aws/validate_public_beta.py" \
      --restore-candidate --image-manifest "$manifest" --approval-manifest "$approval_manifest" \
      --landing-archive "$landing_archive" \
      --infrastructure-revision "$infrastructure_revision"
  else
    [[ "$(jq -er .buildPurpose "$release_provenance")" == release ]] || {
      echo "Normal release actions accept only promoted release provenance." >&2
      exit 2
    }
    restore_evidence_arguments=()
    if [[ -n "$restore_drill_evidence" && -f "$restore_drill_evidence" && ! -L "$restore_drill_evidence" ]]; then
      restore_evidence_arguments=(--restore-drill-evidence "$restore_drill_evidence")
    elif [[ -n "$restore_drill_evidence" && ( -e "$restore_drill_evidence" || -L "$restore_drill_evidence" ) ]]; then
      echo "Unsafe restore-drill evidence input." >&2
      exit 2
    fi
    python3 "$repository_root/scripts/aws/validate_public_beta.py" \
      --release --image-manifest "$manifest" --approval-manifest "$approval_manifest" \
      --landing-archive "$landing_archive" \
      --infrastructure-revision "$infrastructure_revision" \
      "${restore_evidence_arguments[@]}"
  fi
fi

common_arguments=(
  -input=false
  -lock-timeout=10m
  -var-file="$tfvars_file"
  -var=offline_validation=false
  -var="restore_source_preparation=$restore_source_mode"
  -var="image_manifest_path=$manifest"
  -var="approval_manifest_path=$approval_manifest"
)

temporary_release_files=()
cleanup_release_files() {
  if (( ${#temporary_release_files[@]} > 0 )); then
    rm -f -- "${temporary_release_files[@]}"
  fi
}
trap cleanup_release_files EXIT

validate_state_machine_definitions_from_json() {
  local terraform_json=$1
  local source_label=$2
  local address machine_type encoded_definition definition_file validation_file definitions_file
  local state_machine_count
  local validated=0

  definitions_file=$(mktemp /tmp/jsc-state-machine-definitions.XXXXXX.tsv)
  temporary_release_files+=("$definitions_file")
  if ! state_machine_count=$(jq -er '
    def modules: ., (.child_modules[]? | modules);
    [(.planned_values.root_module // .values.root_module)
      | modules
      | .resources[]?
      | select(.mode == "managed" and .type == "aws_sfn_state_machine")]
    | length
  ' "$terraform_json"); then
    echo "Could not enumerate $source_label Terraform state-machine resources." >&2
    exit 3
  fi
  if ! jq -r '
    def modules: ., (.child_modules[]? | modules);
    (.planned_values.root_module // .values.root_module)
    | modules
    | .resources[]?
    | select(.mode == "managed" and .type == "aws_sfn_state_machine")
    | select(.values.definition | type == "string")
    | [.address, (.values.type // "STANDARD"), (.values.definition | @base64)]
    | @tsv
  ' "$terraform_json" >"$definitions_file"; then
    echo "Could not extract $source_label Terraform state-machine definitions." >&2
    exit 3
  fi

  while IFS=$'\t' read -r address machine_type encoded_definition; do
    [[ -n "$address" && -n "$machine_type" && -n "$encoded_definition" ]] || continue
    definition_file=$(mktemp /tmp/jsc-state-machine-definition.XXXXXX.json)
    validation_file=$(mktemp /tmp/jsc-state-machine-validation.XXXXXX.json)
    temporary_release_files+=("$definition_file" "$validation_file")
    printf '%s' "$encoded_definition" | base64 --decode >"$definition_file"
    if ! aws stepfunctions validate-state-machine-definition \
      --region "$region" \
      --definition "file://$definition_file" \
      --type "$machine_type" \
      --severity ERROR \
      --max-results 100 \
      --output json >"$validation_file"; then
      echo "AWS could not validate the $source_label state-machine definition for $address." >&2
      exit 3
    fi
    if ! jq -e '.result == "OK"' "$validation_file" >/dev/null; then
      echo "AWS rejected the $source_label state-machine definition for $address:" >&2
      jq -r '.diagnostics[]? | "\(.severity): \(.message)"' "$validation_file" >&2
      exit 3
    fi
    ((validated += 1))
    rm -f -- "$definition_file" "$validation_file"
  done <"$definitions_file"

  if (( validated != state_machine_count )); then
    echo "Refusing: $source_label has $state_machine_count state-machine resource(s), but only $validated fully rendered definition(s). Stage prerequisites and re-plan." >&2
    exit 3
  fi
  rm -f -- "$definitions_file"

  echo "AWS state-machine definition validation passed for $validated $source_label definition(s)."
}

validate_planned_state_machine_definitions() {
  local plan_json=$1
  validate_state_machine_definitions_from_json "$plan_json" planned
}

validate_deployed_state_machine_definitions() {
  local state_json
  state_json=$(mktemp /tmp/jsc-live-state.XXXXXX.json)
  temporary_release_files+=("$state_json")
  terraform -chdir="$module" show -json >"$state_json"
  validate_state_machine_definitions_from_json "$state_json" deployed
  rm -f -- "$state_json"
}

verify_live_release_iam() {
  local plan=$1
  local allow_rds_monitoring_migration=${2:-false}
  local complete_iam_plan=${3:-$plan}
  local plan_json complete_iam_plan_json
  local -a migration_arguments=()
  if [[ "$allow_rds_monitoring_migration" == true ]]; then
    migration_arguments+=(--allow-rds-monitoring-migration)
  fi
  plan_json=$(mktemp /tmp/jsc-live-iam-plan.XXXXXX.json)
  temporary_release_files+=("$plan_json")
  terraform -chdir="$module" show -json "$plan" >"$plan_json"
  validate_planned_state_machine_definitions "$plan_json"
  validate_deployed_state_machine_definitions
  python3 "$repository_root/scripts/aws/verify_saved_release_plan.py" \
    --plan-json "$plan_json"
  if [[ "$complete_iam_plan" == "$plan" ]]; then
    complete_iam_plan_json=$plan_json
  else
    complete_iam_plan_json=$(mktemp /tmp/jsc-live-complete-iam-plan.XXXXXX.json)
    temporary_release_files+=("$complete_iam_plan_json")
    terraform -chdir="$module" show -json "$complete_iam_plan" >"$complete_iam_plan_json"
    python3 "$repository_root/scripts/aws/verify_saved_release_plan.py" \
      --plan-json "$complete_iam_plan_json"
  fi
  python3 "$repository_root/scripts/aws/verify_live_release_iam.py" \
    --plan-json "$complete_iam_plan_json" \
    --backup-contract "$backup_policy_contract" \
    --region "$region" \
    "${migration_arguments[@]}"
  rm -f "$plan_json"
  if [[ "$complete_iam_plan_json" != "$plan_json" ]]; then
    rm -f "$complete_iam_plan_json"
  fi
}

verify_live_rds_monitoring() {
  local not_before=$1
  local contract database_identifier monitoring_role_arn
  contract=$(terraform -chdir="$module" output -json release_contract)
  database_identifier=$(jq -er '.database_identifier' <<<"$contract")
  monitoring_role_arn=$(jq -er '.rds_monitoring_role_arn' <<<"$contract")
  python3 "$repository_root/scripts/aws/verify_live_rds_monitoring.py" \
    --region "$region" \
    --db-instance-identifier "$database_identifier" \
    --monitoring-role-arn "$monitoring_role_arn" \
    --not-before "$not_before"
}

verify_current_iam_contract() {
  local desired=$1
  local public=$2
  local label=$3
  local plan
  plan=$(mktemp "/tmp/jsc-${label}.XXXXXX.tfplan")
  temporary_release_files+=("$plan")
  terraform -chdir="$module" plan "${common_arguments[@]}" \
    -var="application_desired_count=$desired" \
    -var="public_entrypoint_enabled=$public" \
    -out="$plan"
  verify_live_release_iam "$plan"
  rm -f "$plan"
}

verify_existing_launch_template_authorization() {
  local launch_template_id launch_template_version subnet_id dry_run_output
  local -a subnet_ids=()
  read -r launch_template_id launch_template_version < <(
    aws ec2 describe-launch-templates \
      --region "$region" \
      --filters \
        "Name=tag:Application,Values=Job Seeker Copilot" \
        "Name=tag:Environment,Values=public-beta" \
        "Name=tag:ManagedBy,Values=Terraform" \
      --query 'sort_by(LaunchTemplates,&CreateTime)[-1].[LaunchTemplateId,LatestVersionNumber]' \
      --output text
  )

  # A first-ever foundation has no template to preflight; Terraform creates it
  # in the same saved apply. Every retry/update must prove the exact EC2 dry-run
  # authorization that Auto Scaling performs before accepting the template.
  if [[ -z "${launch_template_id:-}" || "$launch_template_id" == "None" ]]; then
    echo "Launch-template IAM preflight deferred: no existing public-beta template."
    return
  fi

  mapfile -t subnet_ids < <(
    aws ec2 describe-subnets \
      --region "$region" \
      --filters \
        "Name=tag:Application,Values=Job Seeker Copilot" \
        "Name=tag:Environment,Values=public-beta" \
        "Name=tag:ManagedBy,Values=Terraform" \
        "Name=tag:Name,Values=jsc-public-beta-private-*" \
      --query 'sort_by(Subnets,&SubnetId)[].SubnetId' \
      --output json | jq -r '.[]'
  )
  (( ${#subnet_ids[@]} > 0 )) || {
    echo "Launch-template IAM preflight failed: no tagged public-beta private subnet." >&2
    exit 3
  }

  for subnet_id in "${subnet_ids[@]}"; do
    if dry_run_output=$(aws ec2 run-instances \
      --region "$region" \
      --launch-template "LaunchTemplateId=$launch_template_id,Version=$launch_template_version" \
      --subnet-id "$subnet_id" \
      --count 1 \
      --dry-run 2>&1); then
      echo "Launch-template IAM preflight failed: EC2 dry-run unexpectedly returned success." >&2
      exit 3
    fi
    if [[ "$dry_run_output" != *"DryRunOperation"* ]]; then
      echo "Launch-template IAM preflight failed for $launch_template_id version $launch_template_version in $subnet_id:" >&2
      echo "$dry_run_output" >&2
      exit 3
    fi
  done
  echo "Launch-template IAM preflight passed for $launch_template_id version $launch_template_version in every private subnet."
}

verify_account_email_ses() {
  local contract
  contract=$(terraform -chdir="$module" output -json account_email_delivery)
  python3 "$repository_root/scripts/aws/verify_account_email_ses.py" \
    --region "$region" \
    --account-id "$(jq -er '.aws_account_id' <<<"$contract")" \
    --identity-domain "$(jq -er '.identity_domain' <<<"$contract")" \
    --sender "$(jq -er '.sender' <<<"$contract")" \
    --configuration-set "$(jq -er '.configuration_set' <<<"$contract")" \
    --event-destination "$(jq -er '.event_destination' <<<"$contract")" \
    --topic-arn "$(jq -er '.operations_topic_arn' <<<"$contract")"
}

plan_and_apply() {
  local desired=$1
  local public=$2
  local label=$3
  local plan apply_started_at
  local allow_rds_monitoring_migration=false
  if [[ "$label" == foundation ]]; then
    allow_rds_monitoring_migration=true
  fi
  plan=$(mktemp "/tmp/jsc-${label}.XXXXXX.tfplan")
  temporary_release_files+=("$plan")
  terraform -chdir="$module" plan "${common_arguments[@]}" \
    -var="application_desired_count=$desired" \
    -var="public_entrypoint_enabled=$public" \
    -out="$plan"
  verify_live_release_iam "$plan" "$allow_rds_monitoring_migration"
  terraform -chdir="$module" show -no-color "$plan"
  apply_started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  terraform -chdir="$module" apply -input=false "$plan"
  # Recheck IAM without the one-way legacy-role exception, then observe a
  # stability window because RDS can asynchronously reject and revert an
  # apparently successful Enhanced Monitoring modification.
  verify_live_release_iam "$plan"
  verify_live_rds_monitoring "$apply_started_at"
  rm -f "$plan"
}

review_plan_only() {
  local desired=${APPLICATION_DESIRED_COUNT:-0}
  local public=${PUBLIC_ENTRYPOINT_ENABLED:-false}
  local plan
  plan=$(mktemp /tmp/jsc-review.XXXXXX.tfplan)
  temporary_release_files+=("$plan")
  terraform -chdir="$module" plan "${common_arguments[@]}" \
    -var="application_desired_count=$desired" \
    -var="public_entrypoint_enabled=$public" \
    -out="$plan"
  verify_live_release_iam "$plan"
  terraform -chdir="$module" show -no-color "$plan"
  rm -f "$plan"
}

targeted_plan_and_apply() {
  local target=$1
  local label=$2
  local desired=${3:-1}
  local plan complete_iam_plan
  plan=$(mktemp "/tmp/jsc-target-${label}.XXXXXX.tfplan")
  complete_iam_plan=$(mktemp "/tmp/jsc-target-${label}-complete-iam.XXXXXX.tfplan")
  temporary_release_files+=("$plan" "$complete_iam_plan")
  terraform -chdir="$module" plan "${common_arguments[@]}" \
    -parallelism=1 \
    -target="$target" \
    -var="application_desired_count=$desired" \
    -var=public_entrypoint_enabled=false \
    -out="$plan"
  # Terraform deliberately omits unrelated resources from planned_values for
  # a targeted plan. Build a separate, never-applied full dark plan so the
  # live IAM verifier can still compare every reserved PassRole name with the
  # complete reviewed role/boundary/trust model. The targeted plan remains the
  # only plan eligible for apply and retains its own state-machine and retained-
  # resource checks.
  terraform -chdir="$module" plan "${common_arguments[@]}" \
    -var="application_desired_count=$desired" \
    -var=public_entrypoint_enabled=false \
    -out="$complete_iam_plan"
  verify_live_release_iam "$plan" false "$complete_iam_plan"
  terraform -chdir="$module" show -no-color "$plan"
  terraform -chdir="$module" apply -input=false "$plan"
  validate_deployed_state_machine_definitions
  rm -f "$plan" "$complete_iam_plan"
}

stage_state_machine_prerequisites() {
  # A new release changes the broker task-definition ARN embedded in the
  # Step Functions definition. Register only that restore-specific task
  # definition first so the subsequent full dark plan is fully rendered and
  # can pass the fail-closed AWS schema check. No ECS service is targeted.
  targeted_plan_and_apply \
    aws_ecs_task_definition.restore_semantic_broker \
    restore-semantic-broker \
    0
}

write_marker() {
  local name=$1
  local release_attestation_id
  release_attestation_id=$(terraform -chdir="$module" output -json release_contract | jq -er '.release_attestation_id')
  aws ssm put-parameter \
    --region "$region" \
    --name "/jsc/public-beta/release/$name" \
    --description "Successful $name attestation for an exact immutable JSC release" \
    --type String \
    --value "$release_attestation_id" \
    --overwrite >/dev/null
  aws ssm add-tags-to-resource \
    --region "$region" \
    --resource-type Parameter \
    --resource-id "/jsc/public-beta/release/$name" \
    --tags Key=Application,Value="Job Seeker Copilot" Key=Environment,Value=public-beta Key=ReleaseId,Value="$release_id" >/dev/null
}

assert_marker() {
  local name=$1
  local expected actual
  expected=$(terraform -chdir="$module" output -json release_contract | jq -er '.release_attestation_id')
  actual=$(aws ssm get-parameter \
    --region "$region" \
    --name "/jsc/public-beta/release/$name" \
    --query 'Parameter.Value' \
    --output text)
  [[ "$actual" == "$expected" ]] || {
    echo "Release marker mismatch: $name was not completed for the exact prepared contract." >&2
    exit 3
  }
}

assert_current_release() {
  local current_release
  current_release=$(terraform -chdir="$module" output -json release_contract | jq -er '.release_id')
  [[ "$current_release" == "$release_id" ]] || {
    echo "Release action refused: $release_id is not the currently applied release." >&2
    exit 3
  }
}

assert_exact_prepared_release() {
  assert_current_release
  assert_marker database-bootstrap
  assert_marker preflight
}

assert_capacity_ready() {
  local capacity
  capacity=$(terraform -chdir="$module" output -json capacity_contract)
  local expected_nodes expected_instance_type task_slots awsvpc_task_limit required_cpu required_memory
  expected_nodes=$(jq -er '.node_count' <<<"$capacity")
  expected_instance_type=$(jq -er '.instance_type' <<<"$capacity")
  task_slots=$(jq -er '.task_slots' <<<"$capacity")
  awsvpc_task_limit=$(jq -er '.awsvpc_task_limit' <<<"$capacity")
  required_cpu=$(jq -er '.reserved_cpu_units' <<<"$capacity")
  required_memory=$(jq -er '.reserved_memory_mib' <<<"$capacity")

  local contract cluster
  contract=$(terraform -chdir="$module" output -json release_contract)
  cluster=$(jq -er '.cluster_arn' <<<"$contract")
  local instances
  instances=$(aws ecs list-container-instances --region "$region" --cluster "$cluster" --status ACTIVE --output json)
  [[ $(jq '.containerInstanceArns | length' <<<"$instances") -eq "$expected_nodes" ]] || {
    echo "Capacity preflight failed: expected exactly $expected_nodes ACTIVE ECS nodes." >&2; exit 3;
  }

  local instance_state remaining_cpu remaining_memory active_tasks remaining_awsvpc_tasks
  instance_state=$(aws ecs describe-container-instances \
    --region "$region" --cluster "$cluster" \
    --container-instances $(jq -r '.containerInstanceArns[]' <<<"$instances") \
    --output json)
  if ! jq -e --arg expected_instance_type "$expected_instance_type" '
    (.failures | length) == 0 and
    all(.containerInstances[];
      . as $instance |
      ($instance.attributes
        | map(select(.name == "ecs.awsvpc-trunk-id" and (.value | length) > 0))
        | map(.value) | unique) as $trunks |
      $instance.agentConnected == true and $instance.status == "ACTIVE" and
      ($instance.versionInfo.agentVersion | type == "string" and length > 0) and
      any($instance.attributes[];
        .name == "ecs.instance-type" and .value == $expected_instance_type) and
      ($trunks | length) == 1 and
      any($instance.attachments[];
        .id == $trunks[0] and .type == "ElasticNetworkInterface" and .status == "ATTACHED") and
      ($instance.runningTasksCount | type == "number") and $instance.runningTasksCount >= 0 and
      ($instance.pendingTasksCount | type == "number") and $instance.pendingTasksCount >= 0
    )' <<<"$instance_state" >/dev/null; then
    echo "Capacity preflight failed: ECS agent, exact instance type or awsvpcTrunking attachment is invalid." >&2
    exit 3
  fi
  remaining_cpu=$(jq '[.containerInstances[].remainingResources[] | select(.name == "CPU") | .integerValue] | add // 0' <<<"$instance_state")
  remaining_memory=$(jq '[.containerInstances[].remainingResources[] | select(.name == "MEMORY") | .integerValue] | add // 0' <<<"$instance_state")
  active_tasks=$(jq '[.containerInstances[] | .runningTasksCount + .pendingTasksCount] | add // 0' <<<"$instance_state")
  remaining_awsvpc_tasks=$((awsvpc_task_limit - active_tasks))
  (( remaining_cpu >= required_cpu )) || {
    echo "Capacity preflight failed: registered ECS CPU is below the release reservation." >&2; exit 3;
  }
  (( remaining_memory >= required_memory )) || {
    echo "Capacity preflight failed: registered ECS memory is below the release reservation." >&2; exit 3;
  }
  (( remaining_awsvpc_tasks >= task_slots )) || {
    echo "Capacity preflight failed: reviewed awsvpcTrunking task capacity is below the release task count." >&2; exit 3;
  }

  local available_ips
  available_ips=$(aws ec2 describe-subnets \
    --region "$region" \
    --subnet-ids $(jq -r '.private_subnet_ids[]' <<<"$contract") \
    --query 'sum(Subnets[].AvailableIpAddressCount)' --output text)
  (( available_ips >= task_slots + 8 )) || {
    echo "Capacity preflight failed: private subnet IP headroom is below fleet slots plus eight." >&2; exit 3;
  }
}

start_services_in_order() {
  mapfile -t runtime_services < <(jq -r '.services | keys[]' "$module/config/runtime-services.json")
  declare -A required=()
  local service
  for service in "${runtime_services[@]}"; do required[$service]=1; done

  while IFS= read -r service; do
    [[ -n "${required[$service]:-}" ]] || continue
    target="aws_ecs_service.service[\"$service\"]"
    targeted_plan_and_apply "$target" "$service"
    contract=$(terraform -chdir="$module" output -json release_contract)
    cluster=$(jq -er '.cluster_arn' <<<"$contract")
    aws ecs wait services-stable --region "$region" --cluster "$cluster" --services "$service"
    status=$(aws ecs describe-services --region "$region" --cluster "$cluster" --services "$service" --output json)
    if ! jq -e '.failures|length == 0' <<<"$status" >/dev/null || \
       ! jq -e '.services[0] | .desiredCount == 1 and .runningCount == 1 and .pendingCount == 0' <<<"$status" >/dev/null; then
      echo "Ordered release failed to stabilise: $service" >&2
      exit 3
    fi
    unset 'required[$service]'
    echo "Ordered release healthy: $service"
  done < <(jq -r '.buildOrder[]' "$repository_root/config/services.json")

  (( ${#required[@]} == 0 )) || { echo "Build order omitted a runtime service." >&2; exit 3; }
}

start_clamav_scanner() {
  local expected_scanners contract cluster status
  expected_scanners=$(terraform -chdir="$module" output -json capacity_contract | jq -er '.deployment_copy_multiplier')

  # Start and prove the no-task-role scanner before Document Store or any
  # upstream document path. The full reviewed plan is still reconciled after
  # every application service has stabilised in dependency order.
  targeted_plan_and_apply aws_ecs_service.clamav clamav
  contract=$(terraform -chdir="$module" output -json release_contract)
  cluster=$(jq -er '.cluster_arn' <<<"$contract")
  aws ecs wait services-stable --region "$region" --cluster "$cluster" --services clamav
  status=$(aws ecs describe-services --region "$region" --cluster "$cluster" --services clamav --output json)
  if ! jq -e --argjson expected "$expected_scanners" '
    (.failures | length) == 0 and
    (.services | length) == 1 and
    (.services[0] | .desiredCount == $expected and .runningCount == $expected and .pendingCount == 0)
  ' <<<"$status" >/dev/null; then
    echo "Ordered release failed to stabilise the isolated ClamAV scanner fleet." >&2
    exit 3
  fi
  echo "Ordered release healthy: clamav ($expected_scanners task(s), no application task role)"
}

assert_dark_quiesced_source() {
  local endpoint emergency listener_arn listener rules service cluster status running_tasks
  endpoint=$(terraform -chdir="$module" output -json public_endpoint)
  [[ "$(jq -er '.activated' <<<"$endpoint")" == false ]] || {
    echo "Restore-source preparation refused: Terraform state does not keep the public entrypoint dark." >&2
    exit 3
  }
  emergency=$(terraform -chdir="$module" output -json emergency_darken_contract)
  listener_arn=$(jq -er '.https_listener_arn | select(startswith("arn:aws:elasticloadbalancing:"))' <<<"$emergency")
  [[ "$(jq -er '.stripe_webhook_rule_arn' <<<"$emergency")" == "" ]] || {
    echo "Restore-source preparation refused: a Stripe forwarding rule remains public." >&2
    exit 3
  }
  listener=$(aws elbv2 describe-listeners --region "$region" --listener-arns "$listener_arn" --output json)
  jq -e '
    (.Listeners | length) == 1 and
    (.Listeners[0].DefaultActions | length) == 1 and
    .Listeners[0].DefaultActions[0].Type == "fixed-response" and
    .Listeners[0].DefaultActions[0].FixedResponseConfig.StatusCode == "503"
  ' <<<"$listener" >/dev/null || {
    echo "Restore-source preparation refused: the live HTTPS listener is not a fixed 503." >&2
    exit 3
  }
  rules=$(aws elbv2 describe-rules --region "$region" --listener-arn "$listener_arn" --output json)
  jq -e '
    (.Rules | length) == 1 and .Rules[0].IsDefault == true and
    (.Rules[0].Actions | length) == 1 and .Rules[0].Actions[0].Type == "fixed-response" and
    .Rules[0].Actions[0].FixedResponseConfig.StatusCode == "503"
  ' <<<"$rules" >/dev/null || {
    echo "Restore-source preparation refused: an HTTPS listener rule could still forward traffic." >&2
    exit 3
  }

  cluster=$(jq -er '.cluster_name' <<<"$emergency")
  while IFS= read -r service; do
    status=$(aws ecs describe-services --region "$region" --cluster "$cluster" --services "$service" --output json)
    jq -e '
      (.failures | length) == 0 and (.services | length) == 1 and
      (.services[0] | .desiredCount == 0 and .runningCount == 0 and .pendingCount == 0)
    ' <<<"$status" >/dev/null || {
      echo "Restore-source preparation refused: service is not quiesced: $service" >&2
      exit 3
    }
  done < <(jq -r '.service_names[]' <<<"$emergency")
  running_tasks=$(aws ecs list-tasks \
    --region "$region" --cluster "$cluster" --desired-status RUNNING --output json)
  jq -e '.taskArns | length == 0' <<<"$running_tasks" >/dev/null || {
    echo "Restore-source preparation refused: a one-shot or unmanaged ECS task is still running." >&2
    exit 3
  }
  echo "Restore-source precondition passed: every service is stopped and the live listener is a fixed 503."
}

wait_for_paired_backup_jobs() {
  local rds_job_id=$1
  local s3_job_id=$2
  local rds_job_file=$3
  local s3_job_file=$4
  local timeout=${BACKUP_WAIT_TIMEOUT_SECONDS:-14400}
  [[ "$timeout" =~ ^[0-9]+$ ]] && (( timeout >= 60 && timeout <= 14400 )) || {
    echo "Backup wait timeout must be 60-14400 seconds." >&2
    exit 2
  }
  local deadline=$(( $(date +%s) + timeout ))
  local rds_state s3_state state label message job_file
  while (( $(date +%s) < deadline )); do
    aws backup describe-backup-job --region "$region" --backup-job-id "$rds_job_id" --output json >"$rds_job_file"
    aws backup describe-backup-job --region "$region" --backup-job-id "$s3_job_id" --output json >"$s3_job_file"
    rds_state=$(jq -er '.State' "$rds_job_file")
    s3_state=$(jq -er '.State' "$s3_job_file")
    for label in RDS S3; do
      if [[ "$label" == RDS ]]; then state=$rds_state; job_file=$rds_job_file; else state=$s3_state; job_file=$s3_job_file; fi
      case "$state" in
        COMPLETED|CREATED|PENDING|RUNNING|ABORTING) ;;
        FAILED|ABORTED|EXPIRED|PARTIAL)
          message=$(jq -r '.StatusMessage // "no status message"' "$job_file")
          echo "$label restore-source backup reached terminal state $state: $message" >&2
          exit 3
          ;;
        *) echo "$label restore-source backup returned unexpected state: $state" >&2; exit 3 ;;
      esac
    done
    if [[ "$rds_state" == COMPLETED && "$s3_state" == COMPLETED ]]; then
      chmod 0600 "$rds_job_file" "$s3_job_file"
      echo "Paired restore-source backup jobs completed."
      return 0
    fi
    echo "Waiting for paired restore-source backups: RDS=$rds_state S3=$s3_state"
    sleep 20
  done
  message="RDS=$rds_state S3=$s3_state"
  echo "Timed out after ${timeout}s waiting for paired restore-source backups ($message). Rerun the exact candidate/canary dispatch to resume the idempotent jobs without rewriting the canary." >&2
  exit 3
}

start_paired_restore_source_backups() {
  local recovery marker marker_file marker_sha tags_file contract vault_arn vault_name backup_role rds_arn bucket_arn
  local rds_result s3_result rds_job_id s3_job_id rds_job_file s3_job_file rds_tags_file s3_tags_file evidence_file
  recovery=$(terraform -chdir="$module" output -json data_recovery)
  contract=$(terraform -chdir="$module" output -json release_contract)
  vault_arn=$(jq -er '.backup_vault_arn' <<<"$recovery")
  [[ "$vault_arn" =~ ^arn:aws:backup:eu-west-2:[0-9]{12}:backup-vault:jsc-public-beta-customer-data$ ]] || {
    echo "Restore-source backup vault is outside the exact customer-data scope." >&2; exit 3;
  }
  vault_name=${vault_arn##*:}
  backup_role=$(jq -er '.backup_role_arn' <<<"$recovery")
  [[ "$backup_role" =~ ^arn:aws:iam::[0-9]{12}:role/jsc-public-beta-backup$ ]] || {
    echo "Restore-source backup service role is out of scope." >&2; exit 3;
  }
  rds_arn=$(jq -er '.postgres_arn' <<<"$recovery")
  bucket_arn=$(jq -er '.document_bucket_arn' <<<"$recovery")

  mkdir -p -- "$restore_source_output_directory"
  marker_file="$restore_source_output_directory/restore-source-canary-marker.json"
  evidence_file="$restore_source_output_directory/restore-source-evidence.json"
  for path in "$marker_file" "$evidence_file"; do
    [[ ! -e "$path" && ! -L "$path" ]] || { echo "Refusing to overwrite restore-source evidence: $path" >&2; exit 2; }
  done
  marker=$(aws ssm get-parameter --region "$region" \
    --name "$(jq -er '.restore_source_canary_marker' <<<"$contract")" \
    --query 'Parameter.Value' --output text)
  [[ "$(jq -er '.releaseId' <<<"$marker")" == "$release_id" ]] || {
    echo "Restore-source marker belongs to another release." >&2; exit 3;
  }
  [[ "$(jq -er '.releaseAttestationId' <<<"$marker")" == "$(jq -er '.release_attestation_id' <<<"$contract")" ]] || {
    echo "Restore-source marker belongs to another applied candidate contract." >&2; exit 3;
  }
  [[ "$(jq -er '.canaryId' <<<"$marker")" == "$restore_source_canary_id" ]] || {
    echo "Restore-source marker belongs to another canary." >&2; exit 3;
  }
  printf '%s' "$marker" >"$marker_file"
  chmod 0600 "$marker_file"
  marker_sha=$(printf '%s' "$marker" | sha256sum | cut -d' ' -f1)
  tags_file=$(mktemp /tmp/jsc-restore-source-tags.XXXXXX.json)
  temporary_release_files+=("$tags_file")
  jq -n --arg release "$release_id" --arg canary "$restore_source_canary_id" --arg marker "$marker_sha" '{
    Application:"Job Seeker Copilot",Environment:"public-beta",RestoreTest:"quarterly",
    ReleaseId:$release,RestoreSourceCanary:$canary,RestoreSourceMarker:$marker
  }' >"$tags_file"

  rds_result=$(aws backup start-backup-job --region "$region" --backup-vault-name "$vault_name" \
    --resource-arn "$rds_arn" --iam-role-arn "$backup_role" --lifecycle DeleteAfterDays=35 \
    --idempotency-token "$(printf '%s' "$release_id:$restore_source_canary_id:$marker_sha:rds" | sha256sum | cut -d' ' -f1)" \
    --recovery-point-tags "file://$tags_file" --output json)
  s3_result=$(aws backup start-backup-job --region "$region" --backup-vault-name "$vault_name" \
    --resource-arn "$bucket_arn" --iam-role-arn "$backup_role" --lifecycle DeleteAfterDays=35 \
    --idempotency-token "$(printf '%s' "$release_id:$restore_source_canary_id:$marker_sha:s3" | sha256sum | cut -d' ' -f1)" \
    --recovery-point-tags "file://$tags_file" --output json)
  rds_job_id=$(jq -er '.BackupJobId | select(test("^[A-Za-z0-9-]{8,128}$"))' <<<"$rds_result")
  s3_job_id=$(jq -er '.BackupJobId | select(test("^[A-Za-z0-9-]{8,128}$"))' <<<"$s3_result")
  rds_job_file="$restore_source_output_directory/rds-backup-job.json"
  s3_job_file="$restore_source_output_directory/s3-backup-job.json"
  wait_for_paired_backup_jobs "$rds_job_id" "$s3_job_id" "$rds_job_file" "$s3_job_file"
  rds_tags_file="$restore_source_output_directory/rds-recovery-point-tags.json"
  s3_tags_file="$restore_source_output_directory/s3-recovery-point-tags.json"
  aws backup list-tags --region "$region" \
    --resource-arn "$(jq -er '.RecoveryPointArn' "$rds_job_file")" --output json >"$rds_tags_file"
  aws backup list-tags --region "$region" \
    --resource-arn "$(jq -er '.RecoveryPointArn' "$s3_job_file")" --output json >"$s3_tags_file"
  chmod 0600 "$rds_tags_file" "$s3_tags_file"
  python3 "$repository_root/scripts/aws/render_restore_source_evidence.py" \
    --marker "$marker_file" --rds-backup-job "$rds_job_file" --s3-backup-job "$s3_job_file" \
    --rds-recovery-point-tags "$rds_tags_file" --s3-recovery-point-tags "$s3_tags_file" \
    --image-manifest "$manifest" --provenance "$release_provenance" \
    --candidate-build-run-id "$candidate_build_run_id" --created-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --output "$evidence_file"
  python3 "$repository_root/scripts/aws/validate_restore_source_evidence.py" \
    --evidence "$evidence_file" --image-manifest "$manifest" --provenance "$release_provenance" \
    --candidate-build-run-id "$candidate_build_run_id"
  echo "Paired canary-bound recovery points are ready:"
  jq -r '"RDS=" + .backupJobs.rds.recoveryPointArn, "S3=" + .backupJobs.s3.recoveryPointArn' "$evidence_file"
}

prepare_restore_source() {
  local expected_confirmation="PREPARE RESTORE SOURCE $release_id $restore_source_canary_id"
  [[ "$confirmation" == "$expected_confirmation" ]] || {
    echo "Refusing: confirmation must equal '$expected_confirmation'." >&2
    exit 2
  }

  stage_state_machine_prerequisites
  plan_and_apply 0 false restore-source-dark
  verify_account_email_ses
  "$repository_root/scripts/aws/seed-runtime-secrets.sh" public-beta
  assert_capacity_ready
  verify_current_iam_contract 0 false restore-source-bootstrap-iam
  "$repository_root/scripts/aws/run_release_operator.sh" database-bootstrap "$module"
  write_marker database-bootstrap

  APPLICATION_DESIRED_COUNT=1 PUBLIC_ENTRYPOINT_ENABLED=false review_plan_only
  start_clamav_scanner
  start_services_in_order
  plan_and_apply 1 false restore-source-private
  verify_current_iam_contract 1 false restore-source-migrations-iam
  "$repository_root/scripts/aws/run_release_operator.sh" migration-verification "$module"

  # Stop the fleet before writing the canary so no application task can race
  # with the exact source state selected by the paired on-demand backups.
  plan_and_apply 0 false restore-source-quiesce
  assert_dark_quiesced_source
  export RESTORE_SOURCE_CANARY_ID="$restore_source_canary_id"
  verify_current_iam_contract 0 false restore-source-canary-iam
  "$repository_root/scripts/aws/run_release_operator.sh" restore-source-canary-prepare "$module"
  verify_current_iam_contract 0 false restore-source-canary-verify-iam
  "$repository_root/scripts/aws/run_release_operator.sh" restore-source-canary-verify "$module"
  assert_dark_quiesced_source
  start_paired_restore_source_backups
  assert_dark_quiesced_source
  echo "Restore source prepared for $release_id; traffic stayed fixed 503 and all application services remain stopped."
}

prepare_private_fleet() {
  local verb=$1
  [[ "$confirmation" == "$verb $release_id" ]] || {
    echo "Refusing: confirmation must equal '$verb $release_id'." >&2; exit 2;
  }

  # Maintenance first: stop every app task. This is the intentional lean-node
  # stop-first strategy and prevents unschedulable old+new duplication.
  stage_state_machine_prerequisites
  plan_and_apply 0 false "${verb,,}-dark"
  verify_account_email_ses
  "$repository_root/scripts/aws/seed-runtime-secrets.sh" public-beta
  assert_capacity_ready
  verify_current_iam_contract 0 false database-bootstrap-iam
  "$repository_root/scripts/aws/run_release_operator.sh" database-bootstrap "$module"
  write_marker database-bootstrap

  # Render/review the eventual private-fleet change before targeted ordered starts.
  APPLICATION_DESIRED_COUNT=1 PUBLIC_ENTRYPOINT_ENABLED=false review_plan_only
  start_clamav_scanner
  start_services_in_order
  plan_and_apply 1 false "${verb,,}-private"
  verify_current_iam_contract 1 false migration-operator-iam
  "$repository_root/scripts/aws/run_release_operator.sh" migration-verification "$module"
  verify_current_iam_contract 1 false preflight-operator-iam
  "$repository_root/scripts/aws/run_release_operator.sh" release-preflight "$module"
  write_marker preflight
  echo "$verb complete for $release_id; the public listener remains a fixed 503 until a separate ACTIVATE dispatch."
}

case "$action" in
  plan)
    review_plan_only
    ;;
  foundation)
    [[ "$confirmation" == "FOUNDATION public-beta" ]] || {
      echo "Refusing: confirmation must equal 'FOUNDATION public-beta'." >&2; exit 2;
    }
    verify_existing_launch_template_authorization
    plan_and_apply 0 false foundation
    verify_account_email_ses
    ;;
  prepare)
    prepare_private_fleet PREPARE
    ;;
  rollback)
    prepare_private_fleet ROLLBACK
    ;;
  prepare-restore-source)
    prepare_restore_source
    ;;
  activate)
    [[ "$confirmation" == "ACTIVATE $release_id" ]] || {
      echo "Refusing: confirmation must equal 'ACTIVATE $release_id'." >&2; exit 2;
    }
    assert_exact_prepared_release
    verify_account_email_ses
    verify_current_iam_contract 1 false activation-operator-iam
    "$repository_root/scripts/aws/run_release_operator.sh" release-preflight "$module"
    write_marker preflight
    assert_marker preflight
    plan_and_apply 1 true activate
    echo "Public listener activated for $release_id."
    ;;
esac
