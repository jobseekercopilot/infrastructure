#!/usr/bin/env bash
set -euo pipefail

release_id=${1:-}
output_directory=${2:-}
region=${AWS_REGION:-eu-west-2}
account_id=${AWS_ACCOUNT_ID:-}
rds_ca_url=${RDS_CA_BUNDLE_URL:-}
rds_ca_sha=${RDS_CA_BUNDLE_SHA256:-}
postgres_image=${POSTGRES_IMAGE:-}
landing_runtime_env_b64=${LANDING_RUNTIME_ENV_B64:-}
launch_approvals_file=${LAUNCH_APPROVALS_FILE:-}

if [[ ! "$release_id" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7,40}$ ]] || [[ -z "$output_directory" ]]; then
  echo "Usage: $0 YYYYMMDDTHHMMSSZ-GITSHA /output/directory" >&2
  exit 2
fi
if [[ "${GITHUB_REF:-}" != "refs/heads/main" ]] || [[ "$region" != "eu-west-2" ]] || [[ ! "$account_id" =~ ^[0-9]{12}$ ]]; then
  echo "Refusing: protected main, eu-west-2 and a 12-digit AWS account ID are required." >&2
  exit 2
fi
if [[ ! "$rds_ca_url" =~ ^https://truststore\.pki\.rds\.amazonaws\.com/ ]] || [[ ! "$rds_ca_sha" =~ ^[0-9a-f]{64}$ ]]; then
  echo "Refusing: authoritative RDS CA URL and reviewed SHA-256 are required." >&2
  exit 2
fi
if [[ ! "$postgres_image" =~ ^postgres:15\.[0-9]+-alpine@sha256:[0-9a-f]{64}$ ]]; then
  echo "Refusing: POSTGRES_IMAGE must pin PostgreSQL 15 Alpine by digest." >&2
  exit 2
fi
if [[ -z "$launch_approvals_file" ]] || [[ ! -f "$launch_approvals_file" ]] || [[ -L "$launch_approvals_file" ]]; then
  echo "Refusing: protected LAUNCH_APPROVALS_FILE must name a regular reviewed manifest." >&2
  exit 2
fi

for command_name in awk base64 curl docker gh git grep jq npm python3 sha256sum zstd; do
  command -v "$command_name" >/dev/null || { echo "Missing required command: $command_name" >&2; exit 2; }
done

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
workspace_root=$(dirname "$repository_root")
runtime_manifest="$repository_root/aws/public-beta/config/runtime-services.json"
template_manifest="$repository_root/aws/public-beta/config/image-manifest.json"
lock_file="$repository_root/config/workspace-lock.json"
landing_checkout="$workspace_root/job-seeker-copilot-landing"

if [[ -n "$(git -C "$repository_root" status --porcelain)" ]]; then
  echo "Refusing to build release images from a dirty Infrastructure checkout." >&2
  exit 2
fi
if [[ -n "${AWS_ACCESS_KEY_ID:-}" ]] || [[ -n "${AWS_SECRET_ACCESS_KEY:-}" ]] || [[ -n "${AWS_SESSION_TOKEN:-}" ]]; then
  echo "Refusing to execute source builds while AWS credentials are present." >&2
  exit 2
fi

while IFS=$'\t' read -r repository revision; do
  checkout="$workspace_root/$repository"
  if [[ ! -d "$checkout/.git" ]]; then
    echo "Missing locked checkout: $repository" >&2
    exit 2
  fi
  actual=$(git -C "$checkout" rev-parse HEAD)
  if [[ "$actual" != "$revision" ]] || [[ -n "$(git -C "$checkout" status --porcelain)" ]]; then
    echo "Refusing unlocked or dirty checkout: $repository" >&2
    exit 2
  fi
  git -C "$checkout" fetch --quiet origin main
  if ! git -C "$checkout" merge-base --is-ancestor "$revision" origin/main; then
    echo "Refusing service revision not promoted through protected main: $repository@$revision" >&2
    exit 3
  fi
done < <(jq -r '.repositories[] | [.name,.revision] | @tsv' "$lock_file")

client_revision=$(jq -r '.dependencyEvidence.frontendArtifacts.client.revision' "$template_manifest")
client_contract_sha=$(jq -r '.dependencyEvidence.frontendArtifacts.client.artifactContractSha256' "$template_manifest")
landing_revision=$(jq -r '.dependencyEvidence.frontendArtifacts.landing.revision' "$template_manifest")
landing_contract_sha=$(jq -r '.dependencyEvidence.frontendArtifacts.landing.artifactContractSha256' "$template_manifest")
for value in "$client_revision" "$landing_revision"; do
  [[ "$value" =~ ^[0-9a-f]{40}$ ]] || { echo "Frontend release dependency is not a reviewed commit SHA." >&2; exit 3; }
done

for value in "$client_contract_sha" "$landing_contract_sha"; do
  [[ "$value" =~ ^[0-9a-f]{64}$ ]] || { echo "Frontend artifact contract is not checksum-pinned." >&2; exit 3; }
done
if [[ -e "$landing_checkout" ]]; then
  echo "Refusing pre-existing landing checkout in the immutable build workspace." >&2
  exit 3
fi
gh repo clone jobseekercopilot/job-seeker-copilot-landing "$landing_checkout"
git -C "$landing_checkout" checkout --detach "$landing_revision"
git -C "$landing_checkout" fetch --quiet origin main
git -C "$landing_checkout" merge-base --is-ancestor "$landing_revision" origin/main || {
  echo "Landing release revision was not promoted through protected main." >&2
  exit 3
}
actual_client_revision=$(git -C "$workspace_root/job-seeker-copilot-client" rev-parse HEAD)
[[ "$actual_client_revision" == "$client_revision" ]] || {
  echo "Client image revision must exactly match its frontend artifact dependency evidence." >&2
  exit 3
}
echo "$client_contract_sha  $workspace_root/job-seeker-copilot-client/docs/release-artifact-contract.md" | sha256sum -c -

# The approval no longer makes an unverifiable claim about separately rendered
# Terms/Privacy response bytes.  Instead it checksum-binds the exact immutable
# Client and Landing legal artifacts that central release is about to package.
client_legal_artifact_sha=$(jq -er '.publicLegal.clientLegalArtifactSha256' "$launch_approvals_file")
landing_legal_artifact_sha=$(jq -er '.publicLegal.landingLegalArtifactSha256' "$launch_approvals_file")
for value in "$client_legal_artifact_sha" "$landing_legal_artifact_sha"; do
  [[ "$value" =~ ^[0-9a-f]{64}$ ]] && [[ "$value" != "$(printf '0%.0s' {1..64})" ]] || {
    echo "Protected legal artifact checksum is absent, zero or malformed." >&2
    exit 3
  }
done
echo "$client_legal_artifact_sha  $workspace_root/job-seeker-copilot-client/src/app/features/legal-notice/legal-notice.html" | sha256sum -c -
echo "$landing_legal_artifact_sha  $landing_checkout/src/app/pages/legal/legal-page.html" | sha256sum -c -

if [[ -z "$landing_runtime_env_b64" ]]; then
  echo "Refusing: protected LANDING_RUNTIME_ENV_B64 release input is required." >&2
  exit 3
fi

document_store_erasure_runbook=$(jq -er \
  '.dependencyEvidence.documentStorePermanentErasure.restoreReplayRunbook' "$template_manifest")
document_store_erasure_runbook_sha=$(jq -er \
  '.dependencyEvidence.documentStorePermanentErasure.restoreReplayRunbookSha256' "$template_manifest")
[[ "$document_store_erasure_runbook" == "docs/aws-public-beta/document-store-permanent-erasure.md" ]] || {
  echo "Document Store permanent-erasure restore procedure path is not the reviewed contract." >&2
  exit 3
}
echo "$document_store_erasure_runbook_sha  $repository_root/$document_store_erasure_runbook" | sha256sum -c -

declare -A dependency_revision=(
  [document-store-service]="$(jq -r '.dependencyEvidence.documentStorePermanentErasure.revision' "$template_manifest")"
  [adzuna-gateway]=594ac33862c6360fe05768905bab0e2cb9ac1898
  [jsearch-gateway]=79677c6586207f5aa30b9c6d0720f5ed2cfe728a
  [postcode-io-gateway]="$(jq -r '.dependencyEvidence.postcodesNorthernIrelandCoverageChain.postcodeIoGateway.revision' "$template_manifest")"
  [location-service]="$(jq -r '.dependencyEvidence.postcodesNorthernIrelandCoverageChain.locationService.revision' "$template_manifest")"
  [location-gateway]="$(jq -r '.dependencyEvidence.postcodesNorthernIrelandCoverageChain.locationGateway.revision' "$template_manifest")"
  [authentication-service]="$(jq -r '.dependencyEvidence.paymentV2ProductionContract.authenticationService.revision' "$template_manifest")"
  [user-management-gateway]="$(jq -r '.dependencyEvidence.paymentV2ProductionContract.userManagementGateway.revision' "$template_manifest")"
  [document-generation-gateway]="$(jq -r '.dependencyEvidence.paymentV2ProductionContract.documentGenerationGateway.revision' "$template_manifest")"
  [payment-service]="$(jq -r '.dependencyEvidence.paymentV2ProductionContract.paymentService.revision' "$template_manifest")"
  [payment-gateway]="$(jq -r '.dependencyEvidence.paymentV2ProductionContract.paymentGateway.revision' "$template_manifest")"
  [stripe-gateway]="$(jq -r '.dependencyEvidence.paymentV2ProductionContract.stripeGateway.revision' "$template_manifest")"
  [system-data-service]="$(jq -r '.dependencyEvidence.paymentFixtureAcceptance.systemDataServiceRevision' "$template_manifest")"
  [e2e]="$(jq -r '.dependencyEvidence.paymentFixtureAcceptance.e2eRevision' "$template_manifest")"
)
for repository in "${!dependency_revision[@]}"; do
  if [[ ! "${dependency_revision[$repository]}" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Release dependency for $repository is not a reviewed commit SHA." >&2
    exit 3
  fi
  if ! git -C "$workspace_root/$repository" merge-base --is-ancestor "${dependency_revision[$repository]}" HEAD; then
    echo "Release lock for $repository does not contain required dependency ${dependency_revision[$repository]}." >&2
    exit 3
  fi
done
document_store_task_role_revision=$(jq -er '.dependencyEvidence.documentStoreTaskRoleStorage' "$template_manifest")
[[ "$document_store_task_role_revision" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Document Store task-role dependency is not a reviewed commit SHA." >&2
  exit 3
}
git -C "$workspace_root/document-store-service" merge-base --is-ancestor \
  "$document_store_task_role_revision" HEAD || {
    echo "Document Store release lock lost the reviewed task-role storage dependency." >&2
    exit 3
  }

payment_fixture_infrastructure_revision=$(jq -r \
  '.dependencyEvidence.paymentFixtureAcceptance.infrastructureRevision' "$template_manifest")
[[ "$payment_fixture_infrastructure_revision" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Payment fixture Infrastructure evidence is not a reviewed commit SHA." >&2
  exit 3
}
git -C "$repository_root" merge-base --is-ancestor "$payment_fixture_infrastructure_revision" HEAD || {
  echo "Infrastructure does not contain the reviewed isolated payment fixture overlay." >&2
  exit 3
}

# The remaining source builds need neither the short-lived repository token nor
# an AWS identity. Drop inherited tokens before executing any repository code.
unset GH_TOKEN GITHUB_TOKEN

landing_input_directory=$(mktemp -d /tmp/jsc-landing-input.XXXXXX)
cleanup_landing_input() {
  find "$landing_input_directory" -type f -exec sh -c 'command -v shred >/dev/null && shred -u "$1" || rm -f "$1"' _ {} \;
  rmdir "$landing_input_directory" 2>/dev/null || true
}
trap cleanup_landing_input EXIT HUP INT TERM
printf '%s' "$landing_runtime_env_b64" | base64 --decode > "$landing_input_directory/runtime-environment.json"
chmod 0600 "$landing_input_directory/runtime-environment.json"
python3 "$repository_root/scripts/aws/build_landing_artifact.py" \
  --checkout "$landing_checkout" \
  --runtime-environment "$landing_input_directory/runtime-environment.json" \
  --output-directory "$output_directory" \
  --expected-revision "$landing_revision" \
  --expected-contract-sha256 "$landing_contract_sha"
python3 "$repository_root/scripts/aws/validate_public_beta.py" \
  --landing-only \
  --approval-manifest "$launch_approvals_file" \
  --landing-archive "$output_directory/landing-static.tar"
cleanup_landing_input
trap - EXIT HUP INT TERM

export COMPOSE_PROJECT_NAME=jsc-release
"$repository_root/scripts/test-all.sh" --profile full-fixture
# Contract tests export several checksum-bound OpenAPI documents under target/.
# Verify those exact bytes before the subsequent clean packaging pass removes
# generated test output from Maven target directories.
python3 "$repository_root/scripts/aws/verify_release_contract_hashes.py" \
  --workspace-root "$workspace_root" \
  --image-manifest "$template_manifest"
"$repository_root/scripts/build-all.sh" --profile full-fixture

# The workspace lifecycle builds source artifacts but intentionally does not
# publish OCI images. Materialise the exact Compose build contexts under an
# ephemeral fixture-only environment, then address every result by its
# jsc-release-<service> local image name below.
compose_context=$(mktemp -d /tmp/jsc-release-compose.XXXXXX)
cleanup_compose_context() {
  find "$compose_context" -type f -exec sh -c 'command -v shred >/dev/null && shred -u "$1" || rm -f "$1"' _ {} \;
  rmdir "$compose_context" 2>/dev/null || true
}
trap cleanup_compose_context EXIT HUP INT TERM
python3 "$repository_root/scripts/security/generate_profile_env.py" \
  --profile local \
  --output "$compose_context/runtime.env"
mapfile -t runtime_services < <(jq -r '.services | keys[]' "$runtime_manifest")
docker compose \
  --project-name jsc-release \
  --env-file "$compose_context/runtime.env" \
  --file "$repository_root/docker-compose.yml" \
  build "${runtime_services[@]}"
# These two reviewed runtime-health changes live in the owning Dockerfiles,
# not the older local staged-JAR Compose contexts. Rebuild from the exact
# locked sources so the published artifact actually contains that evidence.
for service in adzuna-gateway jsearch-gateway; do
  docker build --tag "jsc-release-$service" "$workspace_root/$service"
done
cleanup_compose_context
trap - EXIT HUP INT TERM

database_services=(
  authentication-service user-profile-service job-service
  document-generation-gateway document-store-service
  application-tracker-service payment-service
)

# Add the exact reviewed RDS trust bundle centrally so rotation is one
# checksum-bound release input rather than seven ad-hoc image changes.
rds_ca_context=$(mktemp -d /tmp/jsc-rds-ca.XXXXXX)
cleanup_rds_ca_context() {
  case "$rds_ca_context" in /tmp/jsc-rds-ca.*) rm -rf "$rds_ca_context" ;; esac
}
trap cleanup_rds_ca_context EXIT HUP INT TERM
curl --fail --show-error --silent --location "$rds_ca_url" \
  --output "$rds_ca_context/global-bundle.pem"
echo "$rds_ca_sha  $rds_ca_context/global-bundle.pem" | sha256sum -c -
printf '%s\n' \
  'ARG BASE_IMAGE' \
  'FROM ${BASE_IMAGE}' \
  'USER 0:0' \
  'COPY --chmod=0444 global-bundle.pem /etc/jsc/rds/global-bundle.pem' \
  'USER 10001:10001' \
  > "$rds_ca_context/Dockerfile"
for service in "${database_services[@]}"; do
  local_image="jsc-release-$service"
  base_image="$local_image:without-rds-ca"
  docker tag "$local_image" "$base_image"
  docker build \
    --build-arg "BASE_IMAGE=$base_image" \
    --label "uk.jobseekercopilot.rds-ca-sha256=$rds_ca_sha" \
    --tag "$local_image" \
    "$rds_ca_context" >/dev/null
  docker image rm "$base_image" >/dev/null
done
cleanup_rds_ca_context
trap - EXIT HUP INT TERM

is_database_service() {
  local candidate=$1
  local service
  for service in "${database_services[@]}"; do
    [[ "$candidate" == "$service" ]] && return 0
  done
  return 1
}

while IFS=$'\t' read -r service port health_path; do
  local_image="jsc-release-$service"
  docker image inspect "$local_image" >/dev/null
  if [[ "$service" == "job-seeker-copilot-client" ]]; then
    [[ "$(docker image inspect --format '{{.Config.User}}' "$local_image")" == "1000:1000" ]] || {
      echo "Client release image must declare non-root user 1000:1000." >&2
      exit 3
    }
    docker run --rm --read-only --tmpfs /tmp --user 1000:1000 --entrypoint /bin/sh \
      "$local_image" -eu -c 'command -v node >/dev/null'
  else
    docker run --rm --read-only --tmpfs /tmp --user 10001:10001 --entrypoint /bin/sh \
      "$local_image" -eu -c 'command -v wget >/dev/null'
  fi
  if is_database_service "$service"; then
    [[ "$(docker image inspect --format '{{.Config.User}}' "$local_image")" == "10001:10001" ]] || {
      echo "Database service release image must declare non-root user 10001:10001: $service" >&2
      exit 3
    }
    docker run --rm --read-only --user 10001:10001 --entrypoint /bin/sh "$local_image" -eu -c \
      "test -r /etc/jsc/rds/global-bundle.pem && echo '$rds_ca_sha  /etc/jsc/rds/global-bundle.pem' | sha256sum -c -"
  fi
  echo "Verified release image contract: $service:$port$health_path"
done < <(jq -r '.services | to_entries[] | [.key, (.value.port|tostring), .value.healthPath] | @tsv' "$runtime_manifest")

# Fixture support is intentionally present in the one reviewed Stripe JAR so
# isolated E2E can exercise signed settlement.  Prove the truthful production
# boundary on the exact image: production+FIXTURE must fail startup, while
# production+DISABLED is healthy, returns 404 for the control route, and does
# not register any of the mode-conditional control/provider beans.
stripe_image=jsc-release-stripe-gateway
stripe_probe=
cleanup_stripe_probe() {
  if [[ -n "$stripe_probe" ]]; then
    docker rm --force "$stripe_probe" >/dev/null 2>&1 || true
  fi
}
trap cleanup_stripe_probe EXIT HUP INT TERM
stripe_production_environment=(
  --env SPRING_PROFILES_ACTIVE=production
  --env SERVER_PORT=8100
  --env STRIPE_LIVE_RELEASE_AUTHORISED=false
  --env STRIPE_LEGACY_CHECKOUT_ENABLED=false
  --env STRIPE_API_BASE_URL=https://api.stripe.com
  --env STRIPE_API_VERSION=2026-02-25.clover
  --env STRIPE_PRICE_STARTER=price_releaseprobe499
  --env STRIPE_PRICE_ACTIVE=price_releaseprobe1199
  --env STRIPE_PRICE_POWER=price_releaseprobe1999
  --env STRIPE_SUCCESS_URL=https://app.jobseekercopilot.com/payment/success
  --env STRIPE_CANCEL_URL=https://app.jobseekercopilot.com/payment/cancel
  --env PAYMENT_SERVICE_URL=http://payment-service.public-beta.internal:8099
  --env PAYMENT_GATEWAY_TO_STRIPE_GATEWAY_TOKEN=release-probe-payment-gateway-token-000001
  --env STRIPE_GATEWAY_TO_PAYMENT_SERVICE_TOKEN=release-probe-stripe-payment-token-000002
  --env PAYMENT_SERVICE_TO_STRIPE_GATEWAY_LIFECYCLE_TOKEN=release-probe-payment-lifecycle-token-000003
)

stripe_probe=$(docker run --detach --read-only --tmpfs /tmp --user 10001:10001 \
  "${stripe_production_environment[@]}" \
  --env EXTERNAL_PROVIDER_MODE=FIXTURE \
  --env STRIPE_FIXTURE_PAYMENT_CONTROL_ENABLED=false \
  "$stripe_image")
for _attempt in {1..15}; do
  [[ "$(docker inspect --format '{{.State.Running}}' "$stripe_probe")" == "false" ]] && break
  sleep 2
done
stripe_fixture_logs=$(docker logs "$stripe_probe" 2>&1)
if [[ "$(docker inspect --format '{{.State.Running}}' "$stripe_probe")" != "false" ]] ||
   [[ "$(docker inspect --format '{{.State.ExitCode}}' "$stripe_probe")" -eq 0 ]] ||
   ! grep -Fq 'cannot start in FIXTURE mode with a production profile' <<<"$stripe_fixture_logs"; then
  printf '%s\n' "$stripe_fixture_logs" >&2
  echo "Stripe exact image did not reject production-profile FIXTURE startup." >&2
  exit 3
fi
unset stripe_fixture_logs
cleanup_stripe_probe
stripe_probe=

stripe_probe=$(docker run --detach --read-only --tmpfs /tmp --user 10001:10001 \
  "${stripe_production_environment[@]}" \
  --env EXTERNAL_PROVIDER_MODE=DISABLED \
  --env STRIPE_FIXTURE_PAYMENT_CONTROL_ENABLED=false \
  --env MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE=health,beans \
  "$stripe_image")
stripe_ready=false
for _attempt in {1..30}; do
  if docker exec "$stripe_probe" curl --fail --silent http://127.0.0.1:8100/actuator/health >/dev/null; then
    stripe_ready=true
    break
  fi
  [[ "$(docker inspect --format '{{.State.Running}}' "$stripe_probe")" == "true" ]] || break
  sleep 2
done
if [[ "$stripe_ready" != "true" ]]; then
  docker logs "$stripe_probe" >&2
  echo "Stripe exact image did not become healthy in production DISABLED mode." >&2
  exit 3
fi
fixture_route_status=$(docker exec "$stripe_probe" curl --silent --output /dev/null --write-out '%{http_code}' \
  http://127.0.0.1:8100/internal/fixtures/v2/stripe/owners/release-preflight)
[[ "$fixture_route_status" == "404" ]] || {
  echo "Stripe fixture payment-control route was present in production DISABLED mode: HTTP $fixture_route_status" >&2
  exit 3
}
docker exec "$stripe_probe" curl --fail --silent http://127.0.0.1:8100/actuator/beans | jq -e '
  [.. | strings |
   select(test("FixturePaymentControlController|FixturePaymentControlService|FixtureStripeProviderClient|FixtureStripeSessionStore"))]
  | length == 0
' >/dev/null || {
  echo "Stripe mode-conditional fixture control/provider bean was active in production DISABLED mode." >&2
  exit 3
}
cleanup_stripe_probe
stripe_probe=
trap - EXIT HUP INT TERM

operator_image=jsc-release-release-operator
docker build \
  --build-arg "POSTGRES_IMAGE=$postgres_image" \
  --build-arg "RDS_CA_BUNDLE_URL=$rds_ca_url" \
  --build-arg "RDS_CA_BUNDLE_SHA256=$rds_ca_sha" \
  --tag "$operator_image" \
  "$repository_root/aws/public-beta/operator"
docker run --rm --entrypoint /bin/sh "$operator_image" -eu -c \
  "psql --version >/dev/null && curl --version >/dev/null && jq --version >/dev/null && echo '$rds_ca_sha  /etc/jsc/rds/global-bundle.pem' | sha256sum -c -"

# The hosted runner has finite Docker storage, and the pinned ClamAV image must
# still have room to refresh its signature database. All application images are
# final and tagged at this point, so discard only unused BuildKit cache. Prove
# the retained release images exist both before and after the cache reclaim;
# never use a broader system/image/container prune here.
mapfile -t retained_release_images < <(jq -r '.services | keys[] | "jsc-release-" + .' "$runtime_manifest")
retained_release_images+=("$operator_image")
docker image inspect "${retained_release_images[@]}" >/dev/null
docker system df
docker builder prune --all --force >/dev/null
docker image inspect "${retained_release_images[@]}" >/dev/null
docker system df

clamav_image='clamav/clamav:1.4.5@sha256:4de20bd9ab45a4b763c5412b769217ef5082572ebc8a63aff1a77943419e5dd8'
docker pull "$clamav_image" >/dev/null
docker run --rm --entrypoint /bin/sh "$clamav_image" -eu -c '
  command -v clamdscan >/dev/null
  command -v clamdcheck.sh >/dev/null
  command -v freshclam >/dev/null
  command -v date >/dev/null
  command -v cut >/dev/null
'

# Prove the exact production lifecycle, not only the presence of binaries. The
# preloaded database avoids a full CDN download on every replacement. FreshClam
# may update it before clamd finishes starting, so the health command requests a
# supported reload on version mismatch and remains failed until the loaded and
# on-disk versions agree and are fresh. A second pass proves the healthy path is
# idempotent and does not depend on another reload.
clamav_health_command='set -eu
clamdcheck.sh
daemon="$(clamdscan --version)"
disk="$(freshclam --version)"
daemon_version="$(echo "$daemon" | cut -d/ -f2)"
disk_version="$(echo "$disk" | cut -d/ -f2)"
if [ "$daemon_version" != "$disk_version" ]; then
  clamdscan --reload >/dev/null 2>&1
  exit 42
fi
signature="${daemon#*/*/}"
signature_epoch="$(date -u -D "%a %b %e %H:%M:%S %Y" -d "$signature" +%s)"
now="$(date -u +%s)"
test "$((now - signature_epoch))" -le 172800'
clamav_probe=
cleanup_clamav_probe() {
  if [[ -n "$clamav_probe" ]]; then
    docker rm --force "$clamav_probe" >/dev/null 2>&1 || true
  fi
}
trap cleanup_clamav_probe EXIT HUP INT TERM
clamav_probe=$(docker run --detach \
  --memory 4g \
  --cpus 0.5 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,uid=100,gid=101,mode=1770 \
  --tmpfs /var/log/clamav:rw,noexec,nosuid,nodev,size=64m,uid=100,gid=101,mode=0750 \
  --tmpfs /run/clamav:rw,noexec,nosuid,nodev,size=16m,uid=100,gid=101,mode=0750 \
  --env FRESHCLAM_CHECKS=12 \
  --env FRESHCLAM_CONF_ConnectTimeout=10 \
  --env FRESHCLAM_CONF_ReceiveTimeout=30 \
  --env CLAMD_CONF_StreamMaxLength=11M \
  --env CLAMD_CONF_MaxFileSize=11M \
  --env CLAMD_CONF_MaxScanSize=32M \
  --env CLAMD_CONF_MaxScanTime=30000 \
  --env CLAMD_CONF_MaxFiles=512 \
  --env CLAMD_CONF_MaxRecursion=16 \
  --env CLAMD_CONF_SelfCheck=60 \
  "$clamav_image")
clamav_ready=false
clamav_reload_observed=false
for _attempt in {1..24}; do
  clamav_probe_status=0
  docker exec "$clamav_probe" /bin/sh -c "$clamav_health_command" || clamav_probe_status=$?
  if [[ "$clamav_probe_status" -eq 0 ]]; then
    clamav_ready=true
    break
  elif [[ "$clamav_probe_status" -eq 42 ]]; then
    clamav_reload_observed=true
  fi
  [[ "$(docker inspect --format '{{.State.Status}}' "$clamav_probe")" == "running" ]] || break
  sleep 10
done
if [[ "$clamav_ready" != "true" ]] || [[ "$clamav_reload_observed" != "true" ]]; then
  docker logs "$clamav_probe" >&2
  echo "ClamAV exact-image initial-reload/equality/freshness contract failed." >&2
  exit 3
fi
docker exec "$clamav_probe" /bin/sh -c "$clamav_health_command"
cleanup_clamav_probe
clamav_probe=
trap - EXIT HUP INT TERM
docker tag "$clamav_image" jsc-release-clamav

mkdir -p "$output_directory"
manifest="$output_directory/image-manifest.json"
created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
infrastructure_revision=$(git -C "$repository_root" rev-parse HEAD)
launch_approvals_sha=$(sha256sum "$launch_approvals_file" | awk '{print $1}')

jq \
  --arg release "$release_id" \
  --arg created "$created_at" \
  --arg launchApprovalsSha "$launch_approvals_sha" \
  '.releaseId=$release | .createdAt=$created | .sourceBranch="main"
   | .launchApprovalManifestSha256=$launchApprovalsSha
   | .capabilities.documentStoreTaskRoleCredentials=true
   | .capabilities.documentStoreS3KmsEncryption=true
   | .capabilities.documentStorePermanentErasureVerified=true
   | .capabilities.runtimeHealthcheckCommandsVerified=true
   | .capabilities.rdsCaBundleVerified=true
   | .capabilities.postcodesNorthernIrelandCoverageChainVerified=true
   | .capabilities.frontendArtifactsVerified=true
   | .capabilities.paymentV2ProductionContractVerified=true
   | .capabilities.paymentFixtureAcceptanceVerified=true
   | .capabilities.stripeFixtureProductionIsolationVerified=true' \
  "$template_manifest" > "$manifest"

landing_metadata="$output_directory/landing-artifact.json"
updated_manifest=$(mktemp)
jq \
  --slurpfile landing "$landing_metadata" \
  '.dependencyEvidence.frontendArtifacts.landing={
     revision:$landing[0].revision,
     artifactContractSha256:$landing[0].artifactContractSha256,
     staticArtifactSha256:$landing[0].staticArtifactSha256,
     runtimeConfigSha256:$landing[0].runtimeConfigSha256,
     selectedSamTemplate:$landing[0].selectedSamTemplate,
     selectedSamTemplateSha256:$landing[0].selectedSamTemplateSha256,
     deploymentStatus:$landing[0].deploymentStatus
   }' \
  "$manifest" > "$updated_manifest"
mv "$updated_manifest" "$manifest"

if [[ -n "$(git -C "$repository_root" status --porcelain)" ]]; then
  echo "Refusing a prepared release after build code modified Infrastructure." >&2
  exit 3
fi
jq -e '
  .sourceBranch == "main" and
  .releaseId != "UNRELEASED" and
  ([.images[].digest] | all(. == "sha256:0000000000000000000000000000000000000000000000000000000000000000")) and
  ([.images[].scanStatus] | all(. == "UNSCANNED"))
' "$manifest" >/dev/null
mapfile -t prepared_images < <(jq -r '.services | keys[] | "jsc-release-" + .' "$runtime_manifest")
prepared_images+=(jsc-release-clamav jsc-release-release-operator)
image_archive="$output_directory/release-images.tar.zst"
docker save "${prepared_images[@]}" | zstd --quiet -T0 -6 -o "$image_archive"
image_archive_sha=$(sha256sum "$image_archive" | awk '{print $1}')
jq -n \
  --arg releaseId "$release_id" \
  --arg infrastructureRevision "$infrastructure_revision" \
  --arg imageArchiveSha256 "$image_archive_sha" \
  --argjson imageNames "$(printf '%s\n' "${prepared_images[@]}" | jq -R . | jq -s 'sort')" \
  '{
    schemaVersion:1,
    releaseId:$releaseId,
    infrastructureRevision:$infrastructureRevision,
    imageArchiveSha256:$imageArchiveSha256,
    imageNames:$imageNames
  }' > "$output_directory/prepared-images.json"
chmod 0444 "$manifest" "$landing_metadata" "$image_archive" \
  "$output_directory/prepared-images.json" \
  "$output_directory/landing-static.tar" \
  "$output_directory/landing-waitlist-backend-template.yaml"
echo "Credential-free release build ready for protected ECR publication: $output_directory"
