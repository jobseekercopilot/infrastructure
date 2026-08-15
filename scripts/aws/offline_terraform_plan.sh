#!/usr/bin/env bash
set -euo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
module="$repository_root/aws/public-beta"
validation_root=$(mktemp -d /tmp/jsc-public-beta-offline.XXXXXX)

cleanup() {
  case "$validation_root" in /tmp/jsc-public-beta-offline.*) rm -rf "$validation_root" ;; esac
}
trap cleanup EXIT HUP INT TERM

for source in "$module"/*.tf; do
  [[ "$(basename "$source")" == "backend.tf" ]] && continue
  cp "$source" "$validation_root/"
done
cp -R "$module/config" "$validation_root/config"
cp "$module/.terraform.lock.hcl" "$validation_root/.terraform.lock.hcl"

terraform -chdir="$validation_root" init -backend=false -input=false -lockfile=readonly
terraform -chdir="$validation_root" validate
plan_log="$validation_root/plan.log"
AWS_ACCESS_KEY_ID=offline-validation \
AWS_SECRET_ACCESS_KEY=offline-validation \
AWS_REGION=eu-west-2 \
AWS_EC2_METADATA_DISABLED=true \
  terraform -chdir="$validation_root" plan \
    -no-color \
    -compact-warnings \
    -refresh=false \
    -input=false \
    -lock=false \
    -var=offline_validation=true \
    -out="$validation_root/public-beta.tfplan" >"$plan_log" 2>&1 || {
      cat "$plan_log" >&2
      exit 1
    }

plan_summary=$(sed -n '/^Plan: /p' "$plan_log" | tail -n 1)
[[ -n "$plan_summary" ]] || { cat "$plan_log" >&2; echo "Offline plan did not produce a resource summary." >&2; exit 1; }
echo "$plan_summary"
echo "Account-free dark topology plan passed; no AWS state, AWS calls or live credentials were used."
