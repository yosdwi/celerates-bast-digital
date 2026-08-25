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
grep -q 'proxy rolled back' scripts/deploy.sh
grep -q 'compose build bot-bridge' scripts/deploy.sh
grep -q 'bot bridge failed health gate' scripts/deploy.sh
grep -q 'bot-bridge/outbound.js' bot-bridge/Dockerfile
printf '%s\n' "operations static checks passed"
