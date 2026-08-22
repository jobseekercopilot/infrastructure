#!/usr/bin/env bash
set -euo pipefail

integration=${1:-}
json_path=${2:-}
region=${AWS_REGION:-eu-west-2}

case "$integration" in
  reed|adzuna|jsearch|apprenticeships|google_maps|openai|stripe) ;;
  *) echo "Usage: $0 {reed|adzuna|jsearch|apprenticeships|google_maps|openai|stripe} /secure/input.json" >&2; exit 2 ;;
esac

if [[ "$region" != "eu-west-2" || ! -f "$json_path" ]]; then
  echo "Refusing: eu-west-2 and an existing input file are required." >&2
  exit 2
fi

permissions=$(stat -c '%a' "$json_path")
case "$permissions" in
  400|600) ;;
  *) echo "Refusing input file permissions $permissions; require exactly 400 or 600." >&2; exit 2 ;;
esac

case "$integration" in
  reed) required_keys='["api_key"]' ;;
  adzuna) required_keys='["app_id","app_key"]' ;;
  jsearch) required_keys='["api_key"]' ;;
  apprenticeships) required_keys='["api_key"]' ;;
  google_maps) required_keys='["api_key"]' ;;
  openai) required_keys='["api_key"]' ;;
  stripe) required_keys='["secret_key","webhook_secret"]' ;;
esac

jq -e \
  --argjson required_keys "$required_keys" \
  'type == "object" and (keys | sort) == ($required_keys | sort)
   and all(.[]; type == "string" and length >= 8)' \
  "$json_path" >/dev/null || {
    echo "Refusing external secret with missing, extra or invalid fields for $integration." >&2
    exit 3
  }
if [[ "$integration" == stripe ]]; then
  jq -e \
    '.secret_key | (startswith("sk_live_") or startswith("rk_live_"))' "$json_path" >/dev/null &&
  jq -e \
    '.webhook_secret | startswith("whsec_")' "$json_path" >/dev/null || {
    echo "Refusing non-live Stripe credentials in the protected production secret." >&2
      exit 3
    }
fi

aws secretsmanager put-secret-value \
  --region "$region" \
  --secret-id "jsc-public-beta/integration/$integration" \
  --secret-string "file://$json_path" \
  --query VersionId \
  --output text >/dev/null

echo "Stored external secret for $integration without printing its value."
