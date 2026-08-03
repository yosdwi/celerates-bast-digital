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
if [ "$DRY_RUN" = "1" ]; then
    printf '%s\n' "DRY-RUN delete NocoDB audit snapshots older than 30 days"
    printf '%s\n' "DRY-RUN delete generation_plans older than 30 days"
    exit 0
fi

docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-digital_bast}" -d "${POSTGRES_DB:-digital_bast}" <<'SQL'
begin;
delete from nocodb_audit_events where created_at < now() - interval '30 days';
delete from generation_plans where created_at < now() - interval '30 days';
commit;
SQL
printf '%s\n' "retention complete"
