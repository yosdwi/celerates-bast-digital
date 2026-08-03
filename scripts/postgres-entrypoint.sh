#!/bin/sh
set -eu

if [ ! -f "${PGDATA:-/var/lib/postgresql/data}/.digital-bast-initialized" ]; then
    install -d -o postgres -g postgres -m 0700 /dev/shm/digital-bast-init
    install -o postgres -g postgres -m 0400 \
        /run/secrets/app_database_password \
        /dev/shm/digital-bast-init/app_database_password
    install -o postgres -g postgres -m 0400 \
        /run/secrets/prefect_database_password \
        /dev/shm/digital-bast-init/prefect_database_password
fi

exec docker-entrypoint.sh "$@"
