# Preflight and operations fix evidence

DoneClaim: lean preflight disk policy, retention table naming, check-ops false-positive, rollback-ready slots, and direct local-image deploy behavior are fixed and verified.

## Red before fix

- Scenario: fake `df -Pk /` reported 75 GB total and 22 GB available; secrets directory was absent.
- Invocation: `tests/ops/preflight-retention.sh`
- Observable: exit 1 before the expected missing-secret prerequisite because `scripts/preflight.sh` rejected total capacity with the obsolete 150 GB gate.
- Artifact: `.omo/evidence/preflight-ops-red-before.txt` (captured failing-first result).

## Green regression checks

Invocation and binary observables:

```text
$ timeout 15s bash -n scripts/*.sh tests/ops/*.sh
syntax_exit=0
$ timeout 15s tests/ops/preflight-retention.sh
preflight and retention checks passed
preflight_retention_exit=0
$ timeout 15s tests/ops/adversarial.sh
adversarial checks passed
adversarial_exit=0
$ timeout 15s tests/ops/rollback-slots.sh
rollback slot checks passed
$ timeout 15s tests/ops/local-image-deploy.sh
local-image deploy checks passed
```

`tests/ops/preflight-retention.sh` uses controlled fake `df` values: 75 GB total / 22 GB free reaches the next missing-secret prerequisite (and emits no total-capacity error); 75 GB total / 19 GB free is rejected with the available-space status 70. The same test captures retention SQL through a fake `docker compose exec` and asserts `generation_plans` with no `generated_plans`.

## check-ops QA

- Scenario: safe local static check with Compose interpolation inputs and no containers started.
- Invocation: `timeout 15s env SECRETS_GID=$(id -g) NOCODB_BASE_URL=https://invalid.local scripts/check-ops.sh`
- Observable:

```text
operations static checks passed
check_ops_exit=0
```

- The prior false-positive source was `scripts/postgres-init.sh:8`; the narrowed scanner no longer matches its quoted shell variables.

## Rollback-ready slot QA

- Scenario: fake successful deploy with blue active slot, then fake rollback with green active slot.
- Invocation: `timeout 15s tests/ops/rollback-slots.sh`
- Observable: exit 0; deploy log contains no stop of `web-blue worker-blue runner-blue` after switching, and rollback log contains `stop web-green worker-green runner-green`.

## Direct local-image deploy QA

- Scenario: local `APP_IMAGE=digital-bast:local` exists versus absent registry image, with fake Docker and no containers.
- Invocation: `timeout 15s tests/ops/local-image-deploy.sh`
- Observable: exit 0; existing local image emits `using local app image` and skips app-service pull while infrastructure pull remains; absent image retains the app-service pull path.

## Adverse inputs and cleanup

- Malformed numeric threshold: `AVAILABLE_MIN_GB=not-a-number ... scripts/preflight.sh --dry-run` exits 2 with `Illegal number` (fail-closed).
- Stale state: retention runs against freshly generated SQL in the isolated fake-Compose harness; no persistent state or containers are created.
- Dirty worktree: baseline v2 files are untracked in this checkout; no unrelated files were reverted.
- Misleading output: preflight reports only the available-space policy; retention dry-run names `generation_plans`; check-ops reports success only after all static gates.
- Bounded commands: syntax/tests/check-ops were each wrapped in `timeout 15s` and completed; no long-running command or container remains.
- Remaining adverse classes: N/A because these shell checks do not expose network, browser, authentication, or concurrency surfaces beyond the existing deployment-lock assertion.

## Changed files

- `scripts/preflight.sh`
- `scripts/retention.sh`
- `scripts/check-ops.sh`
- `scripts/deploy.sh`
- `scripts/rollback.sh`
- `tests/ops/preflight-retention.sh`
- `tests/ops/adversarial.sh`
- `tests/ops/rollback-slots.sh`
- `tests/ops/local-image-deploy.sh`
- `docs/deployment-and-rollback.md`
- `docs/backup-retention-and-recovery.md`
