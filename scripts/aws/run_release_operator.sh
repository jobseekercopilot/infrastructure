#!/usr/bin/env bash
set -euo pipefail

purpose=${1:-}
module_directory=${2:-}
region=${AWS_REGION:-eu-west-2}

case "$purpose" in
  database-bootstrap|migration-verification|release-preflight|restore-source-canary-prepare|restore-source-canary-verify) ;;
  *) echo "Usage: $0 {database-bootstrap|migration-verification|release-preflight|restore-source-canary-prepare|restore-source-canary-verify} /terraform/module" >&2; exit 2 ;;
esac
if [[ "$region" != "eu-west-2" || ! -d "$module_directory" ]]; then
  echo "Refusing release operator outside eu-west-2 or without the Terraform module." >&2
  exit 2
fi

for command_name in aws jq terraform; do
  command -v "$command_name" >/dev/null || { echo "Missing required command: $command_name" >&2; exit 2; }
done

contract=$(terraform -chdir="$module_directory" output -json release_contract)
cluster=$(jq -er '.cluster_arn' <<<"$contract")
security_group=$(jq -er '.release_operator_security_group' <<<"$contract")
subnets=$(jq -er '.private_subnet_ids | join(",")' <<<"$contract")
release_id=$(jq -er '.release_id' <<<"$contract")

case "$purpose" in
  database-bootstrap) task_definition=$(jq -er '.database_bootstrap_task_definition' <<<"$contract") ;;
  migration-verification) task_definition=$(jq -er '.migration_verification_task_definition' <<<"$contract") ;;
  release-preflight) task_definition=$(jq -er '.release_preflight_task_definition' <<<"$contract") ;;
  restore-source-canary-prepare|restore-source-canary-verify)
    task_definition=$(jq -er '.restore_source_canary_task_definition' <<<"$contract")
    ;;
esac

run_task_arguments=()
if [[ "$purpose" == restore-source-canary-* ]]; then
  canary_id=${RESTORE_SOURCE_CANARY_ID:-}
  [[ "$canary_id" =~ ^[a-z0-9][a-z0-9-]{6,30}[a-z0-9]$ ]] || {
    echo "Release operator refused: restore-source canary ID must be 8-32 lowercase letters, digits or interior hyphens." >&2
    exit 2
  }
  canary_mode=${purpose##*-}
  overrides=$(jq -cn --arg mode "$canary_mode" --arg canary "$canary_id" '{
    containerOverrides:[{
      name:"restore-source-canary",
      environment:[
        {name:"RESTORE_SOURCE_CANARY_MODE",value:$mode},
        {name:"RESTORE_SOURCE_CANARY_ID",value:$canary}
      ]
    }]
  }')
  run_task_arguments+=(--overrides "$overrides")
fi

container_instances=$(aws ecs list-container-instances \
  --region "$region" --cluster "$cluster" --status ACTIVE --output json)
mapfile -t instance_arns < <(jq -r '.containerInstanceArns[]' <<<"$container_instances")
if (( ${#instance_arns[@]} == 0 )); then
  echo "Release operator refused: no ACTIVE ECS container instance." >&2
  exit 3
fi
instance_state=$(aws ecs describe-container-instances \
  --region "$region" --cluster "$cluster" \
  --container-instances "${instance_arns[@]}" --output json)
if ! jq -e '
  (.failures | length) == 0 and
  all(.containerInstances[];
    .agentConnected == true and .status == "ACTIVE" and
    any(.attributes[]; .name == "ecs.awsvpc-trunk-id" and (.value | length) > 0)
  )' <<<"$instance_state" >/dev/null; then
  echo "Release operator refused: ECS agent/awsvpcTrunking registration is not healthy." >&2
  exit 3
fi

network="awsvpcConfiguration={subnets=[$subnets],securityGroups=[$security_group],assignPublicIp=DISABLED}"
started_by="jsc-${purpose:0:12}-${release_id: -8}"
task_arn=$(aws ecs run-task \
  --region "$region" \
  --cluster "$cluster" \
  --task-definition "$task_definition" \
  --launch-type EC2 \
  --count 1 \
  --started-by "$started_by" \
  --tags 'key=Application,value=Job Seeker Copilot' 'key=Environment,value=public-beta' 'key=ManagedBy,value=Terraform' 'key=Purpose,value=ReleaseOperator' \
  --network-configuration "$network" \
  "${run_task_arguments[@]}" \
  --query 'tasks[0].taskArn' \
  --output text)
if [[ ! "$task_arn" =~ ^arn:aws:ecs: ]]; then
  echo "Release operator failed to start: $purpose" >&2
  exit 3
fi

echo "Waiting for one-shot operator: $purpose"
if ! aws ecs wait tasks-stopped --region "$region" --cluster "$cluster" --tasks "$task_arn"; then
  echo "Release operator exceeded its bounded waiter; stopping the exact task: $purpose" >&2
  aws ecs stop-task \
    --region "$region" --cluster "$cluster" --task "$task_arn" \
    --reason "JSC protected release operator waiter expired" >/dev/null
  if ! aws ecs wait tasks-stopped --region "$region" --cluster "$cluster" --tasks "$task_arn"; then
    echo "Release operator could not be verified stopped after timeout: $purpose" >&2
    exit 3
  fi
  stopped_task=$(aws ecs describe-tasks --region "$region" --cluster "$cluster" --tasks "$task_arn" --output json)
  jq -e '
    (.failures | length) == 0 and (.tasks | length) == 1 and .tasks[0].lastStatus == "STOPPED"
  ' <<<"$stopped_task" >/dev/null || {
    echo "Release operator stop could not be proven after timeout: $purpose" >&2
    exit 3
  }
  echo "Release operator timed out and was stopped; no success evidence will be emitted: $purpose" >&2
  exit 3
fi
task=$(aws ecs describe-tasks --region "$region" --cluster "$cluster" --tasks "$task_arn" --output json)
if ! jq -e '
  (.failures | length) == 0 and
  (.tasks | length) == 1 and
  all(.tasks[0].containers[]; .exitCode == 0)
' <<<"$task" >/dev/null; then
  reason=$(jq -r '.tasks[0].stoppedReason // .failures[0].reason // "unknown"' <<<"$task")
  echo "Release operator failed: $purpose ($reason). Inspect /jsc/public-beta/release-operator logs." >&2
  exit 3
fi

echo "Release operator passed: $purpose"
