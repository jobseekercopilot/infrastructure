#!/bin/sh
set -eu

fail() {
  echo "restore semantic verifier $1" >&2
  exit "${2:-2}"
}

started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
region=${AWS_REGION:-}
account_id=${AWS_ACCOUNT_ID:-}
drill_id=${RESTORE_DRILL_ID:-}
release_id=${RELEASE_ID:-}
canary_id=${RESTORE_SOURCE_CANARY_ID:-}
source_evidence_sha=${RESTORE_SOURCE_EVIDENCE_SHA256:-}
source_marker_sha=${RESTORE_SOURCE_MARKER_SHA256:-}
marker_name=${RESTORE_SOURCE_CANARY_MARKER:-}
bucket=${RESTORE_DOCUMENT_BUCKET:-}
data_kms_key=${DOCUMENT_KMS_KEY_ARN:-}
source_document_store_url=${SOURCE_DOCUMENT_STORE_URL:-}
replay_document_store_url=${REPLAY_DOCUMENT_STORE_URL:-}
replay_database=${RESTORE_REPLAY_DATABASE:-}
operation_id=${RESTORE_ERASURE_OPERATION_ID:-}
restore_replay_id=${RESTORE_ERASURE_REPLAY_ID:-}
journal_bucket=${ERASURE_JOURNAL_BUCKET:-}
journal_kms_key=${ERASURE_JOURNAL_KMS_KEY_ARN:-}
journal_retention_days=${ERASURE_JOURNAL_RETENTION_DAYS:-}
clone_task_arn=${RESTORE_CLONE_TASK_ARN:-}
source_task_arn=${RESTORE_SOURCE_APP_TASK_ARN:-}
replay_task_arn=${RESTORE_REPLAY_APP_TASK_ARN:-}
clone_task_definition=${RESTORE_CLONE_TASK_DEFINITION_ARN:-}
app_task_definition=${RESTORE_APP_TASK_DEFINITION_ARN:-}
verifier_task_definition=${RESTORE_VERIFIER_TASK_DEFINITION_ARN:-}
document_store_image_digest=${DOCUMENT_STORE_IMAGE_DIGEST:-}
release_operator_image_digest=${RELEASE_OPERATOR_IMAGE_DIGEST:-}
vpc_id=${RESTORE_VPC_ID:-}
database_security_group=${RESTORE_DATABASE_SECURITY_GROUP_ID:-}
semantic_security_group=${RESTORE_SEMANTIC_SECURITY_GROUP_ID:-}
restored_database_arn=${RESTORED_DATABASE_ARN:-}
restored_database_endpoint=${PGHOST:-}

for command_name in aws base64 curl jq psql sha256sum stat tr cut; do
  command -v "$command_name" >/dev/null || fail "refused: missing $command_name"
done

[ "$region" = eu-west-2 ] || fail "refused: region must be eu-west-2"
case "$account_id" in *[!0-9]*|'') fail "refused: malformed account" ;; esac
[ "${#account_id}" -eq 12 ] || fail "refused: malformed account"
case "$drill_id" in *[!a-z0-9-]*|'') fail "refused: malformed drill" ;; esac
[ "${#drill_id}" -ge 8 ] && [ "${#drill_id}" -le 32 ] || fail "refused: malformed drill"
case "$drill_id" in -*|*-) fail "refused: malformed drill" ;; esac
case "$release_id" in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) fail "refused: malformed release" ;;
esac
for digest in "$source_evidence_sha" "$source_marker_sha"; do
  case "$digest" in *[!0-9a-f]*|'') fail "refused: malformed evidence digest" ;; esac
  [ "${#digest}" -eq 64 ] || fail "refused: malformed evidence digest"
done
case "$canary_id" in *[!a-z0-9-]*|'') fail "refused: malformed canary" ;; esac
[ "${#canary_id}" -ge 8 ] && [ "${#canary_id}" -le 32 ] || fail "refused: malformed canary"
case "$canary_id" in -*|*-) fail "refused: malformed canary" ;; esac
printf '%s\n%s\n' "$operation_id" "$restore_replay_id" | jq -eRs '
  split("\n")[:-1] | length == 2 and .[0] != .[1] and
  all(.[]; test("^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"))
' >/dev/null || fail "refused: malformed or duplicate erasure identifiers"
case "$operation_id" in 7e57c0de-*) ;; *) fail "refused: erasure operation is outside the reserved synthetic namespace" ;; esac
operation_hex=$(printf '%s' "$operation_id" | tr -d '-')
expected_replay_database="restore_replay_$(printf '%s' "$operation_hex" | cut -c1-12)"
[ "$replay_database" = "$expected_replay_database" ] || fail "refused: replay database is not operation-bound"
[ "$marker_name" = /jsc/public-beta/release/restore-source-canary ] || fail "refused: marker path is out of scope"
[ "$bucket" = "jsc-public-beta-restore-${account_id}-${drill_id}" ] || fail "refused: destination bucket is out of scope"
[ "$journal_bucket" = "jsc-public-beta-erasure-journal-${account_id}" ] || fail "refused: journal bucket is out of scope"
case "$data_kms_key" in arn:aws:kms:eu-west-2:${account_id}:key/*) ;;
  *) fail "refused: data key is out of scope" ;;
esac
case "$journal_kms_key" in arn:aws:kms:eu-west-2:${account_id}:key/*) ;;
  *) fail "refused: journal key is out of scope" ;;
esac
[ "$journal_kms_key" != "$data_kms_key" ] || fail "refused: journal and customer-data keys are not isolated"
case "$journal_retention_days" in *[!0-9]*|'') fail "refused: journal retention is malformed" ;; esac
[ "$journal_retention_days" -ge 36 ] && [ "$journal_retention_days" -le 400 ] || fail "refused: journal retention is out of bounds"
printf '%s\n%s\n' "$source_document_store_url" "$replay_document_store_url" | jq -eRs '
  split("\n")[:-1] | length == 2 and .[0] != .[1] and
  all(.[]; test("^http://10\\.42\\.(1[6-9]|[23][0-9]|4[0-7])\\.(25[0-5]|2[0-4][0-9]|1?[0-9]{1,2}):8089$"))
' >/dev/null || fail "refused: Document Store endpoints are not distinct private-task addresses"
[ -n "${ECS_CONTAINER_METADATA_URI_V4:-}" ] || fail "refused: ECS task metadata is unavailable"
[ -r "${PGSSLROOTCERT:-}" ] || fail "refused: pinned RDS CA is unreadable"
[ -n "${DOCUMENT_STORE_RETENTION_ADMIN_TOKEN:-}" ] || fail "refused: retention administrator credential is absent"
printf '%s\n%s\n%s\n' "$clone_task_arn" "$source_task_arn" "$replay_task_arn" | jq -eRs \
  --arg account "$account_id" '
    split("\n")[:-1] | length == 3 and (unique | length) == 3 and
    all(.[]; test("^arn:aws:ecs:eu-west-2:"+$account+":task/jsc-public-beta/[0-9a-f]{32}$"))
  ' >/dev/null || fail "refused: semantic task ARN binding is malformed"
printf '%s\n%s\n%s\n' "$clone_task_definition" "$app_task_definition" "$verifier_task_definition" | jq -eRs \
  --arg account "$account_id" '
    split("\n")[:-1] as $a |
    ($a | length == 3 and (unique | length) == 3) and
    ($a[0] | test("^arn:aws:ecs:eu-west-2:"+$account+":task-definition/jsc-public-beta-restore-semantic-clone:[1-9][0-9]*$"))
  ' >/dev/null || fail "refused: semantic task-definition binding is malformed"
printf '%s' "$app_task_definition" | jq -eR --arg account "$account_id" \
  'test("^arn:aws:ecs:eu-west-2:"+$account+":task-definition/jsc-public-beta-restore-semantic-document-store:[1-9][0-9]*$")' \
  >/dev/null || fail "refused: semantic app task definition is malformed"
printf '%s' "$verifier_task_definition" | jq -eR --arg account "$account_id" \
  'test("^arn:aws:ecs:eu-west-2:"+$account+":task-definition/jsc-public-beta-restore-semantic-verifier:[1-9][0-9]*$")' \
  >/dev/null || fail "refused: semantic verifier task definition is malformed"
for digest in "$document_store_image_digest" "$release_operator_image_digest"; do
  printf '%s' "$digest" | jq -eR 'test("^sha256:[0-9a-f]{64}$")' >/dev/null || fail "refused: image digest binding is malformed"
done
case "$vpc_id" in vpc-[0-9a-f]*) ;; *) fail "refused: restore VPC binding is malformed" ;; esac
case "$database_security_group" in sg-[0-9a-f]*) ;; *) fail "refused: restore database SG binding is malformed" ;; esac
case "$semantic_security_group" in sg-[0-9a-f]*) ;; *) fail "refused: semantic SG binding is malformed" ;; esac
[ "$database_security_group" != "$semantic_security_group" ] || fail "refused: restore SG boundaries are not distinct"
[ "$restored_database_arn" = "arn:aws:rds:eu-west-2:${account_id}:db:jsc-public-beta-restore-${drill_id}" ] || \
  fail "refused: restored database ARN is out of scope"
printf '%s' "$restored_database_endpoint" | jq -eR \
  --arg drill "$drill_id" 'test("^jsc-public-beta-restore-"+$drill+"\\.[a-z0-9.-]+\\.rds\\.amazonaws\\.com$")' \
  >/dev/null || fail "refused: restored RDS endpoint is out of scope"

synthetic_owner="jsc-restore-semantic-v1-${operation_id}"
approval_reference="restore-semantic-approval-v1:${drill_id}:${source_marker_sha}"
replay_evidence_reference="restore-semantic-replay-v1:${drill_id}:${source_marker_sha}"
journal_key="permanent-erasures/v1/${operation_id}.json"

temporary_files=""
cleanup() {
  for path in $temporary_files; do rm -f -- "$path"; done
}
trap cleanup EXIT HUP INT TERM
new_temporary_file() {
  temporary_file=$(mktemp /tmp/jsc-restore-semantic.XXXXXX)
  temporary_files="$temporary_files $temporary_file"
}

task_metadata=$(curl --fail --show-error --silent --connect-timeout 5 --max-time 10 "${ECS_CONTAINER_METADATA_URI_V4}/task")
task_arn=$(printf '%s' "$task_metadata" | jq -er '.TaskARN | select(test("^arn:aws:ecs:eu-west-2:[0-9]{12}:task/jsc-public-beta/[0-9a-f]{32}$"))')

marker=$(aws ssm get-parameter --region "$region" --name "$marker_name" --query 'Parameter.Value' --output text)
[ "$(printf '%s' "$marker" | sha256sum | cut -d' ' -f1)" = "$source_marker_sha" ] || \
  fail "refused: source marker bytes do not match restore-start evidence" 3
printf '%s' "$marker" | jq -eS \
  --arg release "$release_id" --arg canary "$canary_id" \
  --arg source_bucket "jsc-public-beta-documents-${account_id}" '
    keys == ["canaryId","databaseBootstrapMarkerVerified","document","flywayHistoriesVerified","logicalDatabases","preparedAt","releaseAttestationId","releaseId","schemaVersion"] and
    .schemaVersion == "jsc-public-beta-restore-source-canary.v1" and
    .releaseId == $release and .canaryId == $canary and
    (.releaseAttestationId | test("^[0-9a-f]{64}$")) and
    .databaseBootstrapMarkerVerified == true and .flywayHistoriesVerified == true and
    .logicalDatabases == ["authentication","user_profile","job_service","document_generation","document_store","application_tracker","payment"] and
    .document.bucket == $source_bucket and
    .document.key == ("restore-canary/v1/"+$canary+"/document.json") and
    [.document.versions[].generation] == [1,2] and (.document.versions | length) == 2 and
    all(.document.versions[]; (.versionId | type == "string" and length > 0 and length <= 1024) and
      (.sha256 | test("^[0-9a-f]{64}$")) and (.sizeBytes | type == "number" and . > 0 and . <= 4096))
  ' >/dev/null || fail "refused: source marker shape/candidate mismatch" 3
attestation_id=$(printf '%s' "$marker" | jq -er '.releaseAttestationId')
object_key=$(printf '%s' "$marker" | jq -er '.document.key')
source_version_one=$(printf '%s' "$marker" | jq -er '.document.versions[0].versionId')
source_version_two=$(printf '%s' "$marker" | jq -er '.document.versions[1].versionId')
sha_one=$(printf '%s' "$marker" | jq -er '.document.versions[0].sha256')
sha_two=$(printf '%s' "$marker" | jq -er '.document.versions[1].sha256')
size_one=$(printf '%s' "$marker" | jq -er '.document.versions[0].sizeBytes')
size_two=$(printf '%s' "$marker" | jq -er '.document.versions[1].sizeBytes')

export PGSSLMODE=verify-full
export PGCONNECT_TIMEOUT=10
export PGOPTIONS='-c statement_timeout=120000 -c lock_timeout=30000 -c idle_in_transaction_session_timeout=120000'

psql_value_database() {
  prefix=$1
  database=$2
  sql=$3
  shift 3
  eval "username=\${${prefix}_USERNAME:-}"
  eval "password=\${${prefix}_PASSWORD:-}"
  [ -n "$database" ] && [ -n "$username" ] && [ -n "$password" ] || fail "refused: incomplete database credential for $prefix"
  PGPASSWORD="$password" PGUSER="$username" PGDATABASE="$database" \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet --tuples-only --no-align \
      "$@" --command="$sql"
}

psql_value() {
  prefix=$1
  sql=$2
  shift 2
  eval "database=\${${prefix}_DATABASE:-}"
  psql_value_database "$prefix" "$database" "$sql" "$@"
}

verify_database_at() {
  prefix=$1
  expected_database=$2
  expected_user=$3
  identity=$(psql_value_database "$prefix" "$expected_database" \
    "SELECT current_database() || '|' || current_user || '|' || r.rolsuper || '|' || r.rolcreaterole || '|' || r.rolcreatedb || '|' || r.rolreplication || '|' || r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
  [ "$identity" = "${expected_database}|${expected_user}|f|f|f|f|f" ] || \
    fail "failed: $expected_database did not use its exact non-privileged role" 3
  [ "$(psql_value_database "$prefix" "$expected_database" "SELECT ssl::text FROM pg_stat_ssl WHERE pid=pg_backend_pid()")" = t ] || \
    fail "failed: $expected_database connection is not TLS" 3
  flyway=$(psql_value_database "$prefix" "$expected_database" \
    "SELECT CASE WHEN to_regclass('public.flyway_schema_history') IS NULL THEN 'missing' ELSE (SELECT count(*)::text || ':' || count(*) FILTER (WHERE NOT success)::text FROM flyway_schema_history) END")
  total=${flyway%%:*}
  failed=${flyway##*:}
  case "$total:$failed" in *[!0-9:]*|:|*:|:*) total=0; failed=1 ;; esac
  [ "$total" -gt 0 ] && [ "$failed" -eq 0 ] || fail "failed: Flyway history is incomplete for $expected_database" 3
  row_count=$(psql_value_database "$prefix" "$expected_database" \
    "SELECT count(*)::text FROM jsc_restore_source_canary_v1 WHERE canary_id = :'canary_id' AND release_id = :'release_id' AND release_attestation_id = :'attestation_id' AND marker_sha256 = :'marker_sha' AND document_object_key = :'object_key' AND document_version_one = :'version_one' AND document_version_two = :'version_two' AND document_sha256_one = :'sha_one' AND document_sha256_two = :'sha_two'" \
    --set=canary_id="$canary_id" --set=release_id="$release_id" --set=attestation_id="$attestation_id" \
    --set=marker_sha="$source_marker_sha" --set=object_key="$object_key" \
    --set=version_one="$source_version_one" --set=version_two="$source_version_two" \
    --set=sha_one="$sha_one" --set=sha_two="$sha_two")
  [ "$row_count" = 1 ] || fail "failed: exact canary row missing in $expected_database" 3
}

prefixes="AUTHENTICATION USER_PROFILE JOB_SERVICE DOCUMENT_GENERATION DOCUMENT_STORE APPLICATION_TRACKER PAYMENT"
databases="authentication user_profile job_service document_generation document_store application_tracker payment"
set -- $databases
for prefix in $prefixes; do
  database_name=$1
  shift
  eval "database_user=\${${prefix}_USERNAME:-}"
  [ "$database_user" = "$database_name" ] || fail "refused: logical database/user binding mismatch"
  verify_database_at "$prefix" "$database_name" "$database_name"
done
[ "${DOCUMENT_STORE_USERNAME:-}" = document_store ] || fail "refused: replay role is not document_store"
verify_database_at DOCUMENT_STORE "$replay_database" document_store

require_empty_table_at() {
  prefix=$1
  database=$2
  table_name=$3
  case "$table_name" in *[!a-z0-9_]*) fail "refused: unsafe table name" ;; esac
  [ "$(psql_value_database "$prefix" "$database" "SELECT CASE WHEN to_regclass('public.$table_name') IS NULL THEN '-1' ELSE (SELECT count(*)::text FROM $table_name) END")" = 0 ] || \
    fail "failed: empty-source invariant failed for $database.$table_name" 3
}

require_empty_table_at AUTHENTICATION authentication users
require_empty_table_at USER_PROFILE user_profile user_profile
require_empty_table_at JOB_SERVICE job_service saved_jobs
require_empty_table_at DOCUMENT_GENERATION document_generation generation_operations
for database_name in document_store "$replay_database"; do
  require_empty_table_at DOCUMENT_STORE "$database_name" generated_documents
  require_empty_table_at DOCUMENT_STORE "$database_name" document_owner_erasure_operations
  require_empty_table_at DOCUMENT_STORE "$database_name" document_owner_erasure_restore_requests
done
require_empty_table_at APPLICATION_TRACKER application_tracker application_records
for table_name in ai_token_wallets ai_token_transactions ai_token_reservations document_credit_wallets document_credit_transactions document_credit_reservations payment_orders founding_promotion_reservations payment_provider_events; do
  require_empty_table_at PAYMENT payment "$table_name"
done
[ "$(psql_value PAYMENT "SELECT count(*)::text FROM founding_promotion_campaigns WHERE id='founding-200' AND enabled=true AND customer_limit=200 AND active_reservations=0 AND completed_claims=0")" = 1 ] || \
  fail "failed: payment campaign seed invariant failed" 3
[ "$(psql_value PAYMENT "SELECT count(*)::text FROM payment_provider_event_ingest_locks WHERE id=1")" = 1 ] || \
  fail "failed: payment ingest-lock invariant failed" 3

versions=$(aws s3api list-object-versions --region "$region" --bucket "$bucket" --prefix "$object_key" --output json)
printf '%s' "$versions" | jq -e --arg key "$object_key" --arg source1 "$source_version_one" --arg source2 "$source_version_two" '
  (.IsTruncated // false) == false and
  ([.DeleteMarkers[]? | select(.Key == $key)] | length) == 0 and
  ([.Versions[]? | select(.Key == $key)] | length) == 2 and
  ([.Versions[]? | select(.Key == $key) | .VersionId] | unique | length) == 2 and
  all(.Versions[]? | select(.Key == $key); .VersionId != $source1 and .VersionId != $source2)
' >/dev/null || fail "failed: destination canary does not have exactly two new versions and zero delete markers" 3

new_temporary_file
destination_versions_file=$temporary_file
printf '%s' "$versions" | jq -r --arg key "$object_key" '.Versions[]? | select(.Key == $key) | .VersionId' > "$destination_versions_file"
generation_one_id=
generation_two_id=
while IFS= read -r destination_version; do
  [ -n "$destination_version" ] || continue
  new_temporary_file
  downloaded=$temporary_file
  response=$(aws s3api get-object --region "$region" --bucket "$bucket" --key "$object_key" \
    --version-id "$destination_version" "$downloaded" --output json)
  generation=$(printf '%s' "$response" | jq -er '.Metadata["jsc-canary-generation"] | select(. == "1" or . == "2")')
  if [ "$generation" = 1 ]; then
    [ -z "$generation_one_id" ] || fail "failed: duplicate generation one" 3
    generation_one_id=$destination_version; expected_sha=$sha_one; expected_size=$size_one
  else
    [ -z "$generation_two_id" ] || fail "failed: duplicate generation two" 3
    generation_two_id=$destination_version; expected_sha=$sha_two; expected_size=$size_two
  fi
  printf '%s' "$response" | jq -e --arg key "$data_kms_key" --arg canary "$canary_id" \
    --arg generation "$generation" --argjson size "$expected_size" '
      .ServerSideEncryption == "aws:kms" and .SSEKMSKeyId == $key and .BucketKeyEnabled == true and
      .ContentLength == $size and .ContentType == "application/json" and
      (.Metadata | keys == ["jsc-canary-generation","jsc-restore-canary"]) and
      .Metadata["jsc-restore-canary"] == $canary and .Metadata["jsc-canary-generation"] == $generation
    ' >/dev/null || fail "failed: restored generation metadata/encryption mismatch" 3
  [ "$(stat -c %s "$downloaded")" = "$expected_size" ] && \
    [ "$(sha256sum "$downloaded" | cut -d' ' -f1)" = "$expected_sha" ] || \
    fail "failed: restored generation payload mismatch" 3
done < "$destination_versions_file"
[ -n "$generation_one_id" ] && [ -n "$generation_two_id" ] || fail "failed: both restored generations were not identified" 3

http_json() {
  method=$1
  url=$2
  body=$3
  output=$4
  status=$(curl --silent --show-error --connect-timeout 10 --max-time 180 \
    --request "$method" --header "Content-Type: application/json" \
    --header "X-Service-Token: $DOCUMENT_STORE_RETENTION_ADMIN_TOKEN" \
    --header "X-Document-Owner: $synthetic_owner" \
    --data "$body" --output "$output" --write-out '%{http_code}' "$url") || \
    fail "failed: isolated Document Store request was unavailable" 3
  [ "$status" = 200 ] || [ "$status" = 202 ] || fail "failed: isolated Document Store returned HTTP $status" 3
}

new_temporary_file
source_response_file=$temporary_file
source_request=$(jq -cnS --arg approval "$approval_reference" '{documentIds:[],approvalReference:$approval}')
http_json PUT "${source_document_store_url}/internal/retention/v1/permanent-erasures/${operation_id}" \
  "$source_request" "$source_response_file"
jq -e --arg operation "$operation_id" '
  .schemaVersion == "document-permanent-erasure.v2" and .operationId == $operation and
  .status == "BACKUP_RETENTION_PENDING" and .documentCount == 0 and .objectScopeCount == 0 and
  .recoveryJournalEvidenceRecorded == true and .liveDataErased == true and
  .backupRetentionWindowElapsed == false and .backupExpiryEvidenceRecorded == false and
  .backupCopiesMayRemain == true and (.liveDataErasedAt | type == "string") and
  (.backupRetentionUntil | type == "string") and .completedAt == null and
  .restoreReplayId == null and .restoreReplayEvidenceRecorded == false and
  .restoreReplayRequestedAt == null and .restoreReplayObjectErasedAt == null and
  .backupRetentionDays == 35
' "$source_response_file" >/dev/null || fail "failed: source application-path erasure response mismatch" 3

journal_binding=$(psql_value_database DOCUMENT_STORE document_store \
  "SELECT journal_object_key || '|' || journal_object_version || '|' || journal_content_sha256 FROM document_owner_erasure_operations WHERE operation_id = :'operation' AND state='BACKUP_RETENTION_PENDING' AND owner_id IS NULL AND document_count=0 AND object_scope_count=0 AND journal_required=true AND journal_schema_version='document-permanent-erasure-recovery-journal.v1' AND journal_recorded_at IS NOT NULL AND live_data_erased_at IS NOT NULL AND backup_retention_days=35 AND restore_replay_id IS NULL" \
  --set=operation="$operation_id")
bound_journal_key=${journal_binding%%|*}
journal_remainder=${journal_binding#*|}
bound_journal_version=${journal_remainder%%|*}
bound_journal_sha=${journal_remainder#*|}
[ "$bound_journal_key" = "$journal_key" ] || fail "failed: source DB journal key mismatch" 3
case "$bound_journal_version" in ''|null|*'|'*) fail "failed: source DB journal VersionId is malformed" 3 ;; esac
[ "${#bound_journal_version}" -le 256 ] || fail "failed: source DB journal VersionId is malformed" 3
case "$bound_journal_sha" in *[!0-9a-f]*|'') fail "failed: source DB journal digest is malformed" 3 ;; esac
[ "${#bound_journal_sha}" -eq 64 ] || fail "failed: source DB journal digest is malformed" 3

journal_versions=$(aws s3api list-object-versions --region "$region" --bucket "$journal_bucket" --prefix "$journal_key" --output json)
printf '%s' "$journal_versions" | jq -e --arg key "$journal_key" --arg version "$bound_journal_version" '
  (.IsTruncated // false) == false and
  ([.DeleteMarkers[]? | select(.Key == $key)] | length) == 0 and
  ([.Versions[]? | select(.Key == $key)] | length) == 1 and
  [.Versions[]? | select(.Key == $key) | .VersionId] == [$version]
' >/dev/null || fail "failed: immutable journal history is not the exact one-version record" 3
new_temporary_file
journal_download=$temporary_file
journal_response=$(aws s3api get-object --region "$region" --bucket "$journal_bucket" --key "$journal_key" \
  --version-id "$bound_journal_version" "$journal_download" --output json)
journal_size=$(stat -c %s "$journal_download")
[ "$(sha256sum "$journal_download" | cut -d' ' -f1)" = "$bound_journal_sha" ] || fail "failed: immutable journal payload digest mismatch" 3
printf '%s' "$journal_response" | jq -e --arg key "$journal_kms_key" --arg sha "$bound_journal_sha" --argjson size "$journal_size" '
  .ServerSideEncryption == "aws:kms" and .SSEKMSKeyId == $key and .BucketKeyEnabled == true and
  .ContentType == "application/json" and .ContentLength == $size and
  .Metadata == {"content-sha256":$sha}
' >/dev/null || fail "failed: immutable journal encryption/metadata mismatch" 3
jq -e --arg operation "$operation_id" --arg owner "$synthetic_owner" '
  .schemaVersion == "document-permanent-erasure-recovery-journal.v1" and
  .operationId == $operation and .ownerId == $owner and .documentIds == [] and .objectScopes == [] and
  (.requestSha256 | test("^[0-9a-f]{64}$")) and (.approvalReferenceSha256 | test("^[0-9a-f]{64}$")) and
  (.policyVersion | type == "string" and length > 0) and
  (.backupRetentionPolicyVersion | type == "string" and length > 0) and
  .backupRetentionDays == 35 and (.createdAt | type == "string")
' "$journal_download" >/dev/null || fail "failed: immutable journal semantic payload mismatch" 3
retention=$(aws s3api get-object-retention --region "$region" --bucket "$journal_bucket" --key "$journal_key" \
  --version-id "$bound_journal_version" --output json)
printf '%s' "$retention" | jq -e --argjson days "$journal_retention_days" '
  .Retention.Mode == "GOVERNANCE" and
  ((.Retention.RetainUntilDate | sub("[+]00:00$";"Z") | fromdateiso8601) >= (now + (($days - 1) * 86400)))
' >/dev/null || fail "failed: immutable journal retention evidence is insufficient" 3

# Exercise the public idempotency contract through the same application path.
# The immutable if-none-match journal write must not create another version.
new_temporary_file
source_retry_response_file=$temporary_file
http_json PUT "${source_document_store_url}/internal/retention/v1/permanent-erasures/${operation_id}" \
  "$source_request" "$source_retry_response_file"
jq -e --arg operation "$operation_id" '
  .schemaVersion == "document-permanent-erasure.v2" and .operationId == $operation and
  .status == "BACKUP_RETENTION_PENDING" and .documentCount == 0 and .objectScopeCount == 0 and
  .recoveryJournalEvidenceRecorded == true and .liveDataErased == true and
  .restoreReplayId == null and .restoreReplayEvidenceRecorded == false
' "$source_retry_response_file" >/dev/null || fail "failed: source application retry was not idempotent" 3
[ "$(psql_value_database DOCUMENT_STORE document_store \
  "SELECT journal_object_key || '|' || journal_object_version || '|' || journal_content_sha256 FROM document_owner_erasure_operations WHERE operation_id = :'operation'" \
  --set=operation="$operation_id")" = "${journal_key}|${bound_journal_version}|${bound_journal_sha}" ] || \
  fail "failed: source retry changed the immutable journal binding" 3

new_temporary_file
replay_response_file=$temporary_file
replay_request=$(jq -cnS --arg evidence "$replay_evidence_reference" '{evidenceReference:$evidence}')
http_json PUT "${replay_document_store_url}/internal/retention/v1/permanent-erasures/${operation_id}/restore-replays/${restore_replay_id}" \
  "$replay_request" "$replay_response_file"
jq -e --arg operation "$operation_id" --arg replay "$restore_replay_id" '
  .schemaVersion == "document-permanent-erasure.v2" and .operationId == $operation and
  .status == "BACKUP_RETENTION_PENDING" and .documentCount == 0 and .objectScopeCount == 0 and
  .recoveryJournalEvidenceRecorded == true and .liveDataErased == true and
  .backupRetentionWindowElapsed == false and .backupExpiryEvidenceRecorded == false and
  .backupCopiesMayRemain == true and (.liveDataErasedAt | type == "string") and
  (.backupRetentionUntil | type == "string") and .completedAt == null and
  .restoreReplayId == $replay and .restoreReplayEvidenceRecorded == true and
  (.restoreReplayRequestedAt | type == "string") and (.restoreReplayObjectErasedAt | type == "string") and
  .backupRetentionDays == 35
' "$replay_response_file" >/dev/null || fail "failed: replay application-path response mismatch" 3

new_temporary_file
replay_retry_response_file=$temporary_file
http_json PUT "${replay_document_store_url}/internal/retention/v1/permanent-erasures/${operation_id}/restore-replays/${restore_replay_id}" \
  "$replay_request" "$replay_retry_response_file"
jq -e --arg operation "$operation_id" --arg replay "$restore_replay_id" '
  .schemaVersion == "document-permanent-erasure.v2" and .operationId == $operation and
  .status == "BACKUP_RETENTION_PENDING" and .documentCount == 0 and .objectScopeCount == 0 and
  .recoveryJournalEvidenceRecorded == true and .liveDataErased == true and
  .restoreReplayId == $replay and .restoreReplayEvidenceRecorded == true and
  (.restoreReplayObjectErasedAt | type == "string")
' "$replay_retry_response_file" >/dev/null || fail "failed: restore replay retry was not idempotent" 3

replay_binding=$(psql_value_database DOCUMENT_STORE "$replay_database" \
  "SELECT journal_object_key || '|' || journal_object_version || '|' || journal_content_sha256 || '|' || restore_replay_id::text FROM document_owner_erasure_operations WHERE operation_id = :'operation' AND state='BACKUP_RETENTION_PENDING' AND owner_id IS NULL AND document_count=0 AND object_scope_count=0 AND journal_required=true AND journal_schema_version='document-permanent-erasure-recovery-journal.v1' AND journal_recorded_at IS NOT NULL AND live_data_erased_at IS NOT NULL AND restore_replay_id = :'replay' AND restore_replay_evidence_sha256 IS NOT NULL AND restore_replay_requested_at IS NOT NULL AND restore_replay_object_erased_at IS NOT NULL AND backup_retention_days=35" \
  --set=operation="$operation_id" --set=replay="$restore_replay_id")
[ "$replay_binding" = "${journal_key}|${bound_journal_version}|${bound_journal_sha}|${restore_replay_id}" ] || \
  fail "failed: replay DB did not bind the exact external journal and replay" 3
[ "$(psql_value_database DOCUMENT_STORE "$replay_database" "SELECT count(*)::text FROM document_owner_erasure_restore_requests")" = 0 ] || \
  fail "failed: replay request remains pending" 3
journal_versions_after_retry=$(aws s3api list-object-versions --region "$region" --bucket "$journal_bucket" --prefix "$journal_key" --output json)
printf '%s' "$journal_versions_after_retry" | jq -e --arg key "$journal_key" --arg version "$bound_journal_version" '
  (.IsTruncated // false) == false and
  ([.DeleteMarkers[]? | select(.Key == $key)] | length) == 0 and
  ([.Versions[]? | select(.Key == $key)] | length) == 1 and
  [.Versions[]? | select(.Key == $key) | .VersionId] == [$version]
' >/dev/null || fail "failed: source/replay retries changed immutable journal version history" 3

readiness_json() {
  url=$1
  curl --fail --silent --show-error --connect-timeout 10 --max-time 60 \
    --header "X-Service-Token: $DOCUMENT_STORE_RETENTION_ADMIN_TOKEN" \
    "${url}/internal/retention/v1/permanent-erasures/readiness"
}
source_readiness=$(readiness_json "$source_document_store_url")
replay_readiness=$(readiness_json "$replay_document_store_url")
for readiness in "$source_readiness" "$replay_readiness"; do
  printf '%s' "$readiness" | jq -e '
    .schemaVersion == "document-permanent-erasure-readiness.v3" and
    .enabled == true and .ready == true and .status == "READY" and
    .recoveryJournalWritePending == 0 and .recoveryJournalEvidenceMissing == 0 and
    .liveErasureReconciliationPending == 0 and .restoreJournalReadPending == 0 and
    .restoreReplayPending == 0 and .backupRetentionPending == 1 and .backupRetentionOverdue == 0
  ' >/dev/null || fail "failed: isolated Document Store readiness v3 is not the exact post-replay READY state" 3
done

completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
owner_sha=$(printf '%s' "$synthetic_owner" | sha256sum | cut -d' ' -f1)
evidence=$(jq -cnS \
  --arg started "$started_at" --arg completed "$completed_at" --arg task "$task_arn" \
  --arg drill "$drill_id" --arg release "$release_id" --arg attestation "$attestation_id" \
  --arg canary "$canary_id" --arg sourceEvidence "$source_evidence_sha" --arg marker "$source_marker_sha" \
  --arg bucket "$bucket" --arg key "$object_key" --arg v1 "$generation_one_id" --arg v2 "$generation_two_id" \
  --arg operation "$operation_id" --arg replay "$restore_replay_id" --arg ownerSha "$owner_sha" \
  --arg journalBucket "$journal_bucket" --arg journalKey "$journal_key" --arg journalVersion "$bound_journal_version" \
  --arg journalSha "$bound_journal_sha" --argjson journalSize "$journal_size" --argjson journalDays "$journal_retention_days" \
  --arg cloneTask "$clone_task_arn" --arg sourceTask "$source_task_arn" --arg replayTask "$replay_task_arn" \
  --arg cloneDefinition "$clone_task_definition" --arg appDefinition "$app_task_definition" \
  --arg verifierDefinition "$verifier_task_definition" --arg documentImage "$document_store_image_digest" \
  --arg operatorImage "$release_operator_image_digest" --arg vpc "$vpc_id" \
  --arg databaseSg "$database_security_group" --arg semanticSg "$semantic_security_group" \
  --arg restoredDatabase "$restored_database_arn" --arg restoredEndpoint "$restored_database_endpoint" \
  --argjson sourceReadiness "$source_readiness" --argjson replayReadiness "$replay_readiness" '{
    schemaVersion:"jsc-public-beta-restore-semantic-observation.v1",status:"VERIFIED",environment:"public-beta",
    drillId:$drill,startedAt:$started,completedAt:$completed,verifierTaskArn:$task,
    releaseCandidate:{releaseId:$release,releaseAttestationId:$attestation},
    runtimeBinding:{cloneTaskArn:$cloneTask,sourceApplicationTaskArn:$sourceTask,replayApplicationTaskArn:$replayTask,cloneTaskDefinitionArn:$cloneDefinition,applicationTaskDefinitionArn:$appDefinition,verifierTaskDefinitionArn:$verifierDefinition,documentStoreImageDigest:$documentImage,releaseOperatorImageDigest:$operatorImage,vpcId:$vpc,restoreDatabaseSecurityGroupId:$databaseSg,semanticSecurityGroupId:$semanticSg,restoredDatabaseArn:$restoredDatabase,restoredDatabaseEndpoint:$restoredEndpoint,applicationTasksUseDedicatedJournalOnlyRole:true,verifierHasNoJournalPut:true,cloneHasNoTaskRole:true},
    restoreSource:{canaryId:$canary,sourceEvidenceSha256:$sourceEvidence,sourceMarkerSha256:$marker},
    databaseVerification:{logicalDatabases:["authentication","user_profile","job_service","document_generation","document_store","application_tracker","payment"],exactCanaryRowsVerified:true,preOperationReplayCloneVerified:true,nonPrivilegedRolesVerified:true,tlsConnectionsVerified:true,flywayHistoriesVerified:true,emptyBootstrapDomainInvariantsVerified:true,paymentLedgerSeedAndEmptyStateReconciled:true},
    documentVerification:{mappingType:"NON_CUSTOMER_RESTORE_CANARY",bucket:$bucket,key:$key,destinationVersionIds:[$v1,$v2],destinationVersionCount:2,deleteMarkerCount:0,newDestinationVersionIdsVerified:true,generationMetadataSizeAndSha256Verified:true,customerGeneratedDocumentMappingClaimed:false},
    erasureReplayVerification:{operationId:$operation,restoreReplayId:$replay,syntheticOwnerSha256:$ownerSha,documentCount:0,objectScopeCount:0,journal:{bucket:$journalBucket,key:$journalKey,versionId:$journalVersion,contentSha256:$journalSha,sizeBytes:$journalSize,objectLockMode:"GOVERNANCE",minimumRetentionDays:$journalDays,writeByCandidateApplicationVerified:true,exactVersionReadBySeparateVerifierVerified:true},externalJournalWriteVerified:true,externalJournalReadVerified:true,absentOperationReconstructed:true,exactReplayVerified:true,restoreReplayEvidenceRecorded:true,restoreReplayObjectErasedAtVerified:true,sourceReadiness:$sourceReadiness,replayReadiness:$replayReadiness},
    scopeLimitations:["SYNTHETIC_NON_CUSTOMER_EMPTY_SCOPE","JOURNAL_WRITE_READ_RETRY_AND_ABSENT_OPERATION_RECONSTRUCTION_PROVEN","CUSTOMER_OBJECT_ERASURE_NOT_CLAIMED","RESTORED_S3_CANARY_PROVES_VERSION_METADATA_SIZE_AND_PAYLOAD_INTEGRITY"]
  }')
printf 'JSC_RESTORE_SEMANTIC_EVIDENCE_B64=%s\n' "$(printf '%s' "$evidence" | base64 | tr -d '\n')"
echo "restore semantic verifier passed exact database/S3 and application-path immutable-journal replay checks"
