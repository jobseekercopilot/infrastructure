#!/bin/sh
set -eu

mode=${RESTORE_SOURCE_CANARY_MODE:-}
region=${AWS_REGION:-}
bucket=${DOCUMENT_BUCKET:-}
kms_key=${DOCUMENT_KMS_KEY_ARN:-}
release_id=${RELEASE_ID:-}
attestation_id=${RELEASE_ATTESTATION_ID:-}
canary_id=${RESTORE_SOURCE_CANARY_ID:-}
marker_name=${RESTORE_SOURCE_CANARY_MARKER:-}
bootstrap_marker=${DATABASE_BOOTSTRAP_MARKER:-}

case "$mode" in prepare|verify) ;;
  *) echo "restore-source canary refused: mode must be prepare or verify" >&2; exit 2 ;;
esac
case "$region" in eu-west-2) ;;
  *) echo "restore-source canary refused: region must be eu-west-2" >&2; exit 2 ;;
esac
case "$release_id" in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "restore-source canary refused: malformed release ID" >&2; exit 2 ;;
esac
case "$attestation_id" in
  *[!0-9a-f]*|'') echo "restore-source canary refused: malformed release attestation" >&2; exit 2 ;;
esac
[ "${#attestation_id}" -eq 64 ] || { echo "restore-source canary refused: malformed release attestation" >&2; exit 2; }
case "$canary_id" in
  *[!a-z0-9-]*|'') echo "restore-source canary refused: malformed canary ID" >&2; exit 2 ;;
esac
[ "${#canary_id}" -ge 8 ] && [ "${#canary_id}" -le 32 ] || {
  echo "restore-source canary refused: canary ID must contain 8-32 lowercase letters, digits or hyphens" >&2
  exit 2
}
case "$canary_id" in -*|*-) echo "restore-source canary refused: canary ID cannot start/end with a hyphen" >&2; exit 2 ;; esac
case "$bucket" in jsc-public-beta-documents-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) echo "restore-source canary refused: document bucket is out of scope" >&2; exit 2 ;;
esac
case "$kms_key" in arn:aws:kms:eu-west-2:[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]:key/*) ;;
  *) echo "restore-source canary refused: KMS key is out of scope" >&2; exit 2 ;;
esac
[ "$marker_name" = "/jsc/public-beta/release/restore-source-canary" ] || {
  echo "restore-source canary refused: marker path is out of scope" >&2; exit 2;
}
[ "$bootstrap_marker" = "/jsc/public-beta/release/database-bootstrap" ] || {
  echo "restore-source canary refused: bootstrap marker path is out of scope" >&2; exit 2;
}

required="PGHOST PGPORT PGSSLROOTCERT"
for name in $required; do
  eval "value=\${$name:-}"
  [ -n "$value" ] || { echo "restore-source canary refused: missing $name" >&2; exit 2; }
done
[ -r "$PGSSLROOTCERT" ] || { echo "restore-source canary refused: pinned RDS CA is unreadable" >&2; exit 2; }

for command_name in aws jq psql sha256sum stat; do
  command -v "$command_name" >/dev/null || { echo "restore-source canary refused: missing $command_name" >&2; exit 2; }
done

export PGSSLMODE=verify-full
export PGCONNECT_TIMEOUT=10
export PGOPTIONS='-c statement_timeout=120000 -c lock_timeout=30000 -c idle_in_transaction_session_timeout=120000'
object_key="restore-canary/v1/${canary_id}/document.json"
temporary_files=""
cleanup() {
  for path in $temporary_files; do rm -f -- "$path"; done
}
trap cleanup EXIT HUP INT TERM

new_temporary_file() {
  temporary_file=$(mktemp /tmp/jsc-restore-source.XXXXXX)
  temporary_files="$temporary_files $temporary_file"
}

bootstrap_value=$(aws ssm get-parameter \
  --region "$region" --name "$bootstrap_marker" \
  --query 'Parameter.Value' --output text)
[ "$bootstrap_value" = "$attestation_id" ] || {
  echo "restore-source canary refused: database bootstrap is absent or belongs to another candidate" >&2
  exit 3
}

verify_flyway() {
  prefix=$1
  eval "database=\${${prefix}_DATABASE:-}"
  eval "username=\${${prefix}_USERNAME:-}"
  eval "password=\${${prefix}_PASSWORD:-}"
  [ -n "$database" ] && [ -n "$username" ] && [ -n "$password" ] || {
    echo "restore-source canary refused: incomplete database credential for $prefix" >&2
    exit 2
  }
  table_name=$(PGPASSWORD="$password" PGUSER="$username" PGDATABASE="$database" \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet --tuples-only --no-align \
      --command="SELECT to_regclass('public.flyway_schema_history')")
  [ "$table_name" = flyway_schema_history ] || {
    echo "restore-source canary refused: Flyway history is missing for $prefix" >&2
    exit 3
  }
  result=$(PGPASSWORD="$password" PGUSER="$username" PGDATABASE="$database" \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet --tuples-only --no-align \
      --command='SELECT count(*) || '"'"':'"'"' || count(*) FILTER (WHERE NOT success) FROM flyway_schema_history')
  total=${result%%:*}
  failed=${result##*:}
  case "$total:$failed" in *[!0-9:]*|:|*:|:*) total=0; failed=1 ;; esac
  [ "$total" -gt 0 ] && [ "$failed" -eq 0 ] || {
    echo "restore-source canary refused: Flyway history is not successful for $prefix ($result)" >&2
    exit 3
  }
}

write_database_row() {
  prefix=$1
  eval "database=\${${prefix}_DATABASE:-}"
  eval "username=\${${prefix}_USERNAME:-}"
  eval "password=\${${prefix}_PASSWORD:-}"
  PGPASSWORD="$password" PGUSER="$username" PGDATABASE="$database" \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet \
      --set=canary_id="$canary_id" \
      --set=release_id="$release_id" \
      --set=attestation_id="$attestation_id" \
      --set=marker_sha="$marker_sha" \
      --set=object_key="$object_key" \
      --set=version_one="$version_one" \
      --set=version_two="$version_two" \
      --set=sha_one="$sha_one" \
      --set=sha_two="$sha_two" <<'SQL'
CREATE TABLE IF NOT EXISTS jsc_restore_source_canary_v1 (
  canary_id varchar(32) PRIMARY KEY,
  release_id text NOT NULL,
  release_attestation_id char(64) NOT NULL,
  marker_sha256 char(64) NOT NULL,
  document_object_key text NOT NULL,
  document_version_one text NOT NULL,
  document_version_two text NOT NULL,
  document_sha256_one char(64) NOT NULL,
  document_sha256_two char(64) NOT NULL,
  prepared_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
REVOKE ALL ON jsc_restore_source_canary_v1 FROM PUBLIC;
INSERT INTO jsc_restore_source_canary_v1 (
  canary_id, release_id, release_attestation_id, marker_sha256,
  document_object_key, document_version_one, document_version_two,
  document_sha256_one, document_sha256_two
) VALUES (
  :'canary_id', :'release_id', :'attestation_id', :'marker_sha',
  :'object_key', :'version_one', :'version_two', :'sha_one', :'sha_two'
)
ON CONFLICT (canary_id) DO UPDATE SET
  release_id = EXCLUDED.release_id,
  release_attestation_id = EXCLUDED.release_attestation_id,
  marker_sha256 = EXCLUDED.marker_sha256,
  document_object_key = EXCLUDED.document_object_key,
  document_version_one = EXCLUDED.document_version_one,
  document_version_two = EXCLUDED.document_version_two,
  document_sha256_one = EXCLUDED.document_sha256_one,
  document_sha256_two = EXCLUDED.document_sha256_two,
  prepared_at = CURRENT_TIMESTAMP;
SQL
}

verify_database_row() {
  prefix=$1
  eval "database=\${${prefix}_DATABASE:-}"
  eval "username=\${${prefix}_USERNAME:-}"
  eval "password=\${${prefix}_PASSWORD:-}"
  state=$(PGPASSWORD="$password" PGUSER="$username" PGDATABASE="$database" \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet --tuples-only --no-align \
      --set=canary_id="$canary_id" \
      --set=release_id="$release_id" \
      --set=attestation_id="$attestation_id" \
      --set=marker_sha="$marker_sha" \
      --set=object_key="$object_key" \
      --set=version_one="$version_one" \
      --set=version_two="$version_two" \
      --set=sha_one="$sha_one" \
      --set=sha_two="$sha_two" <<'SQL'
SELECT count(*)::text FROM jsc_restore_source_canary_v1
WHERE canary_id = :'canary_id'
  AND release_id = :'release_id'
  AND release_attestation_id = :'attestation_id'
  AND marker_sha256 = :'marker_sha'
  AND document_object_key = :'object_key'
  AND document_version_one = :'version_one'
  AND document_version_two = :'version_two'
  AND document_sha256_one = :'sha_one'
  AND document_sha256_two = :'sha_two';
SQL
  )
  [ "$state" = 1 ] || { echo "restore-source canary verification failed for $prefix" >&2; exit 3; }
}

prefixes="AUTHENTICATION USER_PROFILE JOB_SERVICE DOCUMENT_GENERATION DOCUMENT_STORE APPLICATION_TRACKER PAYMENT"
for prefix in $prefixes; do verify_flyway "$prefix"; done

if [ "$mode" = prepare ]; then
  if existing_marker_result=$(aws ssm get-parameter \
    --region "$region" --name "$marker_name" --query 'Parameter.Value' --output text 2>&1); then
    existing_marker=$existing_marker_result
  else
    case "$existing_marker_result" in
      *ParameterNotFound*) existing_marker= ;;
      *)
        echo "restore-source canary refused: could not read the existing marker: $existing_marker_result" >&2
        exit 3
        ;;
    esac
  fi
  if [ -n "$existing_marker" ]; then
    existing_canary=$(printf '%s' "$existing_marker" | jq -er '.canaryId | select(type == "string")') || {
      echo "restore-source canary refused: the existing marker is malformed" >&2
      exit 3
    }
    if [ "$existing_canary" = "$canary_id" ]; then
      printf '%s' "$existing_marker" | jq -e \
        --arg release "$release_id" --arg attestation "$attestation_id" --arg canary "$canary_id" '
          .schemaVersion == "jsc-public-beta-restore-source-canary.v1" and
          .releaseId == $release and .releaseAttestationId == $attestation and .canaryId == $canary
        ' >/dev/null || {
          echo "restore-source canary refused: this canary ID is already bound to another candidate" >&2
          exit 3
        }
      aws ssm add-tags-to-resource --region "$region" --resource-type Parameter --resource-id "$marker_name" \
        --tags Key=Application,Value="Job Seeker Copilot" Key=Environment,Value=public-beta \
          Key=ReleaseId,Value="$release_id" Key=RestoreSourceCanary,Value="$canary_id" >/dev/null
      mode=verify
      echo "restore-source canary already exists for the exact candidate; re-verifying without writing another version"
    else
      echo "restore-source canary will supersede the previously verified marker only after the new source is complete"
    fi
  fi
fi

if [ "$mode" = prepare ]; then
  [ "$(aws s3api get-bucket-versioning --region "$region" --bucket "$bucket" --query Status --output text)" = Enabled ] || {
    echo "restore-source canary refused: document bucket versioning is not enabled" >&2
    exit 3
  }
  new_temporary_file
  payload_one=$temporary_file
  new_temporary_file
  payload_two=$temporary_file
  jq -cnS --arg canary "$canary_id" --arg release "$release_id" \
    '{schemaVersion:"jsc-public-beta-restore-source-document.v1",canaryId:$canary,releaseId:$release,generation:1}' > "$payload_one"
  jq -cnS --arg canary "$canary_id" --arg release "$release_id" \
    '{schemaVersion:"jsc-public-beta-restore-source-document.v1",canaryId:$canary,releaseId:$release,generation:2}' > "$payload_two"
  sha_one=$(sha256sum "$payload_one" | cut -d' ' -f1)
  sha_two=$(sha256sum "$payload_two" | cut -d' ' -f1)
  size_one=$(stat -c %s "$payload_one")
  size_two=$(stat -c %s "$payload_two")

  inspect_document_version() {
    inspected_version_id=$1
    new_temporary_file
    inspected_download=$temporary_file
    inspected_response=$(aws s3api get-object \
      --region "$region" --bucket "$bucket" --key "$object_key" --version-id "$inspected_version_id" \
      "$inspected_download" --output json)
    printf '%s' "$inspected_response" | jq -e \
      --arg key "$kms_key" --arg canary "$canary_id" '
        .ServerSideEncryption == "aws:kms" and .SSEKMSKeyId == $key and
        .ContentType == "application/json" and
        (.Metadata | keys == ["jsc-canary-generation","jsc-restore-canary"]) and
        .Metadata["jsc-restore-canary"] == $canary and
        (.Metadata["jsc-canary-generation"] == "1" or .Metadata["jsc-canary-generation"] == "2")
      ' >/dev/null || {
        echo "restore-source canary refused: an existing version has unexpected encryption or metadata" >&2
        exit 3
      }
    inspected_generation=$(printf '%s' "$inspected_response" | jq -er '.Metadata["jsc-canary-generation"]')
    inspected_sha=$(sha256sum "$inspected_download" | cut -d' ' -f1)
    inspected_size=$(stat -c %s "$inspected_download")
    case "$inspected_generation:$inspected_sha:$inspected_size" in
      "1:$sha_one:$size_one"|"2:$sha_two:$size_two") ;;
      *)
        echo "restore-source canary refused: an existing version payload does not match its deterministic generation" >&2
        exit 3
        ;;
    esac
  }

  existing_versions=$(aws s3api list-object-versions \
    --region "$region" --bucket "$bucket" --prefix "$object_key" --output json)
  printf '%s' "$existing_versions" | jq -e --arg key "$object_key" '
    (.IsTruncated // false) == false and
    ([.DeleteMarkers[]? | select(.Key == $key)] | length) == 0 and
    ([.Versions[]? | select(.Key == $key)] | length) <= 2
  ' >/dev/null || {
    echo "restore-source canary refused: the exact canary key has an ambiguous or paginated version history" >&2
    exit 3
  }
  new_temporary_file
  version_list=$temporary_file
  printf '%s' "$existing_versions" | jq -r --arg key "$object_key" \
    '.Versions[]? | select(.Key == $key) | .VersionId' > "$version_list"
  version_one=
  version_two=
  while IFS= read -r existing_version_id; do
    [ -n "$existing_version_id" ] || continue
    inspect_document_version "$existing_version_id"
    case "$inspected_generation" in
      1)
        [ -z "$version_one" ] || { echo "restore-source canary refused: duplicate generation-one versions exist" >&2; exit 3; }
        version_one=$existing_version_id
        ;;
      2)
        [ -z "$version_two" ] || { echo "restore-source canary refused: duplicate generation-two versions exist" >&2; exit 3; }
        version_two=$existing_version_id
        ;;
    esac
  done < "$version_list"

  if [ -z "$version_one" ]; then
    [ -z "$version_two" ] || {
      echo "restore-source canary refused: generation two exists without generation one" >&2
      exit 3
    }
    put_one=$(aws s3api put-object --region "$region" --bucket "$bucket" --key "$object_key" \
      --body "$payload_one" --content-type application/json --server-side-encryption aws:kms --ssekms-key-id "$kms_key" \
      --metadata "jsc-restore-canary=$canary_id,jsc-canary-generation=1" --output json)
    version_one=$(printf '%s' "$put_one" | jq -er --arg key "$kms_key" \
      'select(.ServerSideEncryption == "aws:kms" and .SSEKMSKeyId == $key) | .VersionId | select(type == "string" and length > 0)')
  fi
  if [ -z "$version_two" ]; then
    put_two=$(aws s3api put-object --region "$region" --bucket "$bucket" --key "$object_key" \
      --body "$payload_two" --content-type application/json --server-side-encryption aws:kms --ssekms-key-id "$kms_key" \
      --metadata "jsc-restore-canary=$canary_id,jsc-canary-generation=2" --output json)
    version_two=$(printf '%s' "$put_two" | jq -er --arg key "$kms_key" \
      'select(.ServerSideEncryption == "aws:kms" and .SSEKMSKeyId == $key) | .VersionId | select(type == "string" and length > 0)')
  fi
  [ "$version_one" != "$version_two" ] || { echo "restore-source canary failed: S3 did not create distinct versions" >&2; exit 3; }
  prepared_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  marker=$(jq -cnS \
    --arg release "$release_id" --arg attestation "$attestation_id" --arg canary "$canary_id" \
    --arg prepared "$prepared_at" --arg bucket "$bucket" --arg key "$object_key" \
    --arg v1 "$version_one" --arg v2 "$version_two" --arg h1 "$sha_one" --arg h2 "$sha_two" \
    --argjson s1 "$size_one" --argjson s2 "$size_two" '{
      schemaVersion:"jsc-public-beta-restore-source-canary.v1",
      releaseId:$release,releaseAttestationId:$attestation,canaryId:$canary,preparedAt:$prepared,
      databaseBootstrapMarkerVerified:true,flywayHistoriesVerified:true,
      logicalDatabases:["authentication","user_profile","job_service","document_generation","document_store","application_tracker","payment"],
      document:{bucket:$bucket,key:$key,versions:[
        {generation:1,versionId:$v1,sha256:$h1,sizeBytes:$s1},
        {generation:2,versionId:$v2,sha256:$h2,sizeBytes:$s2}
      ]}
    }')
  marker_sha=$(printf '%s' "$marker" | sha256sum | cut -d' ' -f1)
  for prefix in $prefixes; do write_database_row "$prefix"; done
  aws ssm put-parameter --region "$region" --name "$marker_name" \
    --description "Verified non-customer restore-source canary for an exact immutable candidate" \
    --type String --value "$marker" --overwrite >/dev/null
  aws ssm add-tags-to-resource --region "$region" --resource-type Parameter --resource-id "$marker_name" \
    --tags Key=Application,Value="Job Seeker Copilot" Key=Environment,Value=public-beta \
      Key=ReleaseId,Value="$release_id" Key=RestoreSourceCanary,Value="$canary_id" >/dev/null
fi

marker=$(aws ssm get-parameter --region "$region" --name "$marker_name" --query 'Parameter.Value' --output text)
printf '%s' "$marker" | jq -eS \
  --arg release "$release_id" --arg attestation "$attestation_id" --arg canary "$canary_id" \
  --arg bucket "$bucket" --arg key "$object_key" '
  keys == ["canaryId","databaseBootstrapMarkerVerified","document","flywayHistoriesVerified","logicalDatabases","preparedAt","releaseAttestationId","releaseId","schemaVersion"] and
  .schemaVersion == "jsc-public-beta-restore-source-canary.v1" and
  .releaseId == $release and .releaseAttestationId == $attestation and .canaryId == $canary and
  .databaseBootstrapMarkerVerified == true and .flywayHistoriesVerified == true and
  .logicalDatabases == ["authentication","user_profile","job_service","document_generation","document_store","application_tracker","payment"] and
  (.preparedAt | test("^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
  (.document | keys == ["bucket","key","versions"]) and
  .document.bucket == $bucket and .document.key == $key and
  (.document.versions | length) == 2 and
  [.document.versions[].generation] == [1,2] and
  (.document.versions[0].versionId != .document.versions[1].versionId) and
  all(.document.versions[];
    keys == ["generation","sha256","sizeBytes","versionId"] and
    (.versionId | type == "string" and length > 0 and length <= 1024) and
    (.sha256 | test("^[0-9a-f]{64}$")) and
    (.sizeBytes | type == "number" and . > 0 and . <= 4096)
  )' >/dev/null || { echo "restore-source canary marker is malformed or belongs to another candidate" >&2; exit 3; }
aws ssm list-tags-for-resource --region "$region" --resource-type Parameter --resource-id "$marker_name" --output json | jq -e \
  --arg release "$release_id" --arg canary "$canary_id" '
    (.TagList | from_entries) as $tags |
    $tags.Application == "Job Seeker Copilot" and $tags.Environment == "public-beta" and
    $tags.ReleaseId == $release and $tags.RestoreSourceCanary == $canary
  ' >/dev/null || { echo "restore-source canary marker tags are missing or stale" >&2; exit 3; }

version_one=$(printf '%s' "$marker" | jq -er '.document.versions[0].versionId')
version_two=$(printf '%s' "$marker" | jq -er '.document.versions[1].versionId')
sha_one=$(printf '%s' "$marker" | jq -er '.document.versions[0].sha256')
sha_two=$(printf '%s' "$marker" | jq -er '.document.versions[1].sha256')
marker_sha=$(printf '%s' "$marker" | sha256sum | cut -d' ' -f1)
versions=$(aws s3api list-object-versions --region "$region" --bucket "$bucket" --prefix "$object_key" --output json)
printf '%s' "$versions" | jq -e --arg key "$object_key" --arg v1 "$version_one" --arg v2 "$version_two" '
  (.IsTruncated // false) == false and
  ([.DeleteMarkers[]? | select(.Key == $key)] | length) == 0 and
  ([.Versions[]? | select(.Key == $key)] | length) == 2 and
  ([.Versions[]? | select(.Key == $key and (.VersionId == $v1 or .VersionId == $v2)) | .VersionId] | unique | length) == 2
' >/dev/null || { echo "restore-source canary exact two-version history is absent from the live bucket" >&2; exit 3; }

generation=1
for version_id in "$version_one" "$version_two"; do
  expected_sha=$(printf '%s' "$marker" | jq -er --argjson generation "$generation" '.document.versions[] | select(.generation == $generation) | .sha256')
  expected_size=$(printf '%s' "$marker" | jq -er --argjson generation "$generation" '.document.versions[] | select(.generation == $generation) | .sizeBytes')
  new_temporary_file
  downloaded=$temporary_file
  aws s3api get-object --region "$region" --bucket "$bucket" --key "$object_key" --version-id "$version_id" "$downloaded" \
    --query '{encryption:ServerSideEncryption,kms:SSEKMSKeyId,contentLength:ContentLength,contentType:ContentType,metadata:Metadata}' --output json | \
    jq -e --arg key "$kms_key" --arg canary "$canary_id" --arg generation "$generation" --argjson size "$expected_size" '
      .encryption == "aws:kms" and .kms == $key and .contentLength == $size and
      .contentType == "application/json" and
      (.metadata | keys == ["jsc-canary-generation","jsc-restore-canary"]) and
      .metadata["jsc-restore-canary"] == $canary and .metadata["jsc-canary-generation"] == $generation
    ' >/dev/null
  [ "$(sha256sum "$downloaded" | cut -d' ' -f1)" = "$expected_sha" ] || {
    echo "restore-source canary object checksum mismatch for generation $generation" >&2
    exit 3
  }
  generation=$((generation + 1))
done

for prefix in $prefixes; do
  verify_flyway "$prefix"
  verify_database_row "$prefix"
done

echo "restore-source canary verified: $canary_id (7 databases, 1 object key, 2 distinct versions)"
