#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
. "$SCRIPT_DIR/lib.sh"

DRY_RUN=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        *) die "unsupported argument: $1" 64 ;;
    esac
    shift
done

cd "$PROJECT_DIR"
require_command docker
require_command flock
exec 9>"${DEPLOY_LOCK_FILE:-/tmp/digital-bast-deploy.lock}"
flock -n 9 || die "another deployment is running" 75

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

if [ "$DRY_RUN" = "1" ]; then
    printf '%s\n' "DRY-RUN verify web-$target is healthy"
    printf '%s\n' "DRY-RUN switch $current to $target"
    printf '%s\n' "rollback dry-run complete"
    exit 0
fi

compose() {
    docker compose --profile blue --profile green "$@"
}

[ "$(docker inspect --format '{{.State.Health.Status}}' "$(compose ps -q "web-$target")" 2>/dev/null || true)" = "healthy" ] || die "rollback slot is not healthy" 1
sed "s/web-$current:8000/web-$target:8000/" "$active_config" > "$active_config.next"
dd if="$active_config.next" of="$active_config" conv=notrunc status=none
truncate -s "$(wc -c < "$active_config.next")" "$active_config"
rm -f "$active_config.next"
compose exec -T reverse-proxy nginx -t || {
    sed "s/web-$target:8000/web-$current:8000/" "$active_config" > "$active_config.next"
    dd if="$active_config.next" of="$active_config" conv=notrunc status=none
    truncate -s "$(wc -c < "$active_config.next")" "$active_config"
    rm -f "$active_config.next"
    die "rollback proxy configuration is invalid; active slot preserved" 1
}
compose exec -T reverse-proxy nginx -s reload
compose exec -T reverse-proxy wget -q -O /dev/null "http://127.0.0.1:8080${PUBLIC_HEALTH_PATH:-/health/ready}" || {
    sed "s/web-$target:8000/web-$current:8000/" "$active_config" > "$active_config.next"
    dd if="$active_config.next" of="$active_config" conv=notrunc status=none
    truncate -s "$(wc -c < "$active_config.next")" "$active_config"
    rm -f "$active_config.next"
    compose exec -T reverse-proxy nginx -s reload
    die "rollback health gate failed; original slot restored" 1
}
compose stop "web-$current" "worker-$current" "runner-$current"
printf '%s\n' "rollback complete: $target"
