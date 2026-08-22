#!/usr/bin/env bash
set -euo pipefail
umask 077

release_id=${1:-}
output_directory=${2:-}
region=${AWS_REGION:-eu-west-2}
account_id=${AWS_ACCOUNT_ID:-}
rds_ca_url=${RDS_CA_BUNDLE_URL:-}
rds_ca_sha=${RDS_CA_BUNDLE_SHA256:-}
launch_approvals_file=${LAUNCH_APPROVALS_FILE:-}
prepared_artifact_digest=${PREPARED_ARTIFACT_DIGEST:-}

if [[ ! "$release_id" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7,40}$ ]] || [[ -z "$output_directory" ]]; then
  echo "Usage: $0 YYYYMMDDTHHMMSSZ-GITSHA /prepared/output/directory" >&2
  exit 2
fi
if [[ "${GITHUB_REF:-}" != "refs/heads/main" ]] || [[ "$region" != "eu-west-2" ]] || [[ ! "$account_id" =~ ^[0-9]{12}$ ]]; then
  echo "Refusing: protected main, eu-west-2 and a 12-digit AWS account ID are required." >&2
  exit 2
fi
if [[ -z "${AWS_ACCESS_KEY_ID:-}" ]] || [[ -z "${AWS_SECRET_ACCESS_KEY:-}" ]] || [[ -z "${AWS_SESSION_TOKEN:-}" ]]; then
  echo "Refusing: protected short-lived AWS session credentials are required for publication." >&2
  exit 2
fi
if [[ ! "$rds_ca_url" =~ ^https://truststore\.pki\.rds\.amazonaws\.com/ ]] || [[ ! "$rds_ca_sha" =~ ^[0-9a-f]{64}$ ]]; then
  echo "Refusing: authoritative RDS CA URL and reviewed SHA-256 are required." >&2
  exit 2
fi
if [[ -z "$launch_approvals_file" ]] || [[ ! -f "$launch_approvals_file" ]] || [[ -L "$launch_approvals_file" ]]; then
  echo "Refusing: protected LAUNCH_APPROVALS_FILE must name a regular reviewed manifest." >&2
  exit 2
fi
if [[ ! "$prepared_artifact_digest" =~ ^(sha256:)?[0-9a-f]{64}$ ]]; then
  echo "Refusing: GitHub's prepared-artifact SHA-256 output is required." >&2
  exit 2
fi
for command_name in aws cut docker git jq python3 sha256sum; do
  command -v "$command_name" >/dev/null || { echo "Missing required command: $command_name" >&2; exit 2; }
done

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
runtime_manifest="$repository_root/aws/public-beta/config/runtime-services.json"
lock_file="$repository_root/config/workspace-lock.json"
manifest="$output_directory/image-manifest.json"
landing_metadata="$output_directory/landing-artifact.json"
provenance="$output_directory/provenance.json"
landing_archive="$output_directory/landing-static.tar"
landing_sam="$output_directory/landing-waitlist-backend-template.yaml"
prepared_metadata="$output_directory/prepared-images.json"
prepared_archive="$output_directory/release-images.tar.zst"

if [[ ! -d "$output_directory" ]] || [[ -L "$output_directory" ]] || [[ -n "$(git -C "$repository_root" status --porcelain)" ]]; then
  echo "Refusing publication from a missing/symlinked output or dirty Infrastructure checkout." >&2
  exit 3
fi
for artifact in "$manifest" "$landing_metadata" "$landing_archive" "$landing_sam" "$prepared_metadata" "$prepared_archive"; do
  [[ -f "$artifact" ]] && [[ ! -L "$artifact" ]] || { echo "Missing prepared release artifact: $artifact" >&2; exit 3; }
done

infrastructure_revision=$(git -C "$repository_root" rev-parse HEAD)
launch_approvals_sha=$(sha256sum "$launch_approvals_file" | cut -d' ' -f1)
prepared_archive_sha=$(jq -er .imageArchiveSha256 "$prepared_metadata")
[[ "$(jq -er .releaseId "$prepared_metadata")" == "$release_id" ]] || { echo "Prepared image release ID mismatch." >&2; exit 3; }
[[ "$(jq -er .infrastructureRevision "$prepared_metadata")" == "$infrastructure_revision" ]] || {
  echo "Prepared images came from a different Infrastructure revision." >&2
  exit 3
}
[[ "$(sha256sum "$prepared_archive" | cut -d' ' -f1)" == "$prepared_archive_sha" ]] || {
  echo "Prepared image archive checksum mismatch." >&2
  exit 3
}
jq -e \
  --arg release "$release_id" \
  --arg approvals "$launch_approvals_sha" \
  '.schemaVersion == 1 and
   .releaseId == $release and
   .sourceBranch == "main" and
   .launchApprovalManifestSha256 == $approvals and
   ([.capabilities[]] | all(. == true)) and
   ([.images[].digest] | all(. == "sha256:0000000000000000000000000000000000000000000000000000000000000000")) and
   ([.images[].scanStatus] | all(. == "UNSCANNED"))' \
  "$manifest" >/dev/null
python3 "$repository_root/scripts/aws/validate_public_beta.py" \
  --landing-only \
  --approval-manifest "$launch_approvals_file" \
  --landing-archive "$landing_archive"

while IFS= read -r service; do
  docker image inspect "jsc-release-$service" >/dev/null
done < <(jq -r '.services | keys[]' "$runtime_manifest")
operator_image=jsc-release-release-operator
clamav_image=jsc-release-clamav
docker image inspect "$operator_image" "$clamav_image" >/dev/null

registry="$account_id.dkr.ecr.$region.amazonaws.com"
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry" >/dev/null

push_image() {
  local name=$1
  local local_reference=$2
  local revision=$3
  local repository="jsc-public-beta/$name"
  local target="$registry/$repository:$release_id"

  docker tag "$local_reference" "$target"
  docker push "$target" >/dev/null
  local digest
  digest=$(aws ecr describe-images \
    --region "$region" \
    --repository-name "$repository" \
    --image-ids "imageTag=$release_id" \
    --query 'imageDetails[0].imageDigest' \
    --output text)
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "Missing immutable ECR digest for $name" >&2; exit 3; }

  local updated
  updated=$(mktemp)
  jq \
    --arg name "$name" \
    --arg revision "$revision" \
    --arg digest "$digest" \
    '.images[$name].revision=$revision | .images[$name].digest=$digest' \
    "$manifest" > "$updated"
  mv "$updated" "$manifest"
  echo "Published immutable image for scanning: $name@$digest"
}

verify_scan() {
  local name=$1
  local repository="jsc-public-beta/$name"
  local digest findings critical high updated
  digest=$(jq -er --arg name "$name" '.images[$name].digest' "$manifest")
  aws ecr wait image-scan-complete \
    --region "$region" \
    --repository-name "$repository" \
    --image-id "imageDigest=$digest"
  findings=$(aws ecr describe-image-scan-findings \
    --region "$region" \
    --repository-name "$repository" \
    --image-id "imageDigest=$digest" \
    --query 'imageScanFindings.findingSeverityCounts' \
    --output json)
  critical=$(jq -r '.CRITICAL // 0' <<<"$findings")
  high=$(jq -r '.HIGH // 0' <<<"$findings")
  if (( critical > 0 || high > 0 )); then
    echo "Image scan failed for $name: CRITICAL=$critical HIGH=$high" >&2
    exit 3
  fi
  updated=$(mktemp)
  jq --arg name "$name" '.images[$name].scanStatus="PASSED"' "$manifest" > "$updated"
  mv "$updated" "$manifest"
  echo "Verified immutable image scan: $name@$digest"
}

chmod 0600 "$manifest"
while IFS= read -r service; do
  revision=$(jq -r --arg service "$service" '.repositories[] | select(.name==$service) | .revision' "$lock_file")
  [[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo "No locked revision for $service" >&2; exit 3; }
  push_image "$service" "jsc-release-$service" "$revision"
done < <(jq -r '.services | keys[]' "$runtime_manifest")
push_image clamav "$clamav_image" 1.4.5
push_image release-operator "$operator_image" "$infrastructure_revision"
while IFS= read -r image_name; do
  verify_scan "$image_name"
done < <(jq -r '.images | keys[]' "$manifest")

python3 "$repository_root/scripts/aws/validate_public_beta.py" \
  --release \
  --image-manifest "$manifest" \
  --approval-manifest "$launch_approvals_file" \
  --landing-archive "$landing_archive"

created_at=$(jq -er .createdAt "$manifest")
manifest_sha=$(sha256sum "$manifest" | cut -d' ' -f1)
lock_sha=$(sha256sum "$lock_file" | cut -d' ' -f1)
jq -n \
  --slurpfile releaseManifest "$manifest" \
  --slurpfile landing "$landing_metadata" \
  --arg releaseId "$release_id" \
  --arg createdAt "$created_at" \
  --arg infrastructureRevision "$infrastructure_revision" \
  --arg workspaceLockSha256 "$lock_sha" \
  --arg imageManifestSha256 "$manifest_sha" \
  --arg launchApprovalManifestSha256 "$launch_approvals_sha" \
  --arg preparedArtifactDigest "$prepared_artifact_digest" \
  --arg preparedImageArchiveSha256 "$prepared_archive_sha" \
  --arg rdsCaBundleUrl "$rds_ca_url" \
  --arg rdsCaBundleSha256 "$rds_ca_sha" \
  '{
    schemaVersion:1,
    releaseId:$releaseId,
    createdAt:$createdAt,
    infrastructureRevision:$infrastructureRevision,
    workspaceLockSha256:$workspaceLockSha256,
    imageManifestSha256:$imageManifestSha256,
    launchApprovalManifestSha256:$launchApprovalManifestSha256,
    preparedArtifactDigest:$preparedArtifactDigest,
    preparedImageArchiveSha256:$preparedImageArchiveSha256,
    rdsCaBundle:{url:$rdsCaBundleUrl,sha256:$rdsCaBundleSha256},
    frontendArtifacts:{
      client:{
        revision:$releaseManifest[0].dependencyEvidence.frontendArtifacts.client.revision,
        artifactContractSha256:$releaseManifest[0].dependencyEvidence.frontendArtifacts.client.artifactContractSha256,
        imageDigest:$releaseManifest[0].images["job-seeker-copilot-client"].digest
      },
      landing:$landing[0]
    }
  }' > "$provenance"

"$repository_root/scripts/aws/verify_frontend_release_artifact.sh" \
  "$manifest" "$provenance" "$landing_archive" "$landing_metadata" "$landing_sam"
chmod 0444 "$manifest" "$provenance" "$landing_metadata" "$landing_archive" "$landing_sam"
echo "Signed-manifest release evidence ready: $output_directory"
