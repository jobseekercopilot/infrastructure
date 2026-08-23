#!/bin/sh
set -eu

source_database=${DOCUMENT_STORE_DATABASE:-document_store}
clone_database=${RESTORE_REPLAY_DATABASE:-}
source_marker_sha=${RESTORE_SOURCE_MARKER_SHA256:-}
drill_id=${RESTORE_DRILL_ID:-}
release_id=${RELEASE_ID:-}
canary_id=${RESTORE_SOURCE_CANARY_ID:-}
attempt=${RESTORE_ATTEMPT:-}
operation_id=${RESTORE_ERASURE_OPERATION_ID:-}
restore_replay_id=${RESTORE_ERASURE_REPLAY_ID:-}

[ "$source_database" = document_store ] || {
  echo "restore clone refused: source database must be document_store" >&2
  exit 2
}
case "$clone_database" in restore_replay_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "restore clone refused: replay database name is malformed" >&2; exit 2 ;;
esac
case "$source_marker_sha" in *[!0-9a-f]*|'') echo "restore clone refused: marker digest is malformed" >&2; exit 2 ;; esac
[ "${#source_marker_sha}" -eq 64 ] || { echo "restore clone refused: marker digest is malformed" >&2; exit 2; }
case "$drill_id" in *[!a-z0-9-]*|'') echo "restore clone refused: drill ID is malformed" >&2; exit 2 ;; esac
[ "${#drill_id}" -ge 8 ] && [ "${#drill_id}" -le 32 ] || {
  echo "restore clone refused: drill ID is malformed" >&2
  exit 2
}
case "$drill_id" in -*|*-) echo "restore clone refused: drill ID is malformed" >&2; exit 2 ;; esac
case "$release_id" in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "restore clone refused: release ID is malformed" >&2; exit 2 ;;
esac
case "$canary_id" in *[!a-z0-9-]*|'') echo "restore clone refused: canary ID is malformed" >&2; exit 2 ;; esac
[ "${#canary_id}" -ge 8 ] && [ "${#canary_id}" -le 32 ] || {
  echo "restore clone refused: canary ID is malformed" >&2
  exit 2
}
case "$canary_id" in -*|*-) echo "restore clone refused: canary ID is malformed" >&2; exit 2 ;; esac
case "$attempt" in 1|2|3) ;; *) echo "restore clone refused: attempt must be 1, 2 or 3" >&2; exit 2 ;; esac
printf '%s\n%s\n' "$operation_id" "$restore_replay_id" | jq -eRs '
  split("\n")[:-1] | length == 2 and .[0] != .[1] and
  all(.[]; test("^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"))
' >/dev/null || { echo "restore clone refused: erasure identifiers are malformed or duplicate" >&2; exit 2; }
case "$operation_id" in 7e57c0de-*) ;; *) echo "restore clone refused: operation is outside the reserved namespace" >&2; exit 2 ;; esac

for name in PGHOST PGPORT PGSSLROOTCERT MASTER_USERNAME MASTER_PASSWORD DOCUMENT_STORE_USERNAME DOCUMENT_STORE_PASSWORD; do
  eval "value=\${$name:-}"
  [ -n "$value" ] || { echo "restore clone refused: missing $name" >&2; exit 2; }
done
[ "$PGPORT" = 5432 ] || { echo "restore clone refused: PostgreSQL port must be 5432" >&2; exit 2; }
[ "$DOCUMENT_STORE_USERNAME" = document_store ] || {
  echo "restore clone refused: target owner must be document_store" >&2
  exit 2
}
[ -r "$PGSSLROOTCERT" ] || { echo "restore clone refused: pinned RDS CA is unreadable" >&2; exit 2; }
for command_name in jq psql sha256sum; do
  command -v "$command_name" >/dev/null || {
    echo "restore clone refused: $command_name is unavailable" >&2
    exit 2
  }
done

export PGSSLMODE=verify-full
export PGCONNECT_TIMEOUT=10
export PGOPTIONS='-c statement_timeout=120000 -c lock_timeout=30000 -c idle_in_transaction_session_timeout=120000'
document_value() {
  sql=$1
  shift
  PGPASSWORD="$DOCUMENT_STORE_PASSWORD" PGUSER="$DOCUMENT_STORE_USERNAME" PGDATABASE="$source_database" \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet --tuples-only --no-align \
      "$@" --command="$sql"
}

admin_value() {
  sql=$1
  shift
  PGPASSWORD="$MASTER_PASSWORD" PGUSER="$MASTER_USERNAME" PGDATABASE=postgres \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet --tuples-only --no-align \
      "$@" --command="$sql"
}

clone_value() {
  sql=$1
  shift
  PGPASSWORD="$DOCUMENT_STORE_PASSWORD" PGUSER="$DOCUMENT_STORE_USERNAME" PGDATABASE="$clone_database" \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet --tuples-only --no-align \
      "$@" --command="$sql"
}

# Fingerprint the migration history and every application-visible public-schema
# object before either candidate application starts. Row data is deliberately
# excluded: the verifier later proves the expected erasure rows independently.
# The fingerprint is persisted only in the isolated clone database comment so
# a candidate startup cannot silently apply or repair migrations and then pass.
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

document_schema_fingerprint() {
  document_value "$schema_state_sql" | sha256sum | cut -d' ' -f1
}

clone_schema_fingerprint() {
  clone_value "$schema_state_sql" | sha256sum | cut -d' ' -f1
}

operation_journal_contract_sql=$(cat <<'SQL'
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

verify_source_retry_operation() {
  journal_key="permanent-erasures/v1/${operation_id}.json"
  [ "$(document_value \
    "SELECT count(*)::text FROM document_owner_erasure_operations WHERE operation_id=:'operation' AND state='BACKUP_RETENTION_PENDING' AND owner_id IS NULL AND document_count=0 AND object_scope_count=0 AND journal_required=true AND journal_schema_version='document-permanent-erasure-recovery-journal.v1' AND journal_object_key=:'journal_key' AND journal_object_version IS NOT NULL AND length(journal_object_version)>0 AND journal_content_sha256 ~ '^[0-9a-f]{64}$' AND journal_recorded_at IS NOT NULL AND live_data_erased_at IS NOT NULL AND backup_retention_days=35 AND restore_replay_id IS NULL AND restore_replay_evidence_sha256 IS NULL AND restore_replay_requested_at IS NULL AND restore_replay_object_erased_at IS NULL" \
    --set=operation="$operation_id" --set=journal_key="$journal_key")" = 1 ] || {
    echo "restore clone refused: source retry operation is not the exact immutable-journal state" >&2
    exit 3
  }
  source_retry_journal_contract=$(document_value "$operation_journal_contract_sql" --set=operation="$operation_id")
  [ -n "$source_retry_journal_contract" ] || {
    echo "restore clone refused: source retry journal contract is absent" >&2
    exit 3
  }
}

verify_replay_retry_operation() {
  [ "$(clone_value \
    "SELECT count(*)::text FROM document_owner_erasure_operations WHERE operation_id=:'operation' AND state='BACKUP_RETENTION_PENDING' AND owner_id IS NULL AND document_count=0 AND object_scope_count=0 AND journal_required=true AND journal_schema_version='document-permanent-erasure-recovery-journal.v1' AND journal_object_key=:'journal_key' AND journal_object_version IS NOT NULL AND length(journal_object_version)>0 AND journal_content_sha256 ~ '^[0-9a-f]{64}$' AND journal_recorded_at IS NOT NULL AND live_data_erased_at IS NOT NULL AND backup_retention_days=35 AND restore_replay_id=:'replay' AND restore_replay_evidence_sha256 ~ '^[0-9a-f]{64}$' AND restore_replay_requested_at IS NOT NULL AND restore_replay_object_erased_at IS NOT NULL" \
    --set=operation="$operation_id" --set=journal_key="permanent-erasures/v1/${operation_id}.json" \
    --set=replay="$restore_replay_id")" = 1 ] || {
    echo "restore clone refused: replay retry operation is not the exact reconstructed state" >&2
    exit 3
  }
  replay_retry_journal_contract=$(clone_value "$operation_journal_contract_sql" --set=operation="$operation_id")
  [ "$replay_retry_journal_contract" = "$source_retry_journal_contract" ] || {
    echo "restore clone refused: replay retry journal contract differs from the source operation" >&2
    exit 3
  }
}

verify_clone() {
  [ "$(clone_value "SELECT current_database() || '|' || current_user || '|' || ssl::text FROM pg_stat_ssl WHERE pid=pg_backend_pid()")" = "${clone_database}|document_store|t" ] || {
    echo "restore clone refused: replay connection is not the exact TLS-bound document_store role" >&2
    exit 3
  }
  flyway=$(clone_value "SELECT CASE WHEN to_regclass('public.flyway_schema_history') IS NULL THEN 'missing' ELSE (SELECT count(*)::text || ':' || count(*) FILTER (WHERE NOT success)::text FROM flyway_schema_history) END")
  total=${flyway%%:*}
  failed=${flyway##*:}
  case "$total:$failed" in *[!0-9:]*|:|*:|:*) total=0; failed=1 ;; esac
  [ "$total" -gt 0 ] && [ "$failed" -eq 0 ] || {
    echo "restore clone refused: replay Flyway history is incomplete" >&2
    exit 3
  }
  [ "$(clone_value \
    "SELECT count(*)::text FROM jsc_restore_source_canary_v1 WHERE canary_id = :'canary' AND release_id = :'release' AND marker_sha256 = :'marker' AND release_attestation_id ~ '^[0-9a-f]{64}$'" \
    --set=canary="$canary_id" --set=release="$release_id" --set=marker="$source_marker_sha")" = 1 ] || {
    echo "restore clone refused: replay database lacks the exact source-canary binding" >&2
    exit 3
  }
  clone_operation_count=$(clone_value "SELECT count(*)::text FROM document_owner_erasure_operations")
  [ "$(clone_value "SELECT count(*)::text FROM document_owner_erasure_restore_requests")" = 0 ] && \
    [ "$(clone_value "SELECT count(*)::text FROM document_owner_erasure_scopes")" = 0 ] || {
    echo "restore clone refused: replay database contains unexpected scope/request rows" >&2
    exit 3
  }
  case "$clone_operation_count" in
    0) ;;
    1)
      [ "$attempt" -ge 2 ] || {
        echo "restore clone refused: first attempt found a pre-existing replay operation" >&2
        exit 3
      }
      [ "$source_operation_count" = 1 ] || {
        echo "restore clone refused: replay operation exists without its exact source operation" >&2
        exit 3
      }
      verify_source_retry_operation
      verify_replay_retry_operation
      ;;
    *)
      echo "restore clone refused: replay database contains extra erasure operations" >&2
      exit 3
      ;;
  esac
  [ "$(clone_schema_fingerprint)" = "$source_schema_fingerprint" ] || {
    echo "restore clone refused: replay schema/Flyway fingerprint differs from its pre-operation source" >&2
    exit 3
  }
}

[ "$(document_value "SELECT current_database() || '|' || current_user || '|' || ssl::text FROM pg_stat_ssl WHERE pid=pg_backend_pid()")" = "document_store|document_store|t" ] || {
  echo "restore clone refused: source connection is not the exact TLS-bound document_store role" >&2
  exit 3
}
[ "$(document_value \
  "SELECT count(*)::text FROM jsc_restore_source_canary_v1 WHERE canary_id = :'canary' AND release_id = :'release' AND marker_sha256 = :'marker' AND release_attestation_id ~ '^[0-9a-f]{64}$'" \
  --set=canary="$canary_id" --set=release="$release_id" --set=marker="$source_marker_sha")" = 1 ] || {
  echo "restore clone refused: source lacks the exact restore-canary binding" >&2
  exit 3
}
source_schema_fingerprint=$(document_schema_fingerprint)
case "$source_schema_fingerprint" in *[!0-9a-f]*|'')
  echo "restore clone refused: source schema fingerprint is malformed" >&2; exit 3 ;;
esac
[ "${#source_schema_fingerprint}" -eq 64 ] || {
  echo "restore clone refused: source schema fingerprint is malformed" >&2
  exit 3
}
clone_binding="jsc-restore-replay-v2:${drill_id}:${source_marker_sha}:${source_schema_fingerprint}"
source_operation_count=$(document_value "SELECT count(*)::text FROM document_owner_erasure_operations")
case "$source_operation_count" in
  0) ;;
  1)
    [ "$attempt" -ge 2 ] || {
      echo "restore clone refused: first attempt found a pre-existing source operation" >&2
      exit 3
    }
    verify_source_retry_operation
    ;;
  *)
    echo "restore clone refused: source contains extra erasure operations" >&2
    exit 3
    ;;
esac
[ "$source_operation_count" = 0 ] || {
  # A retry may reuse only the original, source-bound clone in its exact
  # pre-operation or canonical reconstructed state. Never create a new clone
  # after an operation has acquired an immutable journal identity.
  source_has_operation=true
}
source_has_operation=${source_has_operation:-false}

clone_state=$(admin_value \
  "SELECT d.datname || '|' || pg_get_userbyid(d.datdba) || '|' || COALESCE(shobj_description(d.oid,'pg_database'),'') FROM pg_database d WHERE d.datname = :'clone'" \
  --set=clone="$clone_database")
if [ -n "$clone_state" ]; then
  [ "$clone_state" = "${clone_database}|document_store|${clone_binding}" ] || {
    echo "restore clone refused: existing replay database has another owner or source binding" >&2
    exit 3
  }
  [ "$(admin_value "SELECT count(*)::text FROM pg_stat_activity WHERE datname = :'clone'" --set=clone="$clone_database")" = 0 ] || {
    echo "restore clone refused: existing replay database has an active connection" >&2
    exit 3
  }
  [ "$(admin_value "SELECT count(*)::text FROM pg_stat_activity WHERE datname = :'source'" --set=source="$source_database")" = 0 ] || {
    echo "restore clone refused: source database is not quiescent during replay-clone reuse" >&2
    exit 3
  }
  verify_clone
  echo "restore clone already exists with the exact pre-operation source binding"
  exit 0
fi

[ "$source_has_operation" = false ] || {
  echo "restore clone refused: source operation exists but its pre-operation clone is missing" >&2
  exit 3
}
[ "$(document_value "SELECT count(*)::text FROM document_owner_erasure_restore_requests")" = 0 ] || {
  echo "restore clone refused: source contains a restore request" >&2
  exit 3
}
[ "$(document_value "SELECT count(*)::text FROM document_owner_erasure_scopes")" = 0 ] || {
  echo "restore clone refused: source contains an erasure scope" >&2
  exit 3
}
[ "$(admin_value "SELECT count(*)::text FROM pg_stat_activity WHERE datname = :'source'" --set=source="$source_database")" = 0 ] || {
  echo "restore clone refused: document_store has an active connection" >&2
  exit 3
}

# psql variables cannot safely parameterise SQL identifiers directly. format
# with %I performs PostgreSQL identifier quoting, and the values were already
# reduced to exact allow-listed names above.
PGPASSWORD="$MASTER_PASSWORD" PGUSER="$MASTER_USERNAME" PGDATABASE=postgres \
  psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet \
    --set=clone="$clone_database" --set=source="$source_database" \
    --set=owner="$DOCUMENT_STORE_USERNAME" --set=binding="$clone_binding" <<'SQL'
SELECT format('CREATE DATABASE %I WITH TEMPLATE %I OWNER %I', :'clone', :'source', :'owner')) \gexec
SELECT format('COMMENT ON DATABASE %I IS %L', :'clone', :'binding') \gexec
SQL

[ "$(admin_value \
  "SELECT d.datname || '|' || pg_get_userbyid(d.datdba) || '|' || COALESCE(shobj_description(d.oid,'pg_database'),'') FROM pg_database d WHERE d.datname = :'clone'" \
  --set=clone="$clone_database")" = "${clone_database}|document_store|${clone_binding}" ] || {
  echo "restore clone failed: exact replay database binding was not persisted" >&2
  exit 3
}
verify_clone
echo "restore clone created from quiescent pre-operation document_store state"
