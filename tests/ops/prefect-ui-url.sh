#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$PROJECT_DIR"

render() {
    SECRETS_GID=$(id -g) \
        NOCODB_BASE_URL=https://invalid.local \
        PREFECT_SERVER_UI_API_URL="$1" \
        docker compose --profile blue config --format json
}

count_services() {
    python3 -c 'import json, sys; expected = sys.argv[1]; config = json.load(sys.stdin); print(sum(service.get("environment", {}).get("PREFECT_SERVER_UI_API_URL") == expected for service in config["services"].values()))' "$1"
}

public_url=https://prefect.example.com/api
public_count=$(render "$public_url" | count_services "$public_url")
[ "$public_count" -eq 2 ]

local_url=http://127.0.0.1:4200/api
local_count=$(env -u PREFECT_SERVER_UI_API_URL \
    SECRETS_GID=$(id -g) NOCODB_BASE_URL=https://invalid.local \
    docker compose --profile blue config --format json |
    count_services "$local_url")
[ "$local_count" -eq 2 ]

printf '%s\n' "Prefect UI API URL checks passed"
