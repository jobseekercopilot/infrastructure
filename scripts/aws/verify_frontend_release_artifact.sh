#!/usr/bin/env bash
set -euo pipefail

manifest=${1:-}
provenance=${2:-}
landing_archive=${3:-}
landing_metadata=${4:-}
landing_sam_template=${5:-}

if [[ $# -ne 5 ]]; then
  echo "Usage: $0 IMAGE_MANIFEST PROVENANCE LANDING_ARCHIVE LANDING_METADATA LANDING_SAM_TEMPLATE" >&2
  exit 2
fi
for command_name in awk cut jq sha256sum tar; do
  command -v "$command_name" >/dev/null || { echo "Missing required command: $command_name" >&2; exit 2; }
done
for artifact in "$manifest" "$provenance" "$landing_archive" "$landing_metadata" "$landing_sam_template"; do
  if [[ ! -f "$artifact" ]] || [[ -L "$artifact" ]]; then
    echo "Release artifact is missing, not regular, or a symbolic link: $artifact" >&2
    exit 3
  fi
done

jq -e 'type == "object"' "$manifest" "$provenance" "$landing_metadata" >/dev/null
jq -e '
  .schemaVersion == 1 and
  .repository == "jobseekercopilot/job-seeker-copilot-landing" and
  .selectedSamTemplate == "infrastructure/waitlist-backend/template.yaml" and
  .deploymentStatus == "NOT_DEPLOYED" and
  (.revision | test("^[0-9a-f]{40}$")) and
  ([.artifactContractSha256, .staticArtifactSha256, .runtimeConfigSha256, .selectedSamTemplateSha256]
    | all(test("^[0-9a-f]{64}$")))
' "$landing_metadata" >/dev/null

manifest_landing=$(jq -cS '.dependencyEvidence.frontendArtifacts.landing' "$manifest")
metadata_landing=$(jq -cS '{
  revision,
  artifactContractSha256,
  staticArtifactSha256,
  runtimeConfigSha256,
  selectedSamTemplate,
  selectedSamTemplateSha256,
  deploymentStatus
}' "$landing_metadata")
[[ "$manifest_landing" == "$metadata_landing" ]] || {
  echo "Landing metadata does not match the signed image manifest." >&2
  exit 3
}
[[ "$(jq -cS '.frontendArtifacts.landing' "$provenance")" == "$(jq -cS . "$landing_metadata")" ]] || {
  echo "Landing metadata does not match release provenance." >&2
  exit 3
}

manifest_client=$(jq -cS '{
  revision:.dependencyEvidence.frontendArtifacts.client.revision,
  artifactContractSha256:.dependencyEvidence.frontendArtifacts.client.artifactContractSha256,
  imageDigest:.images["job-seeker-copilot-client"].digest
}' "$manifest")
[[ "$(jq -cS '.frontendArtifacts.client' "$provenance")" == "$manifest_client" ]] || {
  echo "Client OCI evidence does not match release provenance." >&2
  exit 3
}
[[ "$(jq -r '.capabilities.frontendArtifactsVerified' "$manifest")" == true ]] || {
  echo "Frontend artifact capability is not attested." >&2
  exit 3
}

expected_archive_sha=$(jq -r .staticArtifactSha256 "$landing_metadata")
expected_runtime_sha=$(jq -r .runtimeConfigSha256 "$landing_metadata")
expected_sam_sha=$(jq -r .selectedSamTemplateSha256 "$landing_metadata")
[[ "$(sha256sum "$landing_archive" | cut -d' ' -f1)" == "$expected_archive_sha" ]] || {
  echo "Landing static archive checksum mismatch." >&2
  exit 3
}
[[ "$(sha256sum "$landing_sam_template" | cut -d' ' -f1)" == "$expected_sam_sha" ]] || {
  echo "Landing selected SAM template checksum mismatch." >&2
  exit 3
}

runtime_entry_count=$(tar -tf "$landing_archive" | awk '$0 == "config/app-config.json" { count += 1 } END { print count + 0 }')
[[ "$runtime_entry_count" == 1 ]] || {
  echo "Landing archive must contain exactly one config/app-config.json." >&2
  exit 3
}
actual_runtime_sha=$(tar -xOf "$landing_archive" config/app-config.json | sha256sum | cut -d' ' -f1)
[[ "$actual_runtime_sha" == "$expected_runtime_sha" ]] || {
  echo "Landing runtime configuration checksum mismatch." >&2
  exit 3
}

echo "Verified immutable Client OCI and non-deployed Landing static/SAM evidence."
