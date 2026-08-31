#!/bin/sh
set -eu

# Stage the whatsmeow transport binary and a candidate systemd unit WITHOUT
# touching the currently-running WhatsApp transport. This script deliberately
# does not call systemctl daemon-reload/start/stop/restart/enable and does not
# read, move or delete the existing Baileys auth directory.
#
# Run as a user that may write the selected destination, or override PREFIX and
# SYSTEMD_CANDIDATE_DIR to writable staging paths. The actual production unit
# name/paths must be confirmed from the VPS before cutover.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PREFIX=${PREFIX:-/opt/digital-bast-whatsmeow/staged}
SYSTEMD_CANDIDATE_DIR=${SYSTEMD_CANDIDATE_DIR:-/etc/systemd/system}
GO_BIN=${GO_BIN:-go}

command -v "$GO_BIN" >/dev/null 2>&1 || {
    printf '%s\n' "go toolchain is required" >&2
    exit 69
}

build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT INT TERM

printf '%s\n' "Building whatsmeow transport..."
(
    cd "$PROJECT_DIR/whatsmeow-session"
    "$GO_BIN" test ./...
    CGO_ENABLED=1 "$GO_BIN" build -trimpath -o "$build_dir/digital-bast-whatsmeow" .
)

install -d -m 0755 "$PREFIX"
install -m 0755 "$build_dir/digital-bast-whatsmeow" "$PREFIX/digital-bast-whatsmeow"

candidate="$SYSTEMD_CANDIDATE_DIR/digital-bast-whatsmeow.service.candidate"
install -m 0644 "$PROJECT_DIR/ops/systemd/digital-bast-whatsmeow.service.example" "$candidate"

cat <<EOF
Whatsmeow transport staged only.

Binary:
  $PREFIX/digital-bast-whatsmeow

Candidate unit (NOT loaded by systemd):
  $candidate

No existing WhatsApp process, session, auth directory, Docker service, or
systemd unit was stopped/restarted/removed.

Before cutover, audit the VPS and resolve the real values for:
  - existing Baileys systemd unit name + ExecStart
  - BOT_WORKER_BASE_URL
  - BOT_AUTH_DIR (use a NEW persistent directory for whatsmeow)
  - BOT_DATA_DIR
  - token file + allowed groups
  - port 8090 ownership

Then stop the old transport ONCE before starting/pairing whatsmeow. Never run
both against the same WhatsApp account during the cutover.
EOF
