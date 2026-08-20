#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/lib.sh"

DRY_RUN=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        *) die "unsupported argument: $1" 64 ;;
    esac
    shift
done

require_command docker
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required" 69

# 8GB, not 10: the box also carries an unrelated legacy V1 stack (its own
# postgres, pgadmin) that this deploy does not own and will not stop to free
# space, so 10GB stopped being reachable even right after a full prune. A
# deploy needs roughly 4.5GB (nocodb-v2 ~1.5, Ollama llama3.2:3b ~2,
# bot-bridge ~1); 8GB keeps a margin above that without requiring space this
# box does not have spare.
available_min_gb=${AVAILABLE_MIN_GB:-8}
root_available_kb=$(df -Pk / | awk 'NR == 2 {print $4}')
[ "$root_available_kb" -ge "$((available_min_gb * 1024 * 1024))" ] || die "root disk has less than ${available_min_gb}GB available" 70

# active-slot.conf is runtime state and is not in git (see .gitignore). Seed
# it from the template on a fresh checkout so deploy.sh has something to read.
if [ ! -f config/nginx/active-slot.conf ]; then
    cp config/nginx/active-slot.conf.template config/nginx/active-slot.conf
fi

secrets_dir=${SECRETS_DIR:-./secrets}
secrets_gid=${SECRETS_GID:?SECRETS_GID is required}
for name in postgres_password app_database_password prefect_database_password session_secret app_database_dsn legacy_database_dsn prefect_database_dsn prefect_api_auth redis_url redis_acl nocodb_token nocodb_database_dsn sync_ingest_token google_service_account.json sqlserver_connection_string; do
    require_file "$secrets_dir/$name"
    mode=$(stat -c '%a' "$secrets_dir/$name")
    [ "$mode" = 640 ] || die "secret must have mode 0640: $secrets_dir/$name" 77
    group=$(stat -c '%g' "$secrets_dir/$name")
    [ "$group" = "$secrets_gid" ] || die "secret group does not match SECRETS_GID: $secrets_dir/$name" 77
done

docker info >/dev/null 2>&1 || die "Docker daemon is unavailable" 69
SECRETS_GID=$secrets_gid NOCODB_BASE_URL=${NOCODB_BASE_URL:-https://invalid.local} \
    NOCODB_V2_DB_PASSWORD=${NOCODB_V2_DB_PASSWORD:-preflight} docker compose config --quiet
printf '%s\n' "preflight passed"
