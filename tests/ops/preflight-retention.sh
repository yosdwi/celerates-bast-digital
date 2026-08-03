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
if [ "${1:-}" = compose ] && [ "${2:-}" = exec ]; then
    cat >"$FAKE_PSQL_INPUT"
fi
exit 0
FAKE_DOCKER
chmod +x "$fake_bin/docker"

cat >"$fake_bin/df" <<'FAKE_DF'
#!/bin/sh
set -eu
case "${FAKE_DF_FREE_GB:-22}" in
    22) free_kb=23068672 ;;
    19) free_kb=19922944 ;;
    *) printf '%s\n' "unsupported fake free-space value" >&2; exit 2 ;;
esac
printf '%s\n' "Filesystem 1024-blocks Used Available Capacity Mounted on"
printf '/dev/fake 78643200 %s %s 71%% /\n' "$((78643200 - free_kb))" "$free_kb"
FAKE_DF
chmod +x "$fake_bin/df"

if PATH="$fake_bin:$PATH" FAKE_DF_FREE_GB=22 SECRETS_GID=0 SECRETS_DIR="$temporary_dir/missing" \
    scripts/preflight.sh --dry-run >"$temporary_dir/preflight-75-22.log" 2>&1; then
    exit 1
fi
grep -q 'required file unavailable' "$temporary_dir/preflight-75-22.log"
! grep -q 'root disk must be expanded' "$temporary_dir/preflight-75-22.log"

if PATH="$fake_bin:$PATH" FAKE_DF_FREE_GB=19 SECRETS_GID=0 SECRETS_DIR="$temporary_dir/missing" \
    scripts/preflight.sh --dry-run >"$temporary_dir/preflight-75-19.log" 2>&1; then
    exit 1
fi
grep -q 'root disk has less than 20GB available' "$temporary_dir/preflight-75-19.log"

FAKE_PSQL_INPUT="$temporary_dir/retention.sql" PATH="$fake_bin:$PATH" \
    scripts/retention.sh >"$temporary_dir/retention.log"
grep -q "delete from generation_plans where created_at < now() - interval '30 days';" "$temporary_dir/retention.sql"
! grep -q 'generated_plans' "$temporary_dir/retention.sql"

PATH="$fake_bin:$PATH" scripts/check-ops.sh >"$temporary_dir/check-ops.log"
grep -q 'operations static checks passed' "$temporary_dir/check-ops.log"

printf '%s\n' "preflight and retention checks passed"
