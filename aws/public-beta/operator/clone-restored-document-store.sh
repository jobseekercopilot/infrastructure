#!/bin/sh
set -eu

source_database=${DOCUMENT_STORE_DATABASE:-document_store}
clone_database=${RESTORE_REPLAY_DATABASE:-}
source_marker_sha=${RESTORE_SOURCE_MARKER_SHA256:-}
drill_id=${RESTORE_DRILL_ID:-}
release_id=${RELEASE_ID:-}
canary_id=${RESTORE_SOURCE_CANARY_ID:-}

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
command -v psql >/dev/null || { echo "restore clone refused: psql is unavailable" >&2; exit 2; }

export PGSSLMODE=verify-full
export PGCONNECT_TIMEOUT=10
export PGOPTIONS='-c statement_timeout=120000 -c lock_timeout=30000 -c idle_in_transaction_session_timeout=120000'
clone_binding="jsc-restore-replay-v1:${drill_id}:${source_marker_sha}"

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
  [ "$(clone_value "SELECT count(*)::text FROM document_owner_erasure_operations")" = 0 ] && \
    [ "$(clone_value "SELECT count(*)::text FROM document_owner_erasure_restore_requests")" = 0 ] || {
    echo "restore clone refused: replay database is not the preserved pre-operation state" >&2
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
[ "$(document_value "SELECT count(*)::text FROM document_owner_erasure_operations")" = 0 ] || {
  # A retry may preserve a valid pre-operation clone only. Never create a new
  # clone after an operation has acquired an immutable journal identity.
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
