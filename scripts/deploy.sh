#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
. "$SCRIPT_DIR/lib.sh"

DRY_RUN=0
SKIP_PREFLIGHT=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --skip-preflight) SKIP_PREFLIGHT=1 ;;
        *) die "unsupported argument: $1" 64 ;;
    esac
    shift
done

cd "$PROJECT_DIR"
require_command docker
require_command flock

lock_file=${DEPLOY_LOCK_FILE:-/tmp/digital-bast-deploy.lock}
exec 9>"$lock_file"
flock -n 9 || die "another deployment is running" 75

if [ "$SKIP_PREFLIGHT" = "0" ]; then
    "$SCRIPT_DIR/preflight.sh" $(if [ "$DRY_RUN" = "1" ]; then printf '%s' '--dry-run'; fi)
fi

active_config=config/nginx/active-slot.conf
require_file "$active_config"
if grep -q 'web-blue:8000' "$active_config"; then
    current=blue
    target=green
elif grep -q 'web-green:8000' "$active_config"; then
    current=green
    target=blue
else
    die "active slot is indeterminate" 78
fi

compose() {
    docker compose --profile "$current" --profile "$target" "$@"
}

cleanup_failed_target() {
    if [ "${switched:-0}" = "0" ]; then
        compose stop "web-$target" "worker-$target" "runner-$target" >/dev/null 2>&1 || true
    fi
}
trap cleanup_failed_target EXIT HUP INT TERM
switched=0

app_image=${APP_IMAGE:-digital-bast:local}
if docker image inspect "$app_image" >/dev/null 2>&1; then
    printf '%s\n' "using local app image: $app_image"
    run compose pull postgres redis reverse-proxy
else
    run compose pull "web-$target" "worker-$target" "runner-$target" postgres redis prefect-server prefect-services reverse-proxy
fi
run compose up -d postgres redis prefect-server prefect-services reverse-proxy
run compose up -d --no-deps "web-$target"

if [ "$DRY_RUN" = "0" ]; then
    timeout_seconds=${HEALTH_TIMEOUT_SECONDS:-180}
    elapsed=0
    until [ "$(docker inspect --format '{{.State.Health.Status}}' "$(compose ps -q "web-$target")" 2>/dev/null || true)" = "healthy" ]; do
        [ "$elapsed" -lt "$timeout_seconds" ] || die "target slot failed health gate" 1
        sleep 5
        elapsed=$((elapsed + 5))
    done
    compose exec -T reverse-proxy wget -q -O /dev/null "http://web-$target:8000${SHADOW_PATH:-/health/ready}" || die "target slot failed shadow gate" 1
    compose run --rm --no-deps "web-$target" alembic upgrade head || die "migration gate failed; active slot preserved" 1
    compose up -d --no-deps "worker-$target" "runner-$target"
    sed "s/web-$current:8000/web-$target:8000/" "$active_config" > "$active_config.next"
    dd if="$active_config.next" of="$active_config" conv=notrunc status=none
    truncate -s "$(wc -c < "$active_config.next")" "$active_config"
    rm -f "$active_config.next"
    compose exec -T reverse-proxy nginx -t || {
        sed "s/web-$target:8000/web-$current:8000/" "$active_config" > "$active_config.next"
        dd if="$active_config.next" of="$active_config" conv=notrunc status=none
        truncate -s "$(wc -c < "$active_config.next")" "$active_config"
        rm -f "$active_config.next"
        die "proxy configuration gate failed; active slot preserved" 1
    }
    compose exec -T reverse-proxy nginx -s reload
    switched=1
    compose exec -T reverse-proxy wget -q -O /dev/null "http://127.0.0.1:8080${PUBLIC_HEALTH_PATH:-/health/ready}" || {
        sed "s/web-$target:8000/web-$current:8000/" "$active_config" > "$active_config.next"
        dd if="$active_config.next" of="$active_config" conv=notrunc status=none
        truncate -s "$(wc -c < "$active_config.next")" "$active_config"
        rm -f "$active_config.next"
        compose exec -T reverse-proxy nginx -s reload
        switched=0
        die "public health gate failed; proxy rolled back" 1
    }
else
    printf '%s\n' "DRY-RUN health web-$target"
    printf '%s\n' "DRY-RUN shadow web-$target"
    printf '%s\n' "DRY-RUN migration alembic upgrade head"
    printf '%s\n' "DRY-RUN start worker-$target runner-$target"
    printf '%s\n' "DRY-RUN switch $current to $target"
    printf '%s\n' "DRY-RUN public health and rollback on failure"
fi

trap - EXIT HUP INT TERM
printf '%s\n' "deployment complete: $target"
