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

case "$action" in foundation|plan|prepare|activate|rollback) ;;
  *) echo "Usage: $0 {foundation|plan|prepare|activate|rollback}" >&2; exit 2 ;;
esac
if [[ "$region" != "eu-west-2" || -z "$tfvars_file" || -z "$approval_manifest" ]]; then
  echo "Refusing: eu-west-2, TF_VARS_FILE and APPROVAL_MANIFEST are required." >&2
  exit 2
fi

for command_name in aws jq mktemp terraform; do
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
if [[ "$action" != "foundation" ]]; then
  [[ -f "$landing_archive" ]] || { echo "Missing checksum-bound Landing release artifact." >&2; exit 2; }
  python3 "$repository_root/scripts/aws/validate_public_beta.py" \
    --release --image-manifest "$manifest" --approval-manifest "$approval_manifest" \
    --landing-archive "$landing_archive"
fi

common_arguments=(
  -input=false
  -lock-timeout=10m
  -var-file="$tfvars_file"
  -var=offline_validation=false
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

verify_live_release_iam() {
  local plan=$1
  local plan_json
  plan_json=$(mktemp /tmp/jsc-live-iam-plan.XXXXXX.json)
  temporary_release_files+=("$plan_json")
  terraform -chdir="$module" show -json "$plan" >"$plan_json"
  python3 "$repository_root/scripts/aws/verify_saved_release_plan.py" \
    --plan-json "$plan_json"
  python3 "$repository_root/scripts/aws/verify_live_release_iam.py" \
    --plan-json "$plan_json" \
    --backup-contract "$backup_policy_contract" \
    --region "$region"
  rm -f "$plan_json"
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

plan_and_apply() {
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
  terraform -chdir="$module" show -no-color "$plan"
  terraform -chdir="$module" apply -input=false "$plan"
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
  local plan
  plan=$(mktemp "/tmp/jsc-target-${label}.XXXXXX.tfplan")
  temporary_release_files+=("$plan")
  terraform -chdir="$module" plan "${common_arguments[@]}" \
    -parallelism=1 \
    -target="$target" \
    -var=application_desired_count=1 \
    -var=public_entrypoint_enabled=false \
    -out="$plan"
  verify_live_release_iam "$plan"
  terraform -chdir="$module" show -no-color "$plan"
  terraform -chdir="$module" apply -input=false "$plan"
  rm -f "$plan"
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
  local expected_nodes task_slots required_cpu required_memory
  expected_nodes=$(jq -er '.node_count' <<<"$capacity")
  task_slots=$(jq -er '.task_slots' <<<"$capacity")
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

  local instance_state remaining_cpu remaining_memory remaining_eni
  instance_state=$(aws ecs describe-container-instances \
    --region "$region" --cluster "$cluster" \
    --container-instances $(jq -r '.containerInstanceArns[]' <<<"$instances") \
    --output json)
  if ! jq -e '
    (.failures | length) == 0 and
    all(.containerInstances[];
      .agentConnected == true and .status == "ACTIVE" and
      (.versionInfo.agentVersion | type == "string" and length > 0) and
      any(.attributes[]; .name == "ecs.awsvpc-trunk-id" and (.value | length) > 0)
    )' <<<"$instance_state" >/dev/null; then
    echo "Capacity preflight failed: ECS agent/awsvpcTrunking registration is incomplete." >&2
    exit 3
  fi
  remaining_cpu=$(jq '[.containerInstances[].remainingResources[] | select(.name == "CPU") | .integerValue] | add // 0' <<<"$instance_state")
  remaining_memory=$(jq '[.containerInstances[].remainingResources[] | select(.name == "MEMORY") | .integerValue] | add // 0' <<<"$instance_state")
  remaining_eni=$(jq '[.containerInstances[].remainingResources[] | select(.name == "ENI") | .integerValue] | add // 0' <<<"$instance_state")
  (( remaining_cpu >= required_cpu )) || {
    echo "Capacity preflight failed: registered ECS CPU is below the release reservation." >&2; exit 3;
  }
  (( remaining_memory >= required_memory )) || {
    echo "Capacity preflight failed: registered ECS memory is below the release reservation." >&2; exit 3;
  }
  (( remaining_eni >= task_slots )) || {
    echo "Capacity preflight failed: registered branch-ENI capacity is below the release task count." >&2; exit 3;
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

prepare_private_fleet() {
  local verb=$1
  [[ "$confirmation" == "$verb $release_id" ]] || {
    echo "Refusing: confirmation must equal '$verb $release_id'." >&2; exit 2;
  }

  # Maintenance first: stop every app task. This is the intentional lean-node
  # stop-first strategy and prevents unschedulable old+new duplication.
  plan_and_apply 0 false "${verb,,}-dark"
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
    ;;
  prepare)
    prepare_private_fleet PREPARE
    ;;
  rollback)
    prepare_private_fleet ROLLBACK
    ;;
  activate)
    [[ "$confirmation" == "ACTIVATE $release_id" ]] || {
      echo "Refusing: confirmation must equal 'ACTIVATE $release_id'." >&2; exit 2;
    }
    assert_exact_prepared_release
    verify_current_iam_contract 1 false activation-operator-iam
    "$repository_root/scripts/aws/run_release_operator.sh" release-preflight "$module"
    write_marker preflight
    assert_marker preflight
    plan_and_apply 1 true activate
    echo "Public listener activated for $release_id."
    ;;
esac
