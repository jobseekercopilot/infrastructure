#!/bin/sh
set -eu

required="PGHOST PGPORT PGSSLROOTCERT MASTER_USERNAME MASTER_PASSWORD"
for name in $required; do
  eval "value=\${$name:-}"
  if [ -z "$value" ]; then
    echo "database bootstrap refused: missing $name" >&2
    exit 2
  fi
done

if [ ! -r "$PGSSLROOTCERT" ]; then
  echo "database bootstrap refused: pinned RDS CA bundle is not readable" >&2
  exit 2
fi

export PGUSER="$MASTER_USERNAME"
export PGPASSWORD="$MASTER_PASSWORD"
export PGDATABASE=postgres
export PGSSLMODE=verify-full
export PGCONNECT_TIMEOUT=10

psql_base="psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet"

bootstrap_database() {
  prefix="$1"
  eval "database=\${${prefix}_DATABASE:-}"
  eval "username=\${${prefix}_USERNAME:-}"
  eval "password=\${${prefix}_PASSWORD:-}"

  case "$database:$username" in
    *[!a-z0-9_:]*)
      echo "database bootstrap refused: unsafe identifier for $prefix" >&2
      exit 2
      ;;
  esac
  if [ -z "$database" ] || [ -z "$username" ] || [ -z "$password" ]; then
    echo "database bootstrap refused: incomplete credential for $prefix" >&2
    exit 2
  fi

  $psql_base \
    --set=username="$username" \
    --set=password="$password" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'username', :'password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'username') \gexec
SQL

  role_security_state="$($psql_base \
    --tuples-only --no-align \
    --set=username="$username" <<'SQL'
SELECT r.rolsuper::text
  || ':' || r.rolcreatedb::text
  || ':' || r.rolcreaterole::text
  || ':' || r.rolreplication::text
  || ':' || r.rolbypassrls::text
  || ':' || (SELECT count(*)::text FROM pg_auth_members m WHERE m.member = r.oid)
FROM pg_roles r
WHERE r.rolname = :'username';
SQL
)"
  if [ "$role_security_state" != "false:false:false:false:false:0" ]; then
    echo "database bootstrap refused: privileged role or membership detected for $prefix" >&2
    exit 3
  fi

  $psql_base \
    --set=username="$username" \
    --set=password="$password" <<'SQL'
SELECT format('ALTER ROLE %I LOGIN PASSWORD %L NOINHERIT CONNECTION LIMIT 14', :'username', :'password') \gexec
SQL

  $psql_base \
    --set=database="$database" \
    --set=username="$username" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I', :'database', :'username')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'database') \gexec
SELECT format('ALTER DATABASE %I OWNER TO %I', :'database', :'username') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'database') \gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I', :'database', :'username') \gexec
SQL

  $psql_base \
    --dbname="$database" \
    --set=username="$username" <<'SQL'
SELECT format('ALTER SCHEMA public OWNER TO %I', :'username') \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('GRANT USAGE, CREATE ON SCHEMA public TO %I', :'username') \gexec
SQL

  schema_state="$(PGPASSWORD="$password" PGUSER="$username" PGDATABASE="$database" \
    psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet --tuples-only --no-align <<'SQL'
SELECT pg_get_userbyid(nspowner)
  || ':' || has_database_privilege(current_user, current_database(), 'CONNECT')::text
  || ':' || has_database_privilege(current_user, current_database(), 'TEMP')::text
  || ':' || has_schema_privilege(current_user, 'public', 'USAGE')::text
  || ':' || has_schema_privilege(current_user, 'public', 'CREATE')::text
FROM pg_namespace
WHERE nspname = 'public';
SQL
)"
  if [ "$schema_state" != "$username:true:true:true:true" ]; then
    echo "database bootstrap schema privilege verification failed for $prefix" >&2
    exit 3
  fi

  state="$($psql_base \
    --tuples-only --no-align \
    --set=database="$database" \
    --set=username="$username" <<'SQL'
SELECT
  (SELECT rolcanlogin::text || ':' || rolsuper::text || ':' || rolcreatedb::text || ':' || rolcreaterole::text || ':' || rolinherit::text || ':' || rolreplication::text || ':' || rolbypassrls::text || ':' || rolconnlimit::text
   FROM pg_roles WHERE rolname = :'username')
  || ':' ||
  (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = :'database');
SQL
)"
  if [ "$state" != "true:false:false:false:false:false:false:14:$username" ]; then
    echo "database bootstrap least-privilege verification failed for $prefix" >&2
    exit 3
  fi

  if ! PGPASSWORD="$password" PGUSER="$username" PGDATABASE="$database" \
      psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet --command='SELECT 1' >/dev/null; then
    echo "database bootstrap verification failed for $prefix" >&2
    exit 3
  fi
  echo "database bootstrap verified: $prefix"
}

for prefix in \
  AUTHENTICATION \
  USER_PROFILE \
  JOB_SERVICE \
  DOCUMENT_GENERATION \
  DOCUMENT_STORE \
  APPLICATION_TRACKER \
  PAYMENT; do
  bootstrap_database "$prefix"
done

echo "database bootstrap complete"
