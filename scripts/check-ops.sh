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
META_GRAPH_VERSION=v26.0 \
META_WA_PHONE_NUMBER_ID=ci-placeholder \
SECRETS_GID=${SECRETS_GID:-0} \
docker compose --profile blue --profile green config --quiet

if rg -n --glob 'Dockerfile' --glob 'compose*.yaml' --glob '.github/**' --glob 'scripts/**' "(BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|password\\s*[:=]\\s*['\"][[:alnum:]]{8})" .; then
    printf '%s\n' "possible embedded secret detected" >&2
    exit 1
fi

grep -q '^USER 10001:10001$' Dockerfile
grep -q 'read_only: true' compose.yaml
grep -q 'no-new-privileges:true' compose.yaml
grep -q 'internal: true' compose.yaml
grep -q 'flock -n' scripts/deploy.sh
grep -q 'migration gate failed; active slot preserved' scripts/deploy.sh
grep -q 'proxy and messaging services rolled back' scripts/deploy.sh
grep -q 'compose build bot-worker' scripts/deploy.sh
grep -q 'compose pull meta-wa-gateway' scripts/deploy.sh
grep -q 'bot-worker failed health gate; previous image restored' scripts/deploy.sh
grep -q 'rollback_worker' scripts/deploy.sh
grep -q 'rollback_gateway' scripts/deploy.sh
grep -q 'com.docker.compose.service=wa-session' scripts/deploy.sh
grep -q 'meta_wa_access_token meta_app_secret meta_webhook_verify_token' scripts/preflight.sh
grep -q 'disable the legacy digital-bast-whatsmeow.service' scripts/preflight.sh
grep -q '^USER 10001:10001$' meta-wa-gateway/Dockerfile
grep -q '/webhooks/whatsapp' config/nginx/active-slot.conf.template
! rg -n 'whatsmeow|@whiskeysockets/baileys|BOT_AUTH_DIR' \
    compose.yaml .github/workflows meta-wa-gateway
printf '%s\n' "operations static checks passed"
