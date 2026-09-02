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
require_file compose.production.yaml
# Production deploys must use the resource overrides too. In particular,
# TalentOps Web launches Chromium for BAST PDF generation and needs the same
# 1.5G ceiling already proven necessary for bot-worker's identical renderer.
export COMPOSE_FILE="compose.yaml:compose.production.yaml"

lock_file=${DEPLOY_LOCK_FILE:-/tmp/digital-bast-deploy.lock}
exec 9>"$lock_file"
flock -n 9 || die "another deployment is running" 75

# reverse-proxy runs as a fixed, non-root, non-"debian" uid (101:101,
# hardened: read_only + cap_drop ALL) and bind-mounts these two files
# read-only. A file that lands here without "other" read (e.g. a manual
# scp/rsync inheriting a restrictive umask, or a backup restore) means
# nginx can open() the config on first read but silently keeps working
# off that open fd forever -- the break only surfaces on the *next*
# container start (a host reboot, a redeploy), by which point it looks
# unrelated to whatever actually wrote the bad permissions. Enforce this
# on every deploy so it can never regress silently again.
if [ -d config/nginx ]; then
    chmod o+x config config/nginx 2>/dev/null || true
    for f in config/nginx/nginx.conf config/nginx/active-slot.conf; do
        [ -f "$f" ] && chmod o+r "$f"
    done
fi

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
        compose stop "web-$target" >/dev/null 2>&1 || true
    fi
}
trap cleanup_failed_target EXIT HUP INT TERM
switched=0

app_image=${APP_IMAGE:-digital-bast:local}
worker_image=${BOT_WORKER_IMAGE:-digital-bast-bot-worker:local}
previous_worker_image=""
if [ "$DRY_RUN" = "0" ]; then
    worker_container=$(compose ps -q bot-worker 2>/dev/null || true)
    if [ -n "$worker_container" ]; then
        previous_worker_image=$(docker inspect --format '{{.Image}}' "$worker_container" 2>/dev/null || true)
    fi
fi

if docker image inspect "$app_image" >/dev/null 2>&1; then
    printf '%s\n' "using local app image: $app_image"
    run compose pull postgres redis reverse-proxy
else
    run compose pull "web-$target" worker runner postgres redis prefect-server prefect-services reverse-proxy
fi

# bot-worker extends the exact application image selected for this release
# and holds no WhatsApp session state of its own (wa-session does, and is
# deliberately never touched here -- see scripts/deploy-wa-session.sh).
# Build it before recreating so an image-build failure can't take the
# chatbot offline mid-deploy.
run compose build bot-worker
run compose up -d postgres redis prefect-server prefect-services reverse-proxy
run compose up -d --no-deps "web-$target"

rollback_worker() {
    [ -n "$previous_worker_image" ] || return 1
    docker image inspect "$previous_worker_image" >/dev/null 2>&1 || return 1
    docker tag "$previous_worker_image" "$worker_image" || return 1
    compose up -d --no-deps --force-recreate bot-worker || return 1
    return 0
}

wait_for_shadow_readiness() {
    shadow_url="http://web-$target:8000${SHADOW_PATH:-/health/ready}"
    elapsed=0
    while ! compose exec -T reverse-proxy wget -q -O /dev/null "$shadow_url"; do
        if [ "$elapsed" -ge "$timeout_seconds" ]; then
            printf '%s\n' "shadow readiness did not recover within ${timeout_seconds}s: $shadow_url" >&2
            # Emit one final HTTP exchange for diagnosis without weakening the
            # gate. This contains status/response only; application secrets are
            # never printed by the readiness endpoint.
            compose exec -T reverse-proxy wget -S -O - "$shadow_url" 2>&1 || true
            die "target slot failed shadow gate" 1
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
}

if [ "$DRY_RUN" = "0" ]; then
    timeout_seconds=${HEALTH_TIMEOUT_SECONDS:-180}
    elapsed=0
    until [ "$(docker inspect --format '{{.State.Health.Status}}' "$(compose ps -q "web-$target")" 2>/dev/null || true)" = "healthy" ]; do
        [ "$elapsed" -lt "$timeout_seconds" ] || die "target slot failed health gate" 1
        sleep 5
        elapsed=$((elapsed + 5))
    done
    # Migration runs BEFORE the shadow gate, not after. /health/ready asserts
    # the app's schema is present, so gating readiness ahead of the migration
    # that creates it can never pass for a release that adds a table -- the
    # gate would be testing the new image against the old schema. Both gates
    # still run before any traffic moves: a failure here leaves the active
    # slot serving exactly as it was.
    compose run --rm --no-deps "web-$target" alembic upgrade head || die "migration gate failed; active slot preserved" 1
    # Readiness depends on Postgres, Redis, and the NocoDB authentication DB.
    # A single request immediately after a stack recreate can race a dependency
    # reconnect even when the candidate itself is healthy. Poll the shadow slot
    # for the same bounded health timeout; traffic is still on the current slot
    # throughout this loop, and a persistent failure still aborts the rollout.
    wait_for_shadow_readiness

    # Only replace bot-worker after the candidate web + schema passed. It
    # holds no WhatsApp session state (wa-session does, and is untouched
    # here) -- the HTTP health check just proves the new Node process and
    # packaged CLI actually started.
    compose up -d --no-deps --force-recreate bot-worker
    elapsed=0
    while [ "$(docker inspect --format '{{.State.Health.Status}}' "$(compose ps -q bot-worker)" 2>/dev/null || true)" != "healthy" ]; do
        if [ "$elapsed" -ge "$timeout_seconds" ]; then
            if rollback_worker; then
                die "bot-worker failed health gate; previous image restored; active web slot preserved" 1
            fi
            die "bot-worker failed health gate and its rollback also failed; active web slot preserved" 1
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done

    sed "s/web-$current:8000/web-$target:8000/" "$active_config" > "$active_config.next"
    dd if="$active_config.next" of="$active_config" conv=notrunc status=none
    truncate -s "$(wc -c < "$active_config.next")" "$active_config"
    rm -f "$active_config.next"
    compose exec -T reverse-proxy nginx -t || {
        sed "s/web-$target:8000/web-$current:8000/" "$active_config" > "$active_config.next"
        dd if="$active_config.next" of="$active_config" conv=notrunc status=none
        truncate -s "$(wc -c < "$active_config.next")" "$active_config"
        rm -f "$active_config.next"
        rollback_worker >/dev/null 2>&1 || true
        die "proxy configuration gate failed; active slot and previous bot-worker image preserved" 1
    }
    compose exec -T reverse-proxy nginx -s reload
    switched=1
    compose exec -T reverse-proxy wget -q -O /dev/null "http://127.0.0.1:8080${PUBLIC_HEALTH_PATH:-/health/ready}" || {
        sed "s/web-$target:8000/web-$current:8000/" "$active_config" > "$active_config.next"
        dd if="$active_config.next" of="$active_config" conv=notrunc status=none
        truncate -s "$(wc -c < "$active_config.next")" "$active_config"
        rm -f "$active_config.next"
        compose exec -T reverse-proxy nginx -s reload
        rollback_worker >/dev/null 2>&1 || true
        switched=0
        die "public health gate failed; proxy and bot-worker rolled back" 1
    }
    compose up -d --no-deps worker runner
else
    printf '%s\n' "DRY-RUN health web-$target"
    printf '%s\n' "DRY-RUN shadow web-$target"
    printf '%s\n' "DRY-RUN migration alembic upgrade head"
    printf '%s\n' "DRY-RUN restart + health bot-worker (restore previous image on failure)"
    printf '%s\n' "DRY-RUN switch $current to $target"
    printf '%s\n' "DRY-RUN public health and rollback web + bot-worker on failure"
    printf '%s\n' "DRY-RUN restart worker runner"
fi

trap - EXIT HUP INT TERM
printf '%s\n' "deployment complete: $target"
