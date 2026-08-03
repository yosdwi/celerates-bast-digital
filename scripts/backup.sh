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
plain="$backup_dir/postgres-$stamp.dump"
encrypted="$plain.age"

if [ "$DRY_RUN" = "1" ]; then
    printf '%s\n' "DRY-RUN create encrypted PostgreSQL backup"
    printf '%s\n' "DRY-RUN verify encrypted backup is non-empty"
    printf '%s\n' "DRY-RUN copy encrypted backup off-host"
    printf '%s\n' "DRY-RUN retain seven off-host daily backups and local latest"
    exit 0
fi

umask 077
mkdir -p "$backup_dir"
trap 'rm -f "$plain"' EXIT HUP INT TERM
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-digital_bast}" -d "${POSTGRES_DB:-digital_bast}" -Fc > "$plain"
[ -s "$plain" ] || die "database dump is empty" 1
age --encrypt --recipient "$AGE_RECIPIENT" --output "$encrypted.next" "$plain"
[ -s "$encrypted.next" ] || die "encrypted backup is empty" 1
mv "$encrypted.next" "$encrypted"
rm -f "$plain"
rclone copyto "$encrypted" "$BACKUP_REMOTE/$(basename "$encrypted")" --checksum
rclone check "$encrypted" "$BACKUP_REMOTE/$(basename "$encrypted")" --one-way
find "$backup_dir" -maxdepth 1 -type f -name 'postgres-*.dump.age' ! -path "$encrypted" -delete
rclone delete "$BACKUP_REMOTE" --include 'postgres-*.dump.age' --min-age 8d
printf '%s\n' "$encrypted"
