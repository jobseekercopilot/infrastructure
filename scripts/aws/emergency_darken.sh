#!/usr/bin/env bash
set -euo pipefail

release_id=${1:-}
region=${AWS_REGION:-}
confirmation=${RELEASE_CONFIRMATION:-}

if [[ ! "$release_id" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7,40}$ ]]; then
  echo "Usage: $0 YYYYMMDDTHHMMSSZ-GITSHA" >&2
  exit 2
fi
if [[ "$region" != "eu-west-2" ]] || [[ "${GITHUB_REF:-}" != "refs/heads/main" ]]; then
  echo "Refusing: emergency darkening requires protected main in eu-west-2." >&2
  exit 2
fi
if [[ "$confirmation" != "DARKEN $release_id" ]]; then
  echo "Refusing: confirmation must equal 'DARKEN $release_id'." >&2
  exit 2
fi
if [[ -z "${AWS_ACCESS_KEY_ID:-}" ]] || [[ -z "${AWS_SECRET_ACCESS_KEY:-}" ]] || [[ -z "${AWS_SESSION_TOKEN:-}" ]]; then
  echo "Refusing: a protected short-lived AWS session is required." >&2
  exit 2
fi
for command_name in aws jq sort terraform; do
  command -v "$command_name" >/dev/null || { echo "Missing required command: $command_name" >&2; exit 2; }
done

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
module="$repository_root/aws/public-beta"
runtime_manifest="$module/config/runtime-services.json"
export AWS_PAGER=""

# Read only the already-applied, non-secret state outputs. Emergency containment
# deliberately does not re-plan the application: expired/revoked commercial or
# legal approvals must never prevent the public edge from being closed.
release_contract=$(terraform -chdir="$module" output -json release_contract)
darken_contract=$(terraform -chdir="$module" output -json emergency_darken_contract)
current_release_id=$(jq -er .release_id <<<"$release_contract")
[[ "$current_release_id" == "$release_id" ]] || {
  echo "Refusing: requested release is not the currently applied Terraform release." >&2
  exit 3
}

cluster_name=$(jq -er .cluster_name <<<"$darken_contract")
account_id=$(jq -er .aws_account_id <<<"$darken_contract")
https_listener_arn=$(jq -er .https_listener_arn <<<"$darken_contract")
stripe_rule_arn=$(jq -er .stripe_webhook_rule_arn <<<"$darken_contract")
mapfile -t services < <(jq -er '.service_names[]' <<<"$darken_contract")
mapfile -t expected_services < <(jq -er '.services | keys[]' "$runtime_manifest")
expected_services+=(clamav)

[[ "$account_id" =~ ^[0-9]{12}$ ]] || { echo "Refusing: applied state has no valid AWS account ID." >&2; exit 3; }
caller_account_id=$(aws sts get-caller-identity --query Account --output text)
[[ "$caller_account_id" == "$account_id" ]] || {
  echo "Refusing: protected AWS session does not match the applied account." >&2
  exit 3
}
[[ "$cluster_name" == "jsc-public-beta" ]] || { echo "Refusing: unexpected ECS cluster name." >&2; exit 3; }
listener_prefix="arn:aws:elasticloadbalancing:$region:$account_id:listener/app/"
rule_prefix="arn:aws:elasticloadbalancing:$region:$account_id:listener-rule/app/"
[[ "$https_listener_arn" == "$listener_prefix"* ]] || {
  echo "Refusing: applied state does not contain the reviewed eu-west-2 HTTPS listener." >&2
  exit 3
}
[[ ${#services[@]} -eq 28 ]] || { echo "Refusing: applied state does not contain all 28 runtime services." >&2; exit 3; }
[[ "$(printf '%s\n' "${services[@]}" | sort)" == "$(printf '%s\n' "${expected_services[@]}" | sort)" ]] || {
  echo "Refusing: applied service set differs from the reviewed runtime manifest." >&2
  exit 3
}

fixed_response=$(jq -cn '[{
  Type:"fixed-response",
  FixedResponseConfig:{
    StatusCode:"503",
    ContentType:"text/plain",
    MessageBody:"Job Seeker Copilot is temporarily unavailable."
  }
}]')

# Close the exceptional Stripe path first, then the listener default. Both are
# verified before any slower ECS draining begins.
if [[ -n "$stripe_rule_arn" ]]; then
  [[ "$stripe_rule_arn" == "$rule_prefix"* ]] || {
    echo "Refusing: applied Stripe webhook rule ARN is outside the reviewed listener." >&2
    exit 3
  }
  aws elbv2 modify-rule --region "$region" --rule-arn "$stripe_rule_arn" \
    --actions "$fixed_response" >/dev/null
  aws elbv2 describe-rules --region "$region" --rule-arns "$stripe_rule_arn" --output json |
    jq -e '.Rules | length == 1 and (.[] | .Actions | length == 1 and
      .[0].Type == "fixed-response" and
      .[0].FixedResponseConfig.StatusCode == "503")' >/dev/null
fi

aws elbv2 modify-listener --region "$region" --listener-arn "$https_listener_arn" \
  --default-actions "$fixed_response" >/dev/null
aws elbv2 describe-listeners --region "$region" --listener-arns "$https_listener_arn" --output json |
  jq -e '.Listeners | length == 1 and (.[] | .DefaultActions | length == 1 and
    .[0].Type == "fixed-response" and
    .[0].FixedResponseConfig.StatusCode == "503")' >/dev/null

echo "Emergency public edge is fixed at HTTP 503 for $release_id; draining application and scanner tasks."

update_failures=0
for service in "${services[@]}"; do
  # Lean beta owns desired count directly in ECS and deliberately has no
  # Application Auto Scaling targets. Keeping this containment path free of
  # RegisterScalableTarget also prevents a protected release identity from
  # claiming an unrelated opaque target before draining the exact fleet.
  if ! aws ecs update-service --region "$region" --cluster "$cluster_name" \
    --service "$service" --desired-count 0 >/dev/null; then
    echo "Failed to request task drain for $service" >&2
    update_failures=$((update_failures + 1))
  fi
done

# A runner/API interruption can strand a tagged one-shot operator between
# RunTask and its normal timeout cleanup. Stop only the protected release-
# operator tasks; service tasks do not carry Purpose=ReleaseOperator and the
# IAM grant independently enforces this exact tag boundary.
running_tasks=$(aws ecs list-tasks \
  --region "$region" --cluster "$cluster_name" --desired-status RUNNING --output json)
while IFS= read -r task_arn; do
  [[ -n "$task_arn" ]] || continue
  task_tags=$(aws ecs list-tags-for-resource --region "$region" --resource-arn "$task_arn" --output json)
  if jq -e '
    (.tags | from_entries) as $tags |
    $tags.Application == "Job Seeker Copilot" and
    $tags.Environment == "public-beta" and
    $tags.ManagedBy == "Terraform" and
    $tags.Purpose == "ReleaseOperator"
  ' <<<"$task_tags" >/dev/null; then
    aws ecs stop-task --region "$region" --cluster "$cluster_name" --task "$task_arn" \
      --reason "JSC emergency containment of protected release operator" >/dev/null
  fi
done < <(jq -r '.taskArns[]?' <<<"$running_tasks")

(( update_failures == 0 )) || {
  echo "Public edge is dark and tagged operators were stopped, but $update_failures task drain requests failed; investigate immediately." >&2
  exit 4
}

deadline=$((SECONDS + 1200))
while (( SECONDS < deadline )); do
  all_stopped=true
  for ((offset = 0; offset < ${#services[@]}; offset += 10)); do
    batch=("${services[@]:offset:10}")
    status=$(aws ecs describe-services --region "$region" --cluster "$cluster_name" \
      --services "${batch[@]}" --output json)
    if ! jq -e '(.failures | length) == 0 and all(.services[];
      .desiredCount == 0 and .runningCount == 0 and .pendingCount == 0)' <<<"$status" >/dev/null; then
      all_stopped=false
    fi
  done
  running_tasks=$(aws ecs list-tasks \
    --region "$region" --cluster "$cluster_name" --desired-status RUNNING --output json)
  if [[ "$all_stopped" == true ]] && jq -e '.taskArns | length == 0' <<<"$running_tasks" >/dev/null; then
    echo "Emergency darkening complete: public edge is 503 and all application/scanner/operator tasks are stopped."
    exit 0
  fi
  sleep 15
done

echo "Public edge is dark, but application/scanner tasks did not all stop within 20 minutes; investigate immediately." >&2
exit 4
