#!/bin/sh
set -eu

required="PGHOST PGPORT PGSSLROOTCERT"
for name in $required; do
  eval "value=\${$name:-}"
  if [ -z "$value" ]; then
    echo "migration verification refused: missing $name" >&2
    exit 2
  fi
done

if [ ! -r "$PGSSLROOTCERT" ]; then
  echo "migration verification refused: pinned RDS CA bundle is not readable" >&2
  exit 2
fi

export PGSSLMODE=verify-full
export PGCONNECT_TIMEOUT=10

verify_database() {
  prefix="$1"
  eval "database=\${${prefix}_DATABASE:-}"
  eval "username=\${${prefix}_USERNAME:-}"
  eval "password=\${${prefix}_PASSWORD:-}"

  if [ -z "$database" ] || [ -z "$username" ] || [ -z "$password" ]; then
    echo "migration verification refused: incomplete credential for $prefix" >&2
    exit 2
  fi

  table_name="$(PGPASSWORD="$password" PGUSER="$username" PGDATABASE="$database" \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet --tuples-only --no-align \
      --command="SELECT to_regclass('public.flyway_schema_history')")"
  if [ "$table_name" != "flyway_schema_history" ]; then
    echo "migration verification failed: $prefix has no Flyway history" >&2
    exit 3
  fi

  result="$(PGPASSWORD="$password" PGUSER="$username" PGDATABASE="$database" \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet --tuples-only --no-align \
      --command='SELECT count(*) || '"'"':'"'"' || count(*) FILTER (WHERE NOT success) FROM flyway_schema_history')"
  total="${result%%:*}"
  failed="${result##*:}"
  case "$total:$failed" in *[!0-9:]*|:|*:|:*) total=0; failed=1 ;; esac
  if [ "$total" -eq 0 ] || [ "$failed" -ne 0 ]; then
    echo "migration verification failed: $prefix history=$result" >&2
    exit 3
  fi
  echo "migration verification passed: $prefix history=$result"
}

for prefix in \
  AUTHENTICATION \
  USER_PROFILE \
  JOB_SERVICE \
  DOCUMENT_GENERATION \
  DOCUMENT_STORE \
  APPLICATION_TRACKER \
  PAYMENT; do
  verify_database "$prefix"
done

echo "all Flyway histories verified"
