#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$PROJECT_DIR"

workflow=.github/workflows/release.yml

! grep -Fq 'workflow_dispatch' "$workflow"
grep -Fq "if: github.event.workflow_run.conclusion == 'success'" "$workflow"
! grep -Fq 'github.sha' "$workflow"

archive_dir=$(mktemp -d)
trap 'rm -rf "$archive_dir"' EXIT HUP INT TERM
release_tree=$(git write-tree)
git archive --format=tar "$release_tree" -- scripts/deploy.sh | tar -xf - -C "$archive_dir"
[ "$(git ls-files -s scripts/deploy.sh | awk '{print $1}')" = 100755 ]
[ -x "$archive_dir/scripts/deploy.sh" ]

grep -Fq 'RELEASE_IMAGE: ghcr.io/${{ github.repository }}@${{ needs.publish.outputs.digest }}' "$workflow"
[ "$(grep -Fc 'ref: ${{ env.RELEASE_SHA }}' "$workflow")" -ge 3 ]
grep -Fq 'git archive --format=tar "$RELEASE_SHA" -- compose.yaml scripts config/nginx/nginx.conf > release-assets.tar' "$workflow"
grep -Fq 'RELEASE_SHA=$(printf' "$workflow"
grep -Fq 'APP_IMAGE=$(printf' "$workflow"
grep -Fq 'scripts/deploy.sh' "$workflow"
! grep -Fq "APP_IMAGE='\${IMAGE}' scripts/deploy.sh" "$workflow"

grep -Fq 'ALLOW_LOCAL_APP_IMAGE:-0' scripts/deploy.sh
grep -Fq 'APP_IMAGE must be an immutable digest reference' scripts/deploy.sh
grep -Fq 'compose pull --policy always' scripts/deploy.sh
grep -Fq 'docker image inspect "$app_image"' scripts/deploy.sh

printf '%s\n' 'release trust checks passed'
