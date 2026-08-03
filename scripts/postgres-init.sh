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
SQL

rm -f /dev/shm/digital-bast-init/app_database_password
rm -f /dev/shm/digital-bast-init/prefect_database_password
rmdir /dev/shm/digital-bast-init
touch "$PGDATA/.digital-bast-initialized"
