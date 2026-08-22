#!/usr/bin/env bash
set -euo pipefail

repository=${1:-}
environment_name=${2:-}
reviewer_login=${3:-}

if [[ ! "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] ||
   [[ ! "$environment_name" =~ ^production-(aws-plan|aws|build)$ ]] ||
   [[ ! "$reviewer_login" =~ ^[A-Za-z0-9-]{1,39}$ ]]; then
  echo "Usage: $0 owner/repository production-aws-plan|production-build|production-aws reviewer-login" >&2
  exit 2
fi

for command_name in gh jq; do
  command -v "$command_name" >/dev/null || {
    echo "Missing required command: $command_name" >&2
    exit 2
  }
done

environment_json=$(gh api --method GET \
  --header 'Accept: application/vnd.github+json' \
  --header 'X-GitHub-Api-Version: 2022-11-28' \
  "repos/$repository/environments/$environment_name")

jq -e --arg environment "$environment_name" --arg reviewer "$reviewer_login" '
  .name == $environment and
  .deployment_branch_policy.protected_branches == false and
  .deployment_branch_policy.custom_branch_policies == true and
  ([.protection_rules[]? | select(.type == "required_reviewers")] | length) == 1 and
  ([.protection_rules[]? | select(.type == "required_reviewers")][0] |
    .prevent_self_review == false and
    (.reviewers | type == "array" and length == 1) and
    .reviewers[0].type == "User" and
    .reviewers[0].reviewer.login == $reviewer)
' <<<"$environment_json" >/dev/null || {
  echo "Refusing: $environment_name must require the authorised solo reviewer $reviewer_login, allow self-review and use custom deployment branches." >&2
  exit 3
}

branch_policy_json=$(gh api --method GET \
  --header 'Accept: application/vnd.github+json' \
  --header 'X-GitHub-Api-Version: 2022-11-28' \
  "repos/$repository/environments/$environment_name/deployment-branch-policies?per_page=100")

jq -e '
  .total_count == 1 and
  (.branch_policies | type == "array" and length == 1) and
  .branch_policies[0].name == "main" and
  .branch_policies[0].type == "branch"
' <<<"$branch_policy_json" >/dev/null || {
  echo "Refusing: $environment_name must allow the exact main branch and no other deployment branch or tag." >&2
  exit 3
}

echo "Verified API-visible GitHub environment protection: $environment_name (authorised solo reviewer, self-review allowed, exact main branch)."
echo "Administrator bypass is not exposed by this REST response and remains a separately signed launch-approval gate." >&2
