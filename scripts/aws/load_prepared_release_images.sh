#!/usr/bin/env bash
set -euo pipefail

release_id=${1:-}
output_directory=${2:-}
if [[ ! "$release_id" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7,40}$ ]] || [[ -z "$output_directory" ]]; then
  echo "Usage: $0 YYYYMMDDTHHMMSSZ-GITSHA /prepared/output/directory" >&2
  exit 2
fi
if [[ -n "${AWS_ACCESS_KEY_ID:-}" ]] || [[ -n "${AWS_SECRET_ACCESS_KEY:-}" ]] || [[ -n "${AWS_SESSION_TOKEN:-}" ]]; then
  echo "Refusing to load prepared source artifacts while AWS credentials are present." >&2
  exit 2
fi
for command_name in cut docker git jq sha256sum zstd; do
  command -v "$command_name" >/dev/null || { echo "Missing required command: $command_name" >&2; exit 2; }
done

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
runtime_manifest="$repository_root/aws/public-beta/config/runtime-services.json"
metadata="$output_directory/prepared-images.json"
archive="$output_directory/release-images.tar.zst"
if [[ ! -f "$metadata" ]] || [[ -L "$metadata" ]] || [[ ! -f "$archive" ]] || [[ -L "$archive" ]]; then
  echo "Prepared image archive or metadata is missing/not regular." >&2
  exit 3
fi
if [[ -n "$(git -C "$repository_root" status --porcelain)" ]]; then
  echo "Infrastructure must remain clean before prepared images are loaded." >&2
  exit 3
fi

mapfile -t expected_images < <(jq -r '.services | keys[] | "jsc-release-" + .' "$runtime_manifest")
expected_images+=(jsc-release-clamav jsc-release-release-operator)
expected_images_json=$(printf '%s\n' "${expected_images[@]}" | jq -R . | jq -s 'sort')
infrastructure_revision=$(git -C "$repository_root" rev-parse HEAD)
jq -e \
  --arg release "$release_id" \
  --arg revision "$infrastructure_revision" \
  --argjson names "$expected_images_json" \
  '.schemaVersion == 1 and .releaseId == $release and
   .infrastructureRevision == $revision and .imageNames == $names and
   (.imageArchiveSha256 | test("^[0-9a-f]{64}$"))' \
  "$metadata" >/dev/null
expected_sha=$(jq -r .imageArchiveSha256 "$metadata")
[[ "$(sha256sum "$archive" | cut -d' ' -f1)" == "$expected_sha" ]] || {
  echo "Prepared image archive checksum mismatch." >&2
  exit 3
}

zstd --quiet --decompress --stdout "$archive" | docker load >/dev/null
for image in "${expected_images[@]}"; do
  docker image inspect "$image" >/dev/null || { echo "Prepared archive omitted image: $image" >&2; exit 3; }
done
echo "Loaded checksum-bound prepared images without AWS credentials."
