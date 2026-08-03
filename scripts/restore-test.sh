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
require_command age
[ -n "${BACKUP_FILE:-}" ] || die "BACKUP_FILE is required" 78
[ -n "${BACKUP_DATABASE:-}" ] || die "BACKUP_DATABASE is required" 78
[ -n "${AGE_IDENTITY_FILE:-}" ] || die "AGE_IDENTITY_FILE is required" 78
case "$BACKUP_DATABASE" in
    digital_bast_app|digital_bast_prefect) ;;
    *) die "BACKUP_DATABASE must be digital_bast_app or digital_bast_prefect" 64 ;;
esac
case "$(basename "$BACKUP_FILE")" in
    "postgres-$BACKUP_DATABASE-"*.dump.age) ;;
    *) die "BACKUP_FILE name does not match BACKUP_DATABASE" 64 ;;
esac
require_file "$BACKUP_FILE"
require_file "$AGE_IDENTITY_FILE"

if [ "$DRY_RUN" = "1" ]; then
    printf '%s\n' "DRY-RUN decrypt backup without persisting plaintext"
    printf '%s\n' "DRY-RUN restore into isolated temporary database"
    printf '%s\n' "DRY-RUN validate restored schema and drop temporary database"
    exit 0
fi

test_database="restore_test_${BACKUP_DATABASE}_$(date -u +%Y%m%d%H%M%S)_$$"
cleanup() {
    docker compose exec -T postgres dropdb -U "${POSTGRES_USER:-digital_bast}" --if-exists "$test_database" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM
docker compose exec -T postgres createdb -U "${POSTGRES_USER:-digital_bast}" "$test_database"
age --decrypt --identity "$AGE_IDENTITY_FILE" "$BACKUP_FILE" | docker compose exec -T postgres pg_restore -U "${POSTGRES_USER:-digital_bast}" -d "$test_database" --exit-on-error
table_count=$(docker compose exec -T postgres psql -U "${POSTGRES_USER:-digital_bast}" -d "$test_database" -Atc "select count(*) from pg_catalog.pg_tables where schemaname = 'public'")
[ "$table_count" -gt 0 ] || die "restored database contains no public tables" 1
cleanup
trap - EXIT HUP INT TERM
printf '%s\n' "restore test passed"
