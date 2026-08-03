#!/bin/sh
set -eu

WEB_URL=${WEB_URL:-http://127.0.0.1:8080}
PREFECT_URL=${PREFECT_URL:-http://127.0.0.1:4200}
curl --fail --silent --show-error --max-time 10 "$WEB_URL/health" >/dev/null
curl --fail --silent --show-error --max-time 10 "$PREFECT_URL/api/health" >/dev/null
printf '%s\n' "smoke passed"
