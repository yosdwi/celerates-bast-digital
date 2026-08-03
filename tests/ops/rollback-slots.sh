#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$PROJECT_DIR"

temporary_dir=$(mktemp -d)
trap 'rm -rf "$temporary_dir"' EXIT HUP INT TERM
fake_bin="$temporary_dir/bin"
mkdir -p "$fake_bin"

cat >"$fake_bin/docker" <<'FAKE_DOCKER'
#!/bin/sh
set -eu
printf '%s\n' "$*" >>"$FAKE_DOCKER_LOG"
if [ "${1:-}" = inspect ]; then
    printf '%s\n' healthy
elif [ "${1:-}" = compose ] && [ "${2:-}" = ps ]; then
    printf '%s\n' fake-container-id
fi
FAKE_DOCKER
chmod +x "$fake_bin/docker"

run_deploy_copy="$temporary_dir/deploy-copy"
mkdir -p "$run_deploy_copy"
cp -R scripts config "$run_deploy_copy/"
deploy_log="$temporary_dir/deploy.log"
PATH="$fake_bin:$PATH" FAKE_DOCKER_LOG="$deploy_log" DEPLOY_LOCK_FILE="$temporary_dir/deploy.lock" \
    APP_IMAGE="registry.example/digital-bast@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" \
    "$run_deploy_copy/scripts/deploy.sh" --skip-preflight >"$temporary_dir/deploy.out"
! grep -Eq '(^| )stop web-blue worker-blue runner-blue( |$)' "$deploy_log"
grep -q 'up -d --no-deps worker-green runner-green' "$deploy_log"
grep -q 'deployment complete: green' "$temporary_dir/deploy.out"

run_rollback_copy="$temporary_dir/rollback-copy"
mkdir -p "$run_rollback_copy"
cp -R scripts config "$run_rollback_copy/"
sed -i 's/web-blue:8000/web-green:8000/' "$run_rollback_copy/config/nginx/active-slot.conf"
rollback_log="$temporary_dir/rollback.log"
PATH="$fake_bin:$PATH" FAKE_DOCKER_LOG="$rollback_log" DEPLOY_LOCK_FILE="$temporary_dir/rollback.lock" \
    "$run_rollback_copy/scripts/rollback.sh" >"$temporary_dir/rollback.out"
grep -Eq '(^| )stop web-green worker-green runner-green( |$)' "$rollback_log"
grep -q 'rollback complete: blue' "$temporary_dir/rollback.out"

printf '%s\n' "rollback slot checks passed"
