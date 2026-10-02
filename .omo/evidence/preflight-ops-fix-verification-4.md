# Local-image pull semantics follow-up

Verification run: 2026-08-03
Scope: `scripts/deploy.sh` and `tests/ops/local-image-deploy.sh` only, plus required gates.

## Commands and raw output

```text
$ timeout 15s bash -n scripts/*.sh tests/ops/*.sh
$ timeout 15s tests/ops/local-image-deploy.sh
local-image deploy checks passed
$ timeout 15s tests/ops/rollback-slots.sh
rollback slot checks passed
$ timeout 15s env SECRETS_GID=$(id -g) NOCODB_BASE_URL=https://invalid.local scripts/check-ops.sh
operations static checks passed
```

## Pull decision evidence

```text
scripts/deploy.sh:56:if docker image inspect "$app_image" >/dev/null 2>&1; then
scripts/deploy.sh:58:    run compose pull postgres redis reverse-proxy
scripts/deploy.sh:60:    run compose pull "web-$target" "worker-$target" "runner-$target" postgres redis prefect-server prefect-services reverse-proxy
```

The local-image test now asserts no `prefect-server` or `prefect-services` pull, while the registry-image branch asserts both are pulled. This prevents Prefect services, which inherit the app image, from attempting to pull a nonexistent local tag.

DoneClaim: local-image and registry-image pull semantics are fixed and independently verified.
