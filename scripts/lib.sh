#!/bin/sh
set -eu

die() {
    printf '%s\n' "$1" >&2
    exit "${2:-1}"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command unavailable: $1" 69
}

require_file() {
    [ -f "$1" ] || die "required file unavailable: $1" 78
    [ -s "$1" ] || die "required file is empty: $1" 78
}

run() {
    if [ "${DRY_RUN:-0}" = "1" ]; then
        printf 'DRY-RUN'
        for argument in "$@"; do
            printf ' %s' "$argument"
        done
        printf '\n'
        return 0
    fi
    "$@"
}
