#!/bin/sh
set -eu

app_password=$(cat /dev/shm/digital-bast-init/app_database_password)
prefect_password=$(cat /dev/shm/digital-bast-init/prefect_database_password)

psql --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set app_password="$app_password" --set prefect_password="$prefect_password" <<'SQL'
SELECT format('CREATE ROLE digital_bast_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'digital_bast_app') \gexec
SELECT format('CREATE ROLE digital_bast_prefect LOGIN PASSWORD %L', :'prefect_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'digital_bast_prefect') \gexec
SELECT 'CREATE DATABASE digital_bast_app OWNER digital_bast_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'digital_bast_app') \gexec
SELECT 'CREATE DATABASE digital_bast_prefect OWNER digital_bast_prefect'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'digital_bast_prefect') \gexec
-- nocodb-v2 keeps its own metadata (users, views, data-source config) here.
-- The business tables it edits live in digital_bast_app, reached through the
-- least-privilege nocodb_editor role that migration 20260820_0004 creates.
SELECT 'CREATE DATABASE nocodb_v2_meta OWNER digital_bast_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'nocodb_v2_meta') \gexec
-- nocodb-v2's least-privilege login. Created here, as the bootstrap
-- superuser, because migration 20260820_0004 runs as digital_bast_app, which
-- deliberately has no CREATEROLE. The migration only grants; it skips the
-- grants when this role is absent. Password is set out of band by the deploy
-- runbook so no secret lands in a script.
SELECT 'CREATE ROLE nocodb_editor LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nocodb_editor') \gexec
SQL

rm -f /dev/shm/digital-bast-init/app_database_password
rm -f /dev/shm/digital-bast-init/prefect_database_password
rmdir /dev/shm/digital-bast-init
touch "$PGDATA/.digital-bast-initialized"
