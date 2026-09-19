# Code quality review — ade4fd7aa9e5317bd78fde599c1e314be212364f

## Verdict

- `codeQualityStatus`: BLOCK
- `recommendation`: REQUEST_CHANGES
- Scope reviewed: the full commit diff against `ade4fd7^`, its resulting file modes,
  release/CI workflows, affected shell scripts, operation tests, and relevant compose
  configuration. The working tree was at the reviewed SHA; unrelated untracked `.omo/`
  material and `diff.png` were not treated as evidence.
- Verification performed: `git show --check`, `sh -n` across changed and operation shell
  scripts, mode inspection via `git ls-tree`, and static examination of the test runner
  and CI wiring. The full suite was intentionally not rerun per review scope.

## Findings

### CRITICAL

None.

### HIGH

1. **Release deployment is guaranteed to abort because its required entrypoint is not executable.**
   - `.github/workflows/release.yml:103` and `:164` require `test -x "$stage_dir/scripts/deploy.sh"`.
   - The reviewed tree records `scripts/deploy.sh` as mode `100644` (`git ls-tree ade4fd7 scripts/deploy.sh`), and the subsequent direct invocations at `.github/workflows/release.yml:113` and `:174` likewise need execute permission.
   - `git archive` preserves the tracked executable bit, so this fails in both staging and production before `deploy.sh` can run. Make `scripts/deploy.sh` executable and add a behavioral/package-mode check that fails when the archived deployment entrypoint is non-executable.

### MEDIUM

1. **The new operational coverage is not part of CI and therefore would not catch the release-blocking mode regression.**
   - `pyproject.toml` configures pytest only for Python test paths. The CI quality job runs `uv run pytest` and `scripts/check-ops.sh` (`.github/workflows/ci.yml:26-33`), while `scripts/check-ops.sh:8-10` only parses `tests/ops/*.sh` using `sh -n`; it never executes `tests/ops/local-image-deploy.sh`, `tests/ops/release-trust.sh`, `tests/ops/backup-restore.sh`, or `tests/ops/rollback-slots.sh`.
   - This is a concrete false-confidence path: `tests/ops/release-trust.sh` does not assert executable modes, and no CI-run test executes the packaged release flow.

2. **`tests/ops/release-trust.sh` is a brittle implementation-mirroring test rather than an observable release-contract test.**
   - `tests/ops/release-trust.sh:9-20` greps exact workflow and script source strings (including quoting and command spelling). It can fail on harmless refactors and still misses the executable-mode contract that the release workflow enforces.
   - Per the `remove-ai-slops` and `programming` perspectives, this is a needless prompt/text pin rather than a behavioral test. Replace it with a small archive/package test that verifies exact-SHA asset contents, deploy script execute mode, and accepted/rejected image references through the actual scripts.

### LOW

None.

## Required checklist recheck

- Direct-run scripts/entrypoints: all listed changed scripts except `scripts/deploy.sh` are mode `100755`; the deploy entrypoint failure above remains a blocker.
- CI `SECRETS_GID`: fixed at `.github/workflows/ci.yml:31-33`.
- Retention: `scripts/retention.sh:23-27` only deletes `generation_plans` from `digital_bast_app`.
- Backup/restore contract: `scripts/backup.sh:39-53` creates separate app and Prefect backups; `scripts/restore-test.sh:20-29` restricts and validates the two exact database names and filename binding.
- Release digest/exact-SHA assets/local opt-in: the release workflow archives `RELEASE_SHA` assets and passes a digest reference; `scripts/deploy.sh:55-69` restricts local use to explicit opt-in and otherwise validates a lower-case SHA-256 digest. The executable-mode defect prevents this flow from being usable.
- Blue rollback/runner cleanup: deployment failure cleanup and rollback stop `web`, `worker`, and `runner` together (`scripts/deploy.sh:47-50`, `scripts/rollback.sh:67`).

## Skill-perspective check

Ran. `omo:remove-ai-slops` and `omo:programming` were consulted before judging test relevance and maintainability. No Python production/test code changed, so no Python type issue is introduced by this commit. The production shell/workflow changes do not introduce needless parsing, normalization, untyped escape hatches, or abstraction. The diff violates both perspectives through the brittle, implementation-mirroring release-trust grep test described above; the non-executed ops tests also provide false confidence.

## Blockers

1. Track `scripts/deploy.sh` as executable (`100755`) so archived staging/production assets pass their own `test -x` gate and can be invoked.
2. Execute a behavioral operational test in CI that catches the archive/direct-run permission contract; eliminate or substantially replace the brittle source-grep release-trust test.
