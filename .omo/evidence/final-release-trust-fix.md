# Final release trust fix

## Scope and source state

- Owned changes: `.github/workflows/release.yml`, `scripts/deploy.sh`, `tests/ops/local-image-deploy.sh`, `tests/ops/release-trust.sh`, and `docs/deployment-and-rollback.md`.
- Pre-existing shared worktree changes were preserved. The final status still contains unrelated staged and unstaged work outside this scope.

## Red

### Mutable local image silently suppressed the registry pull

- Scenario: a fake Docker daemon reported an image already present while deployment used the old implicit-local path.
- Invocation: `sh -x tests/ops/local-image-deploy.sh` after adding the regression assertions and before the deploy fix.
- Binary observable: exit `1`; the final trace reached `grep -Eq ' pull .*web-green.*worker-green.*runner-green'` after the old script emitted `using local app image`, proving no app-service pull was logged.
- Captured artifact: this receipt, `Red` section; transient full trace was `/tmp/release-trust-red-xtrace.out`.

### Workflow did not bind deployment to the build digest or staged release assets

- Scenario: static assertions for a digest output reference, all release-SHA checkouts, and `git archive "$RELEASE_SHA"` were added before the workflow fix.
- Invocation: `sh tests/ops/release-trust.sh` before the workflow fix.
- Binary observable: exit `1` because the prior workflow only used a mutable `${IMAGE}` tag and had no archive/staging step.
- Captured artifact: this receipt, `Red` section; transient command output was `/tmp/release-trust-red-workflow.out`.

## Green

### Digest deployment and local-image boundary

- Scenario: fake Docker reports an image present, but a `ghcr.io/...@sha256:<64 hex>` app image must still pull all inactive-slot services; a local `digital-bast:local` image can skip those pulls only with `ALLOW_LOCAL_APP_IMAGE=1`; a mutable registry tag must fail closed.
- Invocation: `sh tests/ops/local-image-deploy.sh`.
- Binary observable: exit `0`, stdout `local-image deploy checks passed`; the harness asserts `compose pull --policy always` reaches web/worker/runner, local mode emits its message only with opt-in, and a mutable tag emits `APP_IMAGE must be an immutable digest reference`.
- Captured artifact: this receipt, `Green` section.

### CI digest and exact commit deployment assets

- Scenario: both deployment jobs must check out `RELEASE_SHA`, build `RELEASE_IMAGE` from `needs.publish.outputs.digest`, archive exactly `compose.yaml`, `scripts`, and `config/nginx/nginx.conf`, then invoke the staged script without transferring `.env`, `secrets`, or the host active-slot state.
- Invocation: `sh tests/ops/release-trust.sh`.
- Binary observable: exit `0`, stdout `release trust checks passed`; static assertions verify the digest binding, all three exact-SHA checkouts, archive command, escaped transfer variables, staged deploy entry point, immutable-digest rejection, forced pull policy, and post-pull inspect.
- Captured artifact: this receipt, `Green` section.

### Syntax, workflow parsing, and operations gate

- Scenario: changed shell scripts parse, the release workflow parses as YAML, and operations static checks work with a non-secret environment.
- Invocation: `sh -n scripts/deploy.sh tests/ops/local-image-deploy.sh tests/ops/release-trust.sh && python3 -c 'import yaml, pathlib; yaml.safe_load(pathlib.Path(".github/workflows/release.yml").read_text()); print("release workflow YAML parsed")' && SECRETS_GID=10001 scripts/check-ops.sh`.
- Binary observable: exit `0`, outputs `release workflow YAML parsed` and `operations static checks passed`.
- Captured artifact: this receipt, `Green` section.

## Cleanup

- Removed the temporary debugging journal and its local Git exclude entry.
- No service, credential, SSH host, or Docker state was changed during verification; fake-Docker fixtures were created under `mktemp` and removed by their test traps.
- `git diff --check` exited `0` after the final changes. Existing shared-worktree edits remain untouched.

DoneClaim: CI release deployment is bound to the build-push digest and exact `RELEASE_SHA` assets; immutable registry pulls are enforced, and direct local images require explicit opt-in.

## Stop-hook direct verification (2026-08-03)

Invocation:

```sh
sh -n scripts/deploy.sh tests/ops/local-image-deploy.sh tests/ops/release-trust.sh
sh tests/ops/local-image-deploy.sh
sh tests/ops/release-trust.sh
python3 -c 'import yaml, pathlib; yaml.safe_load(pathlib.Path(".github/workflows/release.yml").read_text()); print("release workflow YAML parsed")'
SECRETS_GID=10001 scripts/check-ops.sh
git diff --check
```

Observed output:

```text
shell syntax: PASS
local-image deploy checks passed
release trust checks passed
release workflow YAML parsed
operations static checks passed
git diff --check: PASS
```

Static source observations from the same direct run:

```text
scripts/deploy.sh:56: explicit ALLOW_LOCAL_APP_IMAGE gate
scripts/deploy.sh:67: compose pull --policy always for app services
.github/workflows/release.yml:81,142: git archive from RELEASE_SHA
.github/workflows/release.yml:87,148: RELEASE_IMAGE uses needs.publish.outputs.digest
```

## Stop-hook final independent rerun (2026-08-03)

Invocation:

```sh
sh -n scripts/deploy.sh tests/ops/local-image-deploy.sh tests/ops/release-trust.sh
sh tests/ops/local-image-deploy.sh
sh tests/ops/release-trust.sh
python3 -c 'import yaml, pathlib; yaml.safe_load(pathlib.Path(".github/workflows/release.yml").read_text()); print("release workflow YAML parsed")'
SECRETS_GID=10001 scripts/check-ops.sh
git diff --check
```

Observed output (process exit `0`):

```text
local-image deploy checks passed
release trust checks passed
release workflow YAML parsed
operations static checks passed
FINAL_RERUN_PASS
```

Judgment: all requested targeted behavior, syntax, YAML parsing, and safe-environment operations checks remain green after the evidence receipt update.

## Stop-hook third direct verification (2026-08-03)

Invocation:

```sh
sh -n scripts/deploy.sh tests/ops/local-image-deploy.sh tests/ops/release-trust.sh
sh tests/ops/local-image-deploy.sh
sh tests/ops/release-trust.sh
python3 -c 'import yaml, pathlib; yaml.safe_load(pathlib.Path(".github/workflows/release.yml").read_text()); print("release workflow YAML parsed")'
SECRETS_GID=10001 scripts/check-ops.sh
git diff --check
```

Observed output (process exit `0`):

```text
local-image deploy checks passed
release trust checks passed
release workflow YAML parsed
operations static checks passed
THIRD_DIRECT_VERIFICATION_PASS
```

Judgment: the third independent execution confirms the artifact remains green; no failed criterion requires correction.
