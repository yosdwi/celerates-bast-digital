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
require_command rclone
[ -n "${AGE_RECIPIENT:-}" ] || die "AGE_RECIPIENT is required" 78
[ -n "${BACKUP_REMOTE:-}" ] || die "BACKUP_REMOTE is required" 78

backup_dir=${BACKUP_DIR:-./backups}
stamp=$(date -u +%Y%m%dT%H%M%SZ)

if [ "$DRY_RUN" = "1" ]; then
    for database in digital_bast_app digital_bast_prefect; do
        printf '%s\n' "DRY-RUN create encrypted PostgreSQL backup for $database"
        printf '%s\n' "DRY-RUN verify $database encrypted backup is non-empty"
        printf '%s\n' "DRY-RUN copy $database encrypted backup off-host"
        printf '%s\n' "DRY-RUN retain seven off-host daily backups and local latest for $database"
    done
    exit 0
fi

umask 077
mkdir -p "$backup_dir"
for database in digital_bast_app digital_bast_prefect; do
    plain="$backup_dir/postgres-$database-$stamp.dump"
    encrypted="$plain.age"
    trap 'rm -f "$plain" "$encrypted.next"' EXIT HUP INT TERM
    docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-digital_bast}" -d "$database" -Fc > "$plain"
    [ -s "$plain" ] || die "$database dump is empty" 1
    age --encrypt --recipient "$AGE_RECIPIENT" --output "$encrypted.next" "$plain"
    [ -s "$encrypted.next" ] || die "$database encrypted backup is empty" 1
    mv "$encrypted.next" "$encrypted"
    rm -f "$plain"
    rclone copyto "$encrypted" "$BACKUP_REMOTE/$(basename "$encrypted")" --checksum
    rclone check "$encrypted" "$BACKUP_REMOTE/$(basename "$encrypted")" --one-way
    find "$backup_dir" -maxdepth 1 -type f -name "postgres-$database-*.dump.age" ! -path "$encrypted" -delete
    rclone delete "$BACKUP_REMOTE" --include "postgres-$database-*.dump.age" --min-age 8d
    printf '%s\n' "$encrypted"
done
trap - EXIT HUP INT TERM
