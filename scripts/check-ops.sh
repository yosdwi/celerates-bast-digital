#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_DIR"

for script in scripts/*.sh tests/ops/*.sh; do
    sh -n "$script"
done

# `docker compose config` only validates interpolation and structure here; it
# never starts services. Supply explicit non-secret CI placeholders for every
# production-required variable so the static gate does not depend on a local
# .env file or deployment secrets existing on the runner.
NOCODB_BASE_URL=https://invalid.local \
NOCODB_BASE_ID=ci-placeholder \
NOCODB_V2_DB_PASSWORD=ci-placeholder \
SECRETS_GID=${SECRETS_GID:-0} \
docker compose --profile blue --profile green config --quiet

if rg -n --glob 'Dockerfile' --glob 'compose*.yaml' --glob '.github/**' --glob 'scripts/**' '(BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|password\s*[:=]\s*[[:alnum:]])' .; then
    printf '%s\n' "possible embedded secret detected" >&2
    exit 1
fi

grep -q '^USER 10001:10001$' Dockerfile
grep -q 'read_only: true' compose.yaml
grep -q 'no-new-privileges:true' compose.yaml
grep -q 'internal: true' compose.yaml
grep -q 'flock -n' scripts/deploy.sh
grep -q 'migration gate failed; active slot preserved' scripts/deploy.sh
grep -q 'proxy and bot-worker rolled back' scripts/deploy.sh
grep -q 'compose build bot-worker' scripts/deploy.sh
grep -q 'bot-worker failed health gate; previous image restored' scripts/deploy.sh
grep -q 'rollback_worker' scripts/deploy.sh
grep -q 'wa-session/outbound.js' wa-session/Dockerfile
grep -q 'flock -n' scripts/deploy-wa-session.sh
# wa-session must never be touched by the automated blue/green flow -- that
# coupling is exactly what caused WhatsApp to revoke the session in the
# first place. Keep this a standing guard against it regressing silently.
! grep -q 'wa-session' scripts/deploy.sh
printf '%s\n' "operations static checks passed"
