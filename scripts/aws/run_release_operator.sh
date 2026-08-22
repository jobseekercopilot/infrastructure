#!/usr/bin/env bash
set -euo pipefail

purpose=${1:-}
module_directory=${2:-}
region=${AWS_REGION:-eu-west-2}

case "$purpose" in
  database-bootstrap|migration-verification|release-preflight) ;;
  *) echo "Usage: $0 {database-bootstrap|migration-verification|release-preflight} /terraform/module" >&2; exit 2 ;;
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
esac

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
  --network-configuration "$network" \
  --query 'tasks[0].taskArn' \
  --output text)
if [[ ! "$task_arn" =~ ^arn:aws:ecs: ]]; then
  echo "Release operator failed to start: $purpose" >&2
  exit 3
fi

echo "Waiting for one-shot operator: $purpose"
aws ecs wait tasks-stopped --region "$region" --cluster "$cluster" --tasks "$task_arn"
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
