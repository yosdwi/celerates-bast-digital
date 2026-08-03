#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$PROJECT_DIR"

temporary_dir=$(mktemp -d)
trap 'rm -rf "$temporary_dir"' EXIT HUP INT TERM
fake_bin="$temporary_dir/bin"
mkdir -p "$fake_bin" "$temporary_dir/backups"

cat >"$fake_bin/docker" <<'FAKE_DOCKER'
#!/bin/sh
set -eu
printf '%s\n' "$*" >>"$FAKE_DOCKER_LOG"
case "$*" in
    *' pg_dump '*) printf '%s\n' 'fake custom-format dump' ;;
    *' pg_restore '*) cat >/dev/null ;;
    *' psql '*) printf '%s\n' 1 ;;
esac
FAKE_DOCKER
chmod +x "$fake_bin/docker"

cat >"$fake_bin/age" <<'FAKE_AGE'
#!/bin/sh
set -eu
if [ "${1:-}" = --encrypt ]; then
    output=
    input=
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --output) output=$2; shift 2 ;;
            --recipient) shift 2 ;;
            --encrypt) shift ;;
            *) input=$1; shift ;;
        esac
    done
    cp "$input" "$output"
else
    eval "input=\${$#}"
    cat "$input"
fi
FAKE_AGE
chmod +x "$fake_bin/age"

cat >"$fake_bin/rclone" <<'FAKE_RCLONE'
#!/bin/sh
set -eu
exit 0
FAKE_RCLONE
chmod +x "$fake_bin/rclone"

FAKE_DOCKER_LOG="$temporary_dir/backup-docker.log" PATH="$fake_bin:$PATH" \
    AGE_RECIPIENT=age1test BACKUP_REMOTE=remote:test BACKUP_DIR="$temporary_dir/backups" \
    scripts/backup.sh >"$temporary_dir/backup.out"

grep -q 'pg_dump -U digital_bast -d digital_bast_app -Fc' "$temporary_dir/backup-docker.log"
grep -q 'pg_dump -U digital_bast -d digital_bast_prefect -Fc' "$temporary_dir/backup-docker.log"
[ "$(grep -c ' pg_dump ' "$temporary_dir/backup-docker.log")" -eq 2 ]
app_backup=$(find "$temporary_dir/backups" -name 'postgres-digital_bast_app-*.dump.age')
prefect_backup=$(find "$temporary_dir/backups" -name 'postgres-digital_bast_prefect-*.dump.age')
[ -s "$app_backup" ]
[ -s "$prefect_backup" ]

FAKE_DOCKER_LOG="$temporary_dir/restore-docker.log" PATH="$fake_bin:$PATH" \
    BACKUP_FILE="$app_backup" BACKUP_DATABASE=digital_bast_app \
    AGE_IDENTITY_FILE="$app_backup" scripts/restore-test.sh >"$temporary_dir/restore.out"

grep -q 'createdb -U digital_bast restore_test_digital_bast_app_' "$temporary_dir/restore-docker.log"
grep -q 'pg_restore -U digital_bast -d restore_test_digital_bast_app_.* --exit-on-error' "$temporary_dir/restore-docker.log"
grep -q 'psql -U digital_bast -d restore_test_digital_bast_app_' "$temporary_dir/restore-docker.log"

if FAKE_DOCKER_LOG="$temporary_dir/rejected.log" PATH="$fake_bin:$PATH" \
    BACKUP_FILE="$app_backup" BACKUP_DATABASE=digital_bast \
    AGE_IDENTITY_FILE="$app_backup" scripts/restore-test.sh >"$temporary_dir/rejected.out" 2>&1; then
    exit 1
fi
grep -q 'BACKUP_DATABASE must be digital_bast_app or digital_bast_prefect' "$temporary_dir/rejected.out"

printf '%s\n' "backup and restore checks passed"
