#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$PROJECT_DIR"

temporary_dir=$(mktemp -d)
trap 'rm -rf "$temporary_dir"' EXIT HUP INT TERM

if SECRETS_DIR="$temporary_dir" SECRETS_GID=0 AVAILABLE_MIN_GB=0 scripts/preflight.sh --dry-run >"$temporary_dir/missing.log" 2>&1; then
    exit 1
fi
grep -q 'required file unavailable' "$temporary_dir/missing.log"

DEPLOY_LOCK_FILE="$temporary_dir/deploy.lock"
export DEPLOY_LOCK_FILE
(
    exec 8>"$DEPLOY_LOCK_FILE"
    flock 8
    sleep 5
) &
locker=$!
sleep 1
if scripts/rollback.sh --dry-run >"$temporary_dir/lock.log" 2>&1; then
    kill "$locker" 2>/dev/null || true
    exit 1
fi
wait "$locker"
grep -q 'another deployment is running' "$temporary_dir/lock.log"

grep -q 'target slot failed health gate' scripts/deploy.sh
grep -q 'migration gate failed; active slot preserved' scripts/deploy.sh
grep -q 'restored database contains no public tables' scripts/restore-test.sh
printf '%s\n' "adversarial checks passed"
