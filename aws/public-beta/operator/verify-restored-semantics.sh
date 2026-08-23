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
marker_b64=${RESTORE_SOURCE_MARKER_B64:-}
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
attempt=${RESTORE_ATTEMPT:-}

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
case "$attempt" in 1|2|3) ;; *) fail "refused: attempt must be 1, 2 or 3" ;; esac
replay_database_seed=$(printf '%s:%s:%s' "$drill_id" "$release_id" "$source_marker_sha" | sha256sum | cut -d' ' -f1)
expected_replay_database="restore_replay_$(printf '%s' "$replay_database_seed" | cut -c1-12)"
[ "$replay_database" = "$expected_replay_database" ] || fail "refused: replay database is not operation-bound"
[ "$marker_name" = /jsc/public-beta/release/restore-source-canary ] || fail "refused: marker path is out of scope"
[ "$bucket" = "jsc-public-beta-restore-${account_id}-${drill_id}" ] || fail "refused: destination bucket is out of scope"
[ "$journal_bucket" = "jsc-public-beta-erasure-journal-${account_id}" ] || fail "refused: journal bucket is out of scope"
printf '%s\n%s\n' "$data_kms_key" "$journal_kms_key" | jq -eRs --arg account "$account_id" '
  split("\n")[:-1] | length == 2 and (unique | length) == 2 and
  all(.[]; test("^arn:aws:kms:eu-west-2:"+$account+":key/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"))
' >/dev/null || fail "refused: data/journal key binding is malformed, shared or out of scope"
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
printf '%s' "$vpc_id" | jq -eR 'test("^vpc-[0-9a-f]{8,17}$")' >/dev/null || \
  fail "refused: restore VPC binding is malformed"
printf '%s\n%s\n' "$database_security_group" "$semantic_security_group" | jq -eRs '
  split("\n")[:-1] | length == 2 and (unique | length) == 2 and
  all(.[]; test("^sg-[0-9a-f]{8,17}$"))
' >/dev/null || fail "refused: restore SG binding is malformed or not distinct"
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
on_signal() {
  trap - EXIT HUP INT TERM
  cleanup
  exit 130
}
trap cleanup EXIT
trap on_signal HUP INT TERM
new_temporary_file() {
  temporary_file=$(mktemp /tmp/jsc-restore-semantic.XXXXXX)
  temporary_files="$temporary_files $temporary_file"
}

task_metadata=$(curl --fail --show-error --silent --connect-timeout 5 --max-time 10 "${ECS_CONTAINER_METADATA_URI_V4}/task")
task_arn=$(printf '%s' "$task_metadata" | jq -er --arg account "$account_id" \
  '.TaskARN | select(test("^arn:aws:ecs:eu-west-2:"+$account+":task/jsc-public-beta/[0-9a-f]{32}$"))')

case "$marker_b64" in *[!A-Za-z0-9+/=]*|'') fail "refused: source marker transport is malformed" ;; esac
[ "${#marker_b64}" -le 6144 ] || fail "refused: source marker transport is unbounded"
marker=$(printf '%s' "$marker_b64" | base64 -d) || fail "refused: source marker transport is invalid"
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
    (.preparedAt | test("^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
    (.document | keys == ["bucket","key","versions"]) and
    .document.bucket == $source_bucket and
    .document.key == ("restore-canary/v1/"+$canary+"/document.json") and
    [.document.versions[].generation] == [1,2] and (.document.versions | length) == 2 and
    (.document.versions[0].versionId != .document.versions[1].versionId) and
    all(.document.versions[]; keys == ["generation","sha256","sizeBytes","versionId"] and
      (.versionId | type == "string" and length > 0 and length <= 1024) and
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

schema_state_sql=$(cat <<'SQL'
SELECT jsonb_build_object(
  'columns', (SELECT COALESCE(jsonb_agg(jsonb_build_array(
      table_name, ordinal_position, column_name, data_type, udt_name,
      is_nullable, column_default, character_maximum_length,
      numeric_precision, numeric_scale) ORDER BY table_name, ordinal_position), '[]'::jsonb)
    FROM information_schema.columns WHERE table_schema='public'),
  'constraints', (SELECT COALESCE(jsonb_agg(jsonb_build_array(
      c.relname, x.conname, x.contype, pg_get_constraintdef(x.oid, true))
      ORDER BY c.relname, x.conname), '[]'::jsonb)
    FROM pg_constraint x JOIN pg_class c ON c.oid=x.conrelid
    JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'),
  'indexes', (SELECT COALESCE(jsonb_agg(jsonb_build_array(tablename,indexname,indexdef)
      ORDER BY tablename,indexname), '[]'::jsonb)
    FROM pg_indexes WHERE schemaname='public'),
  'policies', (SELECT COALESCE(jsonb_agg(jsonb_build_array(
      tablename,policyname,permissive,roles,cmd,qual,with_check)
      ORDER BY tablename,policyname), '[]'::jsonb)
    FROM pg_policies WHERE schemaname='public'),
  'sequences', (SELECT COALESCE(jsonb_agg(jsonb_build_array(
      sequence_name,data_type,start_value,minimum_value,maximum_value,increment,cycle_option)
      ORDER BY sequence_name), '[]'::jsonb)
    FROM information_schema.sequences WHERE sequence_schema='public'),
  'flyway', (SELECT COALESCE(jsonb_agg(jsonb_build_array(
      installed_rank,version,description,type,script,checksum,installed_by,success)
      ORDER BY installed_rank), '[]'::jsonb) FROM flyway_schema_history)
)::text;
SQL
)

schema_fingerprint_at() {
  prefix=$1
  database=$2
  psql_value_database "$prefix" "$database" "$schema_state_sql" | sha256sum | cut -d' ' -f1
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

pre_application_schema_fingerprint=$(psql_value_database DOCUMENT_STORE "$replay_database" \
  "SELECT split_part(COALESCE(shobj_description(oid,'pg_database'),''), ':', 4) FROM pg_database WHERE datname = current_database()")
clone_binding=$(psql_value_database DOCUMENT_STORE "$replay_database" \
  "SELECT COALESCE(shobj_description(oid,'pg_database'),'') FROM pg_database WHERE datname = current_database()")
[ "$clone_binding" = "jsc-restore-replay-v2:${drill_id}:${source_marker_sha}:${pre_application_schema_fingerprint}" ] || \
  fail "failed: replay database does not carry its exact pre-application fingerprint binding" 3
case "$pre_application_schema_fingerprint" in *[!0-9a-f]*|'')
  fail "failed: pre-application schema fingerprint is malformed" 3 ;;
esac
[ "${#pre_application_schema_fingerprint}" -eq 64 ] || fail "failed: pre-application schema fingerprint is malformed" 3
source_schema_fingerprint=$(schema_fingerprint_at DOCUMENT_STORE document_store)
replay_schema_fingerprint=$(schema_fingerprint_at DOCUMENT_STORE "$replay_database")
[ "$source_schema_fingerprint" = "$pre_application_schema_fingerprint" ] && \
  [ "$replay_schema_fingerprint" = "$pre_application_schema_fingerprint" ] || \
  fail "failed: candidate startup changed or repaired restored schema/Flyway state" 3

require_empty_table_at() {
  prefix=$1
  database=$2
  table_name=$3
  case "$table_name" in *[!a-z0-9_]*) fail "refused: unsafe table name" ;; esac
  [ "$(psql_value_database "$prefix" "$database" "SELECT CASE WHEN to_regclass('public.$table_name') IS NULL THEN '-1' ELSE (SELECT count(*)::text FROM $table_name) END")" = 0 ] || \
    fail "failed: empty-source invariant failed for $database.$table_name" 3
}

for table_name in users account_deletion_operation authentication_session password_reset_token refresh_token registration_legal_acceptance; do
  require_empty_table_at AUTHENTICATION authentication "$table_name"
done
for table_name in user_profile evidence_entry evidence_fact evidence_revision evidence_revision_skill evidence_snapshot evidence_snapshot_fact evidence_snapshot_section evidence_snapshot_selection evidence_supporting_link profile_professional_contact profile_professional_link qualification role user_profile_commute_travel_modes user_profile_employment_types user_profile_skills user_profile_target_roles user_profile_working_patterns user_profile_workplace_arrangements; do
  require_empty_table_at USER_PROFILE user_profile "$table_name"
done
for table_name in saved_jobs saved_job_snapshots; do
  require_empty_table_at JOB_SERVICE job_service "$table_name"
done
require_empty_table_at DOCUMENT_GENERATION document_generation generation_operations
for database_name in document_store "$replay_database"; do
  for table_name in application_document_uploads document_activity_events document_application_workflow_commands document_current_commands document_lifecycle_events document_storage_operations document_storage_reconciliation_cursors document_tombstone_associations exported_document_files generated_documents; do
    require_empty_table_at DOCUMENT_STORE "$database_name" "$table_name"
  done
done
for table_name in application_applied_commands application_document_reconciliations application_document_selection_commands application_document_workflows application_events application_records document_availability_projections; do
  require_empty_table_at APPLICATION_TRACKER application_tracker "$table_name"
done
for table_name in ai_token_wallets ai_token_transactions ai_token_reservations document_credit_wallets document_credit_transactions document_credit_reservations payment_orders founding_promotion_reservations payment_provider_events; do
  require_empty_table_at PAYMENT payment "$table_name"
done
[ "$(psql_value PAYMENT "SELECT count(*)::text FROM founding_promotion_campaigns WHERE id='founding-200' AND enabled=true AND customer_limit=200 AND active_reservations=0 AND completed_claims=0")" = 1 ] || \
  fail "failed: payment campaign seed invariant failed" 3
[ "$(psql_value PAYMENT "SELECT count(*)::text FROM payment_provider_event_ingest_locks WHERE id=1")" = 1 ] || \
  fail "failed: payment ingest-lock invariant failed" 3

# Redrive never recreates a clone after the immutable operation identity has
# been used. An attempt may therefore start in one of three exact states:
# untouched source+clone, source journal already written with untouched clone,
# or the same source and replay operations already complete. Anything else is
# drift. Both APIs are called twice below in every case, so an already-complete
# state must still prove canonical idempotency and one immutable journal version.
preexisting_journal_contract_sql=$(cat <<'SQL'
SELECT jsonb_build_object(
  'ownerFingerprint',owner_fingerprint,
  'fingerprintKeyVerifier',fingerprint_key_verifier,
  'requestSha256',request_sha256,
  'approvalReferenceSha256',approval_reference_sha256,
  'operatorId',operator_id,
  'documentCount',document_count,
  'objectScopeCount',object_scope_count,
  'policyVersion',policy_version,
  'backupRetentionPolicyVersion',backup_retention_policy_version,
  'backupRetentionDays',backup_retention_days,
  'createdAt',created_at,
  'journalSchemaVersion',journal_schema_version,
  'journalObjectKey',journal_object_key,
  'journalObjectVersion',journal_object_version,
  'journalContentSha256',journal_content_sha256
)::text
FROM document_owner_erasure_operations
WHERE operation_id = :'operation';
SQL
)

source_operation_count_before=$(psql_value_database DOCUMENT_STORE document_store \
  "SELECT count(*)::text FROM document_owner_erasure_operations")
replay_operation_count_before=$(psql_value_database DOCUMENT_STORE "$replay_database" \
  "SELECT count(*)::text FROM document_owner_erasure_operations")
for database_name in document_store "$replay_database"; do
  [ "$(psql_value_database DOCUMENT_STORE "$database_name" \
    "SELECT count(*)::text FROM document_owner_erasure_scopes")" = 0 ] && \
    [ "$(psql_value_database DOCUMENT_STORE "$database_name" \
    "SELECT count(*)::text FROM document_owner_erasure_restore_requests")" = 0 ] || \
    fail "failed: pre-attempt erasure scope/request state is not empty in $database_name" 3
done
case "${source_operation_count_before}:${replay_operation_count_before}" in
  0:0)
    source_operation_preexisting=false
    replay_operation_preexisting=false
    ;;
  1:0|1:1)
    [ "$attempt" -ge 2 ] || fail "failed: first attempt found a pre-existing erasure operation" 3
    source_operation_preexisting=true
    if [ "$replay_operation_count_before" = 1 ]; then replay_operation_preexisting=true
    else replay_operation_preexisting=false
    fi
    [ "$(psql_value_database DOCUMENT_STORE document_store \
      "SELECT count(*)::text FROM document_owner_erasure_operations WHERE operation_id=:'operation' AND state='BACKUP_RETENTION_PENDING' AND owner_id IS NULL AND document_count=0 AND object_scope_count=0 AND journal_required=true AND journal_schema_version='document-permanent-erasure-recovery-journal.v1' AND journal_object_key=:'journal_key' AND journal_object_version IS NOT NULL AND length(journal_object_version)>0 AND journal_content_sha256 ~ '^[0-9a-f]{64}$' AND journal_recorded_at IS NOT NULL AND live_data_erased_at IS NOT NULL AND backup_retention_days=35 AND restore_replay_id IS NULL AND restore_replay_evidence_sha256 IS NULL AND restore_replay_requested_at IS NULL AND restore_replay_object_erased_at IS NULL" \
      --set=operation="$operation_id" --set=journal_key="$journal_key")" = 1 ] || \
      fail "failed: pre-existing source operation is not the exact immutable-journal retry state" 3
    if [ "$replay_operation_count_before" = 1 ]; then
      [ "$(psql_value_database DOCUMENT_STORE "$replay_database" \
        "SELECT count(*)::text FROM document_owner_erasure_operations WHERE operation_id=:'operation' AND state='BACKUP_RETENTION_PENDING' AND owner_id IS NULL AND document_count=0 AND object_scope_count=0 AND journal_required=true AND journal_schema_version='document-permanent-erasure-recovery-journal.v1' AND journal_object_key=:'journal_key' AND journal_object_version IS NOT NULL AND length(journal_object_version)>0 AND journal_content_sha256 ~ '^[0-9a-f]{64}$' AND journal_recorded_at IS NOT NULL AND live_data_erased_at IS NOT NULL AND backup_retention_days=35 AND restore_replay_id=:'replay' AND restore_replay_evidence_sha256 ~ '^[0-9a-f]{64}$' AND restore_replay_requested_at IS NOT NULL AND restore_replay_object_erased_at IS NOT NULL" \
        --set=operation="$operation_id" --set=journal_key="$journal_key" --set=replay="$restore_replay_id")" = 1 ] || \
        fail "failed: pre-existing replay operation is not the exact reconstructed retry state" 3
      preexisting_source_contract=$(psql_value_database DOCUMENT_STORE document_store \
        "$preexisting_journal_contract_sql" --set=operation="$operation_id")
      preexisting_replay_contract=$(psql_value_database DOCUMENT_STORE "$replay_database" \
        "$preexisting_journal_contract_sql" --set=operation="$operation_id")
      [ -n "$preexisting_source_contract" ] && \
        [ "$preexisting_replay_contract" = "$preexisting_source_contract" ] || \
        fail "failed: pre-existing replay journal contract differs from the source operation" 3
    fi
    ;;
  *)
    fail "failed: pre-attempt erasure operations are extra, mismatched or replay-only" 3
    ;;
esac

preexisting_source_row_snapshot=
preexisting_replay_row_snapshot=
preexisting_source_journal_binding=
preexisting_journal_history_canonical=
if [ "$source_operation_preexisting" = true ]; then
  preexisting_source_row_snapshot=$(psql_value_database DOCUMENT_STORE document_store \
    "SELECT to_jsonb(o)::text FROM document_owner_erasure_operations o WHERE operation_id=:'operation'" \
    --set=operation="$operation_id")
  preexisting_source_journal_binding=$(psql_value_database DOCUMENT_STORE document_store \
    "SELECT journal_object_key || '|' || journal_object_version || '|' || journal_content_sha256 FROM document_owner_erasure_operations WHERE operation_id=:'operation'" \
    --set=operation="$operation_id")
  preexisting_binding_key=${preexisting_source_journal_binding%%|*}
  preexisting_binding_remainder=${preexisting_source_journal_binding#*|}
  preexisting_binding_version=${preexisting_binding_remainder%%|*}
  preexisting_binding_sha=${preexisting_binding_remainder#*|}
  [ "$preexisting_binding_key" = "$journal_key" ] || \
    fail "failed: pre-existing source journal key is not exact" 3
  case "$preexisting_binding_version" in ''|null|*'|'*)
    fail "failed: pre-existing source journal VersionId is malformed" 3 ;; esac
  [ "${#preexisting_binding_version}" -le 1024 ] || \
    fail "failed: pre-existing source journal VersionId is malformed" 3
  case "$preexisting_binding_sha" in *[!0-9a-f]*|'')
    fail "failed: pre-existing source journal digest is malformed" 3 ;; esac
  [ "${#preexisting_binding_sha}" -eq 64 ] || \
    fail "failed: pre-existing source journal digest is malformed" 3
  preexisting_journal_versions=$(aws s3api list-object-versions --region "$region" \
    --bucket "$journal_bucket" --prefix "$journal_key" --output json)
  printf '%s' "$preexisting_journal_versions" | jq -e --arg key "$journal_key" \
    --arg version "$preexisting_binding_version" '
      (.IsTruncated // false) == false and all(.Versions[]?; .Key == $key) and
      all(.DeleteMarkers[]?; .Key == $key) and (.DeleteMarkers // [] | length) == 0 and
      (.Versions // [] | length) == 1 and .Versions[0].VersionId == $version
    ' >/dev/null || fail "failed: pre-existing immutable journal history is not exact" 3
  preexisting_journal_history_canonical=$(printf '%s' "$preexisting_journal_versions" | \
    jq -cS '{IsTruncated:(.IsTruncated//false),Versions:(.Versions//[]),DeleteMarkers:(.DeleteMarkers//[])}')
fi
if [ "$replay_operation_preexisting" = true ]; then
  preexisting_replay_row_snapshot=$(psql_value_database DOCUMENT_STORE "$replay_database" \
    "SELECT to_jsonb(o)::text FROM document_owner_erasure_operations o WHERE operation_id=:'operation'" \
    --set=operation="$operation_id")
fi

versions=$(aws s3api list-object-versions --region "$region" --bucket "$bucket" --prefix "$object_key" --output json)
printf '%s' "$versions" | jq -e --arg key "$object_key" --arg source1 "$source_version_one" --arg source2 "$source_version_two" '
  (.IsTruncated // false) == false and
  all(.Versions[]?; .Key == $key) and all(.DeleteMarkers[]?; .Key == $key) and
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
  [ "$status" = 202 ] || fail "failed: isolated Document Store returned HTTP $status instead of exact 202" 3
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
source_response_canonical=$(jq -cS . "$source_response_file")
source_row_after_first=$(psql_value_database DOCUMENT_STORE document_store \
  "SELECT to_jsonb(o)::text FROM document_owner_erasure_operations o WHERE operation_id=:'operation'" \
  --set=operation="$operation_id")
if [ "$source_operation_preexisting" = true ]; then
  [ "$source_row_after_first" = "$preexisting_source_row_snapshot" ] || \
    fail "failed: first redrive source retry mutated its pre-existing canonical row" 3
fi

journal_binding=$(psql_value_database DOCUMENT_STORE document_store \
  "SELECT journal_object_key || '|' || journal_object_version || '|' || journal_content_sha256 FROM document_owner_erasure_operations WHERE operation_id = :'operation' AND state='BACKUP_RETENTION_PENDING' AND owner_id IS NULL AND document_count=0 AND object_scope_count=0 AND journal_required=true AND journal_schema_version='document-permanent-erasure-recovery-journal.v1' AND journal_recorded_at IS NOT NULL AND live_data_erased_at IS NOT NULL AND backup_retention_days=35 AND restore_replay_id IS NULL" \
  --set=operation="$operation_id")
bound_journal_key=${journal_binding%%|*}
journal_remainder=${journal_binding#*|}
bound_journal_version=${journal_remainder%%|*}
bound_journal_sha=${journal_remainder#*|}
[ "$bound_journal_key" = "$journal_key" ] || fail "failed: source DB journal key mismatch" 3
case "$bound_journal_version" in ''|null|*'|'*) fail "failed: source DB journal VersionId is malformed" 3 ;; esac
[ "${#bound_journal_version}" -le 1024 ] || fail "failed: source DB journal VersionId is malformed" 3
case "$bound_journal_sha" in *[!0-9a-f]*|'') fail "failed: source DB journal digest is malformed" 3 ;; esac
[ "${#bound_journal_sha}" -eq 64 ] || fail "failed: source DB journal digest is malformed" 3

journal_versions=$(aws s3api list-object-versions --region "$region" --bucket "$journal_bucket" --prefix "$journal_key" --output json)
printf '%s' "$journal_versions" | jq -e --arg key "$journal_key" --arg version "$bound_journal_version" '
  (.IsTruncated // false) == false and
  all(.Versions[]?; .Key == $key) and all(.DeleteMarkers[]?; .Key == $key) and
  ([.DeleteMarkers[]? | select(.Key == $key)] | length) == 0 and
  ([.Versions[]? | select(.Key == $key)] | length) == 1 and
  [.Versions[]? | select(.Key == $key) | .VersionId] == [$version]
' >/dev/null || fail "failed: immutable journal history is not the exact one-version record" 3
stable_journal_history_canonical=$(printf '%s' "$journal_versions" | \
  jq -cS '{IsTruncated:(.IsTruncated//false),Versions:(.Versions//[]),DeleteMarkers:(.DeleteMarkers//[])}')
if [ "$source_operation_preexisting" = true ]; then
  [ "$journal_binding" = "$preexisting_source_journal_binding" ] || \
    fail "failed: first redrive source retry changed its journal binding" 3
  [ "$stable_journal_history_canonical" = "$preexisting_journal_history_canonical" ] || \
    fail "failed: first redrive source retry changed immutable journal history" 3
fi
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
  (.Retention.RetainUntilDate | sub("[+]00:00$";"Z") | fromdateiso8601) as $until |
  $until >= (now + (($days - 1) * 86400)) and $until <= (now + (($days + 1) * 86400))
' >/dev/null || fail "failed: immutable journal retention evidence is insufficient" 3

journal_request_sha=$(jq -er '.requestSha256 | select(test("^[0-9a-f]{64}$"))' "$journal_download")
journal_approval_sha=$(jq -er '.approvalReferenceSha256 | select(test("^[0-9a-f]{64}$"))' "$journal_download")
journal_policy=$(jq -er '.policyVersion | select(type == "string" and length > 0)' "$journal_download")
journal_backup_policy=$(jq -er '.backupRetentionPolicyVersion | select(type == "string" and length > 0)' "$journal_download")
journal_created_at=$(jq -er '.createdAt | select(type == "string" and length > 0)' "$journal_download")
[ "$(psql_value_database DOCUMENT_STORE document_store \
  "SELECT count(*)::text FROM document_owner_erasure_operations WHERE operation_id=:'operation' AND request_sha256=:'request' AND approval_reference_sha256=:'approval' AND policy_version=:'policy' AND backup_retention_policy_version=:'backup_policy' AND backup_retention_days=35 AND created_at=((:'created_at')::timestamptz AT TIME ZONE 'UTC') AND journal_content_sha256=:'journal_sha'" \
  --set=operation="$operation_id" --set=request="$journal_request_sha" --set=approval="$journal_approval_sha" \
  --set=policy="$journal_policy" --set=backup_policy="$journal_backup_policy" \
  --set=created_at="$journal_created_at" --set=journal_sha="$bound_journal_sha")" = 1 ] || \
  fail "failed: source DB is not canonically bound to the immutable journal payload" 3
source_row_snapshot=$source_row_after_first
[ "$(psql_value_database DOCUMENT_STORE document_store "SELECT count(*)::text FROM document_owner_erasure_operations")" = 1 ] && \
  [ "$(psql_value_database DOCUMENT_STORE document_store "SELECT count(*)::text FROM document_owner_erasure_scopes")" = 0 ] && \
  [ "$(psql_value_database DOCUMENT_STORE document_store "SELECT count(*)::text FROM document_owner_erasure_restore_requests")" = 0 ] || \
  fail "failed: source erasure created unexpected operation/scope/request rows" 3

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
[ "$(jq -cS . "$source_retry_response_file")" = "$source_response_canonical" ] || \
  fail "failed: source retry response changed canonical fields or timestamps" 3
[ "$(psql_value_database DOCUMENT_STORE document_store \
  "SELECT journal_object_key || '|' || journal_object_version || '|' || journal_content_sha256 FROM document_owner_erasure_operations WHERE operation_id = :'operation'" \
  --set=operation="$operation_id")" = "${journal_key}|${bound_journal_version}|${bound_journal_sha}" ] || \
  fail "failed: source retry changed the immutable journal binding" 3
[ "$(psql_value_database DOCUMENT_STORE document_store \
  "SELECT to_jsonb(o)::text FROM document_owner_erasure_operations o WHERE operation_id=:'operation'" \
  --set=operation="$operation_id")" = "$source_row_snapshot" ] || \
  fail "failed: source retry mutated the canonical operation row" 3
journal_versions_after_source_retry=$(aws s3api list-object-versions --region "$region" \
  --bucket "$journal_bucket" --prefix "$journal_key" --output json)
[ "$(printf '%s' "$journal_versions_after_source_retry" | jq -cS \
  '{IsTruncated:(.IsTruncated//false),Versions:(.Versions//[]),DeleteMarkers:(.DeleteMarkers//[])}')" \
  = "$stable_journal_history_canonical" ] || \
  fail "failed: source retry changed immutable journal history" 3
if [ "$source_operation_preexisting" = true ]; then
  [ "$(psql_value_database DOCUMENT_STORE document_store \
    "SELECT to_jsonb(o)::text FROM document_owner_erasure_operations o WHERE operation_id=:'operation'" \
    --set=operation="$operation_id")" = "$preexisting_source_row_snapshot" ] || \
    fail "failed: second redrive source retry mutated its pre-existing canonical row" 3
fi

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
replay_response_canonical=$(jq -cS . "$replay_response_file")
replay_row_snapshot=$(psql_value_database DOCUMENT_STORE "$replay_database" \
  "SELECT to_jsonb(o)::text FROM document_owner_erasure_operations o WHERE operation_id=:'operation'" \
  --set=operation="$operation_id")
[ -n "$replay_row_snapshot" ] || fail "failed: replay operation row was not reconstructed" 3
if [ "$replay_operation_preexisting" = true ]; then
  [ "$replay_row_snapshot" = "$preexisting_replay_row_snapshot" ] || \
    fail "failed: first redrive replay retry mutated its pre-existing canonical row" 3
fi
journal_versions_after_first_replay=$(aws s3api list-object-versions --region "$region" \
  --bucket "$journal_bucket" --prefix "$journal_key" --output json)
[ "$(printf '%s' "$journal_versions_after_first_replay" | jq -cS \
  '{IsTruncated:(.IsTruncated//false),Versions:(.Versions//[]),DeleteMarkers:(.DeleteMarkers//[])}')" \
  = "$stable_journal_history_canonical" ] || \
  fail "failed: first replay call changed immutable journal history" 3

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
[ "$(jq -cS . "$replay_retry_response_file")" = "$replay_response_canonical" ] || \
  fail "failed: replay retry response changed canonical fields or timestamps" 3
[ "$(psql_value_database DOCUMENT_STORE "$replay_database" \
  "SELECT to_jsonb(o)::text FROM document_owner_erasure_operations o WHERE operation_id=:'operation'" \
  --set=operation="$operation_id")" = "$replay_row_snapshot" ] || \
  fail "failed: replay retry mutated the reconstructed operation row" 3
if [ "$replay_operation_preexisting" = true ]; then
  [ "$(psql_value_database DOCUMENT_STORE "$replay_database" \
    "SELECT to_jsonb(o)::text FROM document_owner_erasure_operations o WHERE operation_id=:'operation'" \
    --set=operation="$operation_id")" = "$preexisting_replay_row_snapshot" ] || \
    fail "failed: second redrive replay retry mutated its pre-existing canonical row" 3
fi

replay_binding=$(psql_value_database DOCUMENT_STORE "$replay_database" \
  "SELECT journal_object_key || '|' || journal_object_version || '|' || journal_content_sha256 || '|' || restore_replay_id::text FROM document_owner_erasure_operations WHERE operation_id = :'operation' AND state='BACKUP_RETENTION_PENDING' AND owner_id IS NULL AND document_count=0 AND object_scope_count=0 AND journal_required=true AND journal_schema_version='document-permanent-erasure-recovery-journal.v1' AND journal_recorded_at IS NOT NULL AND live_data_erased_at IS NOT NULL AND restore_replay_id = :'replay' AND restore_replay_evidence_sha256 IS NOT NULL AND restore_replay_requested_at IS NOT NULL AND restore_replay_object_erased_at IS NOT NULL AND backup_retention_days=35" \
  --set=operation="$operation_id" --set=replay="$restore_replay_id")
[ "$replay_binding" = "${journal_key}|${bound_journal_version}|${bound_journal_sha}|${restore_replay_id}" ] || \
  fail "failed: replay DB did not bind the exact external journal and replay" 3
source_journal_contract=$(psql_value_database DOCUMENT_STORE document_store \
  "SELECT jsonb_build_object('ownerFingerprint',owner_fingerprint,'fingerprintKeyVerifier',fingerprint_key_verifier,'requestSha256',request_sha256,'approvalReferenceSha256',approval_reference_sha256,'operatorId',operator_id,'documentCount',document_count,'objectScopeCount',object_scope_count,'policyVersion',policy_version,'backupRetentionPolicyVersion',backup_retention_policy_version,'backupRetentionDays',backup_retention_days,'createdAt',created_at,'journalSchemaVersion',journal_schema_version,'journalObjectKey',journal_object_key,'journalObjectVersion',journal_object_version,'journalContentSha256',journal_content_sha256)::text FROM document_owner_erasure_operations WHERE operation_id=:'operation'" \
  --set=operation="$operation_id")
replay_journal_contract=$(psql_value_database DOCUMENT_STORE "$replay_database" \
  "SELECT jsonb_build_object('ownerFingerprint',owner_fingerprint,'fingerprintKeyVerifier',fingerprint_key_verifier,'requestSha256',request_sha256,'approvalReferenceSha256',approval_reference_sha256,'operatorId',operator_id,'documentCount',document_count,'objectScopeCount',object_scope_count,'policyVersion',policy_version,'backupRetentionPolicyVersion',backup_retention_policy_version,'backupRetentionDays',backup_retention_days,'createdAt',created_at,'journalSchemaVersion',journal_schema_version,'journalObjectKey',journal_object_key,'journalObjectVersion',journal_object_version,'journalContentSha256',journal_content_sha256)::text FROM document_owner_erasure_operations WHERE operation_id=:'operation'" \
  --set=operation="$operation_id")
[ "$replay_journal_contract" = "$source_journal_contract" ] || \
  fail "failed: replay reconstruction changed journal policies, timestamps, hashes or owner fingerprint" 3
[ "$(psql_value_database DOCUMENT_STORE "$replay_database" "SELECT count(*)::text FROM document_owner_erasure_restore_requests")" = 0 ] || \
  fail "failed: replay request remains pending" 3
[ "$(psql_value_database DOCUMENT_STORE "$replay_database" "SELECT count(*)::text FROM document_owner_erasure_operations")" = 1 ] && \
  [ "$(psql_value_database DOCUMENT_STORE "$replay_database" "SELECT count(*)::text FROM document_owner_erasure_scopes")" = 0 ] || \
  fail "failed: replay created unexpected operation or scope rows" 3
journal_versions_after_retry=$(aws s3api list-object-versions --region "$region" --bucket "$journal_bucket" --prefix "$journal_key" --output json)
printf '%s' "$journal_versions_after_retry" | jq -e --arg key "$journal_key" --arg version "$bound_journal_version" '
  (.IsTruncated // false) == false and
  all(.Versions[]?; .Key == $key) and all(.DeleteMarkers[]?; .Key == $key) and
  ([.DeleteMarkers[]? | select(.Key == $key)] | length) == 0 and
  ([.Versions[]? | select(.Key == $key)] | length) == 1 and
  [.Versions[]? | select(.Key == $key) | .VersionId] == [$version]
' >/dev/null || fail "failed: source/replay retries changed immutable journal version history" 3
[ "$(printf '%s' "$journal_versions_after_retry" | jq -cS \
  '{IsTruncated:(.IsTruncated//false),Versions:(.Versions//[]),DeleteMarkers:(.DeleteMarkers//[])}')" \
  = "$stable_journal_history_canonical" ] || \
  fail "failed: replay retry changed immutable journal history" 3

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
source_response_sha=$(printf '%s' "$source_response_canonical" | sha256sum | cut -d' ' -f1)
replay_response_sha=$(printf '%s' "$replay_response_canonical" | sha256sum | cut -d' ' -f1)
source_row_sha=$(printf '%s' "$source_row_snapshot" | sha256sum | cut -d' ' -f1)
replay_row_sha=$(printf '%s' "$replay_row_snapshot" | sha256sum | cut -d' ' -f1)
journal_contract_sha=$(printf '%s' "$source_journal_contract" | sha256sum | cut -d' ' -f1)
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
  --arg schemaFingerprint "$pre_application_schema_fingerprint" --arg sourceResponseSha "$source_response_sha" \
  --arg replayResponseSha "$replay_response_sha" --arg sourceRowSha "$source_row_sha" \
  --arg replayRowSha "$replay_row_sha" --arg journalContractSha "$journal_contract_sha" \
  --arg generationOneSha "$sha_one" --arg generationTwoSha "$sha_two" \
  --argjson generationOneSize "$size_one" --argjson generationTwoSize "$size_two" \
  --argjson sourceReadiness "$source_readiness" --argjson replayReadiness "$replay_readiness" \
  --argjson attempt "$attempt" --argjson sourcePreexisting "$source_operation_preexisting" \
  --argjson replayPreexisting "$replay_operation_preexisting" '{
    schemaVersion:"jsc-public-beta-restore-semantic-raw.v1",status:"RAW_VERIFIED",environment:"public-beta",
    drillId:$drill,startedAt:$started,completedAt:$completed,verifierTaskArn:$task,
    releaseCandidate:{releaseId:$release,releaseAttestationId:$attestation},
    restoreSource:{canaryId:$canary,sourceEvidenceSha256:$sourceEvidence,sourceMarkerSha256:$marker},
    localRuntimeAssertions:{cloneTaskArn:$cloneTask,sourceApplicationTaskArn:$sourceTask,
      replayApplicationTaskArn:$replayTask,cloneTaskDefinitionArn:$cloneDefinition,
      applicationTaskDefinitionArn:$appDefinition,verifierTaskDefinitionArn:$verifierDefinition,
      documentStoreImageDigest:$documentImage,releaseOperatorImageDigest:$operatorImage,
      vpcId:$vpc,restoreDatabaseSecurityGroupId:$databaseSg,semanticSecurityGroupId:$semanticSg,
      restoredDatabaseArn:$restoredDatabase,restoredDatabaseEndpoint:$restoredEndpoint},
    databaseVerification:{logicalDatabases:["authentication","user_profile","job_service","document_generation","document_store","application_tracker","payment"],
      exactCanaryRowCounts:{authentication:1,userProfile:1,jobService:1,documentGeneration:1,
        documentStore:1,applicationTracker:1,payment:1,replayClone:1},
      exactCanaryRowsVerified:true,preOperationReplayCloneVerified:true,
      preApplicationSchemaFingerprint:$schemaFingerprint,schemaAndFlywayFingerprintUnchangedAfterCandidateStartup:true,
      nonPrivilegedRolesVerified:true,tlsConnectionsVerified:true,flywayHistoriesVerified:true,
      emptyBootstrapDomainInvariantsVerified:true,paymentLedgerSeedAndEmptyStateReconciled:true},
    documentVerification:{mappingType:"NON_CUSTOMER_RESTORE_CANARY",bucket:$bucket,key:$key,
      destinationVersionCount:2,deleteMarkerCount:0,newDestinationVersionIdsVerified:true,
      generations:[{generation:1,versionId:$v1,sourceSha256:$generationOneSha,sizeBytes:$generationOneSize,
        exactSourceMetadataVerified:true,payloadSha256Verified:true,bucketKeyEnabled:true},
        {generation:2,versionId:$v2,sourceSha256:$generationTwoSha,sizeBytes:$generationTwoSize,
        exactSourceMetadataVerified:true,payloadSha256Verified:true,bucketKeyEnabled:true}],
      customerGeneratedDocumentMappingClaimed:false},
    erasureReplayVerification:{operationId:$operation,restoreReplayId:$replay,attempt:$attempt,
      sourceOperationPreexistingBeforeAttempt:$sourcePreexisting,
      replayOperationPreexistingBeforeAttempt:$replayPreexisting,syntheticOwnerSha256:$ownerSha,
      documentCount:0,objectScopeCount:0,sourceCanonicalResponseSha256:$sourceResponseSha,
      replayCanonicalResponseSha256:$replayResponseSha,sourceCanonicalRowSha256:$sourceRowSha,
      replayCanonicalRowSha256:$replayRowSha,journalContractSha256:$journalContractSha,
      sourceCanonicalRetryVerified:true,replayCanonicalRetryVerified:true,
      sourceReplayJournalContractEqual:true,
      journal:{bucket:$journalBucket,key:$journalKey,versionId:$journalVersion,contentSha256:$journalSha,
        sizeBytes:$journalSize,objectLockMode:"GOVERNANCE",minimumRetentionDays:$journalDays,
        versionCount:1,deleteMarkerCount:0,bucketKeyEnabled:true,contentSha256MetadataVerified:true,
        writeByCandidateApplicationVerified:true,exactVersionReadBySeparateVerifierVerified:true,
        unchangedAfterSourceAndReplayRetries:true},
      externalJournalWriteVerified:true,externalJournalReadVerified:true,absentOperationReconstructed:true,
      exactReplayVerified:true,restoreReplayEvidenceRecorded:true,restoreReplayObjectErasedAtVerified:true,
      sourceReadiness:$sourceReadiness,replayReadiness:$replayReadiness},
    scopeLimitations:["SYNTHETIC_NON_CUSTOMER_EMPTY_SCOPE",
      "JOURNAL_WRITE_READ_RETRY_AND_ABSENT_OPERATION_RECONSTRUCTION_PROVEN",
      "CUSTOMER_OBJECT_ERASURE_NOT_CLAIMED",
      "CUSTOMER_METADATA_OBJECT_MAPPING_NOT_CLAIMED",
      "RESTORED_S3_CANARY_PROVES_VERSION_METADATA_SIZE_AND_PAYLOAD_INTEGRITY",
      "LIVENESS_AND_FLYWAY_STARTUP_ONLY","AGGREGATE_DOCUMENT_STORAGE_HEALTH_NOT_CLAIMED"]
  }')
printf 'JSC_RESTORE_SEMANTIC_RAW_EVIDENCE_B64=%s\n' "$(printf '%s' "$evidence" | base64 | tr -d '\n')"
echo "restore semantic verifier passed exact database/S3 and application-path immutable-journal replay checks"
