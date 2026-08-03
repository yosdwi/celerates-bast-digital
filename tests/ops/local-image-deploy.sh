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
if [ "${1:-}" = image ] && [ "${2:-}" = inspect ]; then
    [ "${FAKE_LOCAL_IMAGE:-0}" = 1 ]
elif [ "${1:-}" = inspect ]; then
    printf '%s\n' healthy
elif [ "${1:-}" = compose ] && [ "${2:-}" = ps ]; then
    printf '%s\n' fake-container-id
fi
FAKE_DOCKER
chmod +x "$fake_bin/docker"

project_copy="$temporary_dir/project"
mkdir -p "$project_copy"
cp -R scripts config "$project_copy/"

local_log="$temporary_dir/local.log"
PATH="$fake_bin:$PATH" FAKE_LOCAL_IMAGE=1 FAKE_DOCKER_LOG="$local_log" \
    APP_IMAGE=digital-bast:local DEPLOY_LOCK_FILE="$temporary_dir/local.lock" \
    "$project_copy/scripts/deploy.sh" --skip-preflight >"$temporary_dir/local.out"
grep -q 'using local app image: digital-bast:local' "$temporary_dir/local.out"
! grep -Eq ' pull .*web-green| pull .*worker-green| pull .*runner-green' "$local_log"
grep -q 'pull postgres redis reverse-proxy' "$local_log"
! grep -q 'prefect-server' "$local_log"
! grep -q 'prefect-services' "$local_log"

registry_copy="$temporary_dir/registry-project"
mkdir -p "$registry_copy"
cp -R scripts config "$registry_copy/"
registry_log="$temporary_dir/registry.log"
PATH="$fake_bin:$PATH" FAKE_LOCAL_IMAGE=0 FAKE_DOCKER_LOG="$registry_log" \
    APP_IMAGE=digital-bast:missing DEPLOY_LOCK_FILE="$temporary_dir/registry.lock" \
    "$registry_copy/scripts/deploy.sh" --skip-preflight >"$temporary_dir/registry.out"
grep -Eq ' pull .*web-green.*worker-green.*runner-green' "$registry_log"
grep -q 'prefect-server' "$registry_log"
grep -q 'prefect-services' "$registry_log"

printf '%s\n' "local-image deploy checks passed"
