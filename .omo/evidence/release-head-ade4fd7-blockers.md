# Release high-blocker fix at `ade4fd7`

## Red

### Release asset executable bit

- Scenario: inspect the Git release source for `scripts/deploy.sh` before the fix.
- Invocation: `git ls-files -s scripts/deploy.sh`.
- Observed output: `100644 ea44f817d0c7897c7dcd4f2c6375eafd246bc8cf 0 scripts/deploy.sh`.
- Judgment: an exact Git archive would preserve the non-executable mode, while the workflow invokes `scripts/deploy.sh` directly.

### Manual publish route

- Scenario: run the new release-trust static regression before the workflow fix.
- Invocation: `sh -x tests/ops/release-trust.sh`.
- Observed output: exit `1` at `grep -Fq workflow_dispatch .github/workflows/release.yml`; the workflow also had `if: github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success'`.
- Judgment: a manual release could bypass the successful-CI origin requirement.

## Green

### Executable exact release asset

- Scenario: test the staged release tree as the source for `git archive`.
- Invocation: `sh tests/ops/release-trust.sh`.
- Binary observable: exit `0`, stdout `release trust checks passed`. The test uses `git write-tree`, archives `scripts/deploy.sh`, asserts its Git index mode is `100755`, and asserts the extracted deployment script is executable.
- Direct Git observable: `git ls-files -s scripts/deploy.sh` now reports `100755 ea44f817d0c7897c7dcd4f2c6375eafd246bc8cf 0 scripts/deploy.sh`.

### CI-only release origin

- Scenario: static release workflow validation.
- Invocation: `sh tests/ops/release-trust.sh`.
- Binary observable: exit `0`, stdout `release trust checks passed`; it rejects `workflow_dispatch`, requires `if: github.event.workflow_run.conclusion == 'success'`, and rejects fallback use of `github.sha`.

### Requested verification

- Invocation: `sh tests/ops/release-trust.sh && sh tests/ops/local-image-deploy.sh && sh -n scripts/deploy.sh tests/ops/release-trust.sh tests/ops/local-image-deploy.sh && python3 -c 'import yaml, pathlib; yaml.safe_load(pathlib.Path(".github/workflows/release.yml").read_text()); print("release workflow YAML parsed")' && SECRETS_GID=10001 scripts/check-ops.sh && git diff --check`.
- Observed output: `release trust checks passed`; `local-image deploy checks passed`; `release workflow YAML parsed`; `operations static checks passed`; exit `0`.

DoneClaim: the release workflow can originate only from a successful CI workflow run, and the exact Git deployment asset is executable when archived.

## Stop-hook direct verification

Invocation:

```sh
sh tests/ops/release-trust.sh
sh tests/ops/local-image-deploy.sh
sh -n scripts/deploy.sh tests/ops/release-trust.sh tests/ops/local-image-deploy.sh
python3 -c 'import yaml, pathlib; yaml.safe_load(pathlib.Path(".github/workflows/release.yml").read_text()); print("release workflow YAML parsed")'
SECRETS_GID=10001 scripts/check-ops.sh
git diff --check
git ls-files -s scripts/deploy.sh
```

Observed output (process exit `0`):

```text
release trust checks passed
local-image deploy checks passed
release workflow YAML parsed
operations static checks passed
100755 ea44f817d0c7897c7dcd4f2c6375eafd246bc8cf 0 scripts/deploy.sh
HEAD_BLOCKERS_DIRECT_PASS
```

Judgment: both blocker criteria remain directly verified.

## Stop-hook second direct verification

Invocation: `sh tests/ops/release-trust.sh && sh tests/ops/local-image-deploy.sh && sh -n scripts/deploy.sh tests/ops/release-trust.sh tests/ops/local-image-deploy.sh && python3 -c 'import yaml, pathlib; yaml.safe_load(pathlib.Path(".github/workflows/release.yml").read_text()); print("release workflow YAML parsed")' && SECRETS_GID=10001 scripts/check-ops.sh && git diff --check && git ls-files -s scripts/deploy.sh`.

Observed output (process exit `0`):

```text
release trust checks passed
local-image deploy checks passed
release workflow YAML parsed
operations static checks passed
100755 ea44f817d0c7897c7dcd4f2c6375eafd246bc8cf 0 scripts/deploy.sh
HEAD_BLOCKERS_SECOND_DIRECT_PASS
```

Judgment: the second independent direct run confirms the CI-only workflow and archive-executable criteria remain green.

## Stop-hook third direct verification

Invocation: `sh tests/ops/release-trust.sh && sh tests/ops/local-image-deploy.sh && sh -n scripts/deploy.sh tests/ops/release-trust.sh tests/ops/local-image-deploy.sh && python3 -c 'import yaml, pathlib; yaml.safe_load(pathlib.Path(".github/workflows/release.yml").read_text()); print("release workflow YAML parsed")' && SECRETS_GID=10001 scripts/check-ops.sh && git diff --check && git ls-files -s scripts/deploy.sh`.

Observed output (process exit `0`):

```text
release trust checks passed
local-image deploy checks passed
release workflow YAML parsed
operations static checks passed
100755 ea44f817d0c7897c7dcd4f2c6375eafd246bc8cf 0 scripts/deploy.sh
HEAD_BLOCKERS_THIRD_DIRECT_PASS
```

Judgment: the final direct verification found no failing criterion; the artifact is ready for handoff.
