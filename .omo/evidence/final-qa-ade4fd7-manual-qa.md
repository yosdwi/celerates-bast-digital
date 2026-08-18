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

# Fresh manualQa matrix bound to SHA ade4fd7aa9e5317bd78fde599c1e314be212364f

<verdict>FAIL</verdict>

Exact HEAD was verified before and after probes. Production reverification passes web live/ready/auth, exactly five deployments with one active schedule each, green/blue rollback, backup restore, cleanup, migration, and recovery assets. Local /health/ready is 503 because external NocoDB is intentionally absent locally; production ready is 200, so this is an environment caveat. Exact-SHA release asset executability is blocking: git ls-tree reports scripts/deploy.sh mode 100644; git archive yields 0644 and tests/ops/local-image-deploy.sh exits 126 Permission denied.

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| SHA-EXACT-OPS | exact commit ops gates | git archive ade4fd7; tests/ops adversarial, backup-restore, local-image-deploy | FAIL: adversarial and backup pass; local-image exits 126 | QA1 |
| RELEASE-ASSET-MODE | release asset integrity | git ls-tree and stat archived deploy.sh | FAIL: mode 100644/0644 conflicts with workflow test -x | QA1 |
| LOCAL-WEB-AUTH | web auth | curl -i live/login/root/unauth plan POST | PASS 200/200/303/401 | QA2,QA3 |
| LOCAL-WEB-READY | local readiness caveat | curl -i http://127.0.0.1:8080/health/ready | PASS with caveat 503 fail-closed; production 200 | QA2,QA3 |
| LOCAL-PREFECT | Prefect protection | curl -i health/UI/unauth filter and authenticated container filters | PASS 200/200/401; authenticated 200 | QA2 |
| LOCAL-COMPOSE | runtime hardening | docker compose ps; alembic current; docker inspect | PASS healthy, migration head, users/read-only correct | QA2 |
| PROD-OPS | production readiness/ops | independent reverification artifacts | PASS web/auth, five schedules, rollback, restore, cleanup | QA3 |
| QUALITY-71-PIC-TWOPASS | predecessor evidence | preserved runtime transcript | PASS 71 tests; PIC 2 then 0; pass 2 writes 0 | QA4 |
| NEW-OPS-GATES | release-trust/backup/retention/rollback | affected scripts and check-ops | FAIL bound to exact SHA due mode; current worktree passes with uncommitted mode fix | QA1,QA5 |

### adversarialCases

| scenario id | adversarial class / expected | verdict | artifactRefs |
|---|---|---|---|
| ADV-UNAUTH-WEB | root redirects and protected API returns 401 | PASS | QA2,QA3 |
| ADV-UNAUTH-PREFECT | unauth filter 401; auth succeeds | PASS | QA2,QA3 |
| ADV-READY-FAIL-CLOSED | absent dependency returns 503 | PASS local caveat | QA2,QA3 |
| ADV-IMMUTABLE-IMAGE | mutable rejected; local requires opt-in | PASS current worktree; exact SHA blocked by mode | QA1,QA5 |
| ADV-BACKUP | invalid selector rejected; restore has tables; cleanup | PASS | QA1,QA3 |
| ADV-ROLLBACK | healthy blue rollback target | PASS | QA3 |
| ADV-CLEANUP | no candidate/archive/restore DB/SSH residue | PASS | QA3 |
| ADV-RELEASE-EXECUTABLE | archive keeps deploy script executable | FAIL: archive 0644 and permission denied | QA1 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| QA1 | exact-SHA command transcript | archive ops and permission failure | /mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/final-qa-ade4fd7-exact-sha-ops.txt |
| QA2 | fresh local runtime transcript | HTTP/Prefect/Compose/migration/container probes | /mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/final-qa-ade4fd7-local-runtime.txt |
| QA3 | independent production reverification | runtime, Prefect, restore, cleanup, SSH | /mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/REVERIFIED.md and reverification 01-05 transcripts |
| QA4 | predecessor runtime evidence | 71-test, PIC, two-pass | /mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/resumed-session-runtime-evidence.md |
| QA5 | current worktree gate receipt | uncommitted mode-fix rerun | /mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/release-head-ade4fd7-blockers.md |

Blocker: commit scripts/deploy.sh mode 100755 at reviewed HEAD, then rerun exact-SHA archive gates.
