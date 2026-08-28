#!/bin/sh
set -eu

# Manual, rarely-run deploy for wa-session ONLY -- the WhatsApp session
# holder. Deliberately NOT part of scripts/deploy.sh's automated blue/green
# flow: that flow runs on every app deploy, and recreating the container
# that holds the live Baileys socket forces a reconnect that WhatsApp's own
# anti-abuse system can penalize after a few rapid repeats. Run this
# yourself, only when wa-session/ itself actually changed.
#
# Usage: SSH into the box, cd into the release directory you want to deploy
# from (same one scripts/deploy.sh would use), then run this script.

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

lock_file=${DEPLOY_WA_SESSION_LOCK_FILE:-/tmp/digital-bast-deploy-wa-session.lock}
exec 9>"$lock_file"
flock -n 9 || die "another wa-session deployment is running" 75

active_config=config/nginx/active-slot.conf
require_file "$active_config"
if grep -q 'web-blue:8000' "$active_config"; then
    current=blue
elif grep -q 'web-green:8000' "$active_config"; then
    current=green
else
    die "active slot is indeterminate" 78
fi

# wa-session has no blue/green concept -- one instance, paired to one
# WhatsApp number -- but the compose project still needs a profile to
# resolve web-blue/web-green's other service definitions.
compose() {
    docker compose --profile "$current" "$@"
}

session_image=${WA_SESSION_IMAGE:-digital-bast-wa-session:local}
previous_session_image=""
if [ "$DRY_RUN" = "0" ]; then
    session_container=$(compose ps -q wa-session 2>/dev/null || true)
    if [ -n "$session_container" ]; then
        previous_session_image=$(docker inspect --format '{{.Image}}' "$session_container" 2>/dev/null || true)
    fi
fi

rollback_session() {
    [ -n "$previous_session_image" ] || return 1
    docker image inspect "$previous_session_image" >/dev/null 2>&1 || return 1
    docker tag "$previous_session_image" "$session_image" || return 1
    compose up -d --no-deps --force-recreate wa-session || return 1
    return 0
}

run compose build wa-session

if [ "$DRY_RUN" = "0" ]; then
    compose up -d --no-deps --force-recreate wa-session
    timeout_seconds=${HEALTH_TIMEOUT_SECONDS:-180}
    elapsed=0
    while [ "$(docker inspect --format '{{.State.Health.Status}}' "$(compose ps -q wa-session)" 2>/dev/null || true)" != "healthy" ]; do
        if [ "$elapsed" -ge "$timeout_seconds" ]; then
            if rollback_session; then
                die "wa-session failed health gate; previous image restored" 1
            fi
            die "wa-session failed health gate and its rollback also failed -- check it by hand" 1
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
else
    printf '%s\n' "DRY-RUN restart + health wa-session (restore previous image on failure)"
fi

printf '%s\n' "wa-session deployment complete"
