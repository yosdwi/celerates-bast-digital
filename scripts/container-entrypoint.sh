#!/bin/sh
set -eu

load_secret() {
    name="$1"
    file_variable="${name}_FILE"
    eval "file_path=\${$file_variable:-}"
    if [ -n "$file_path" ]; then
        [ -f "$file_path" ] || exit 78
        value=$(cat "$file_path")
        [ -n "$value" ] || exit 78
        export "$name=$value"
        unset "$file_variable"
    fi
}

load_secret APP_SESSION_SECRET
load_secret APP_DATABASE_DSN
load_secret LEGACY_DATABASE_DSN
load_secret PREFECT_API_AUTH_STRING
load_secret PREFECT_SERVER_API_AUTH_STRING
load_secret PREFECT_API_DATABASE_CONNECTION_URL
load_secret PREFECT_REDIS_MESSAGING_URL
load_secret REDIS_URL
load_secret NOCODB_TOKEN
load_secret SQLSERVER_CONNECTION_STRING

mkdir -p "${HOME:-/tmp}/.prefect" "${PREFECT_HOME:-/tmp/prefect}" \
    "${PREFECT_UI_STATIC_DIRECTORY:-/tmp/prefect-ui}"

exec "$@"
