# Manual QA — commit `307c5dbf972990321d8f63c8d269910e76e3237f`

Scope: exact commit review in `/mnt/d/Github/celerates/digital-bast/v2-prod`. No credentials or secret contents were printed.

## surfaceEvidence

| Scenario | Criterion reference | Surface | Exact invocation | Verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | C1 exact revision and file scope | Git repository | `git rev-parse HEAD`; `git show --no-renames --format=fuller --stat --summary 307c5dbf972990321d8f63c8d269910e76e3237f`; `git diff-tree --no-commit-id --name-status -r 307c5dbf972990321d8f63c8d269910e76e3237f` | PASS — HEAD is the requested SHA; changed files are `.env.example`, `compose.yaml`, `docs/local-development.md`, and `tests/ops/prefect-ui-url.sh`; only pre-existing/untracked QA files are present in status. | A1 |
| S2 | C2 targeted Prefect UI URL regression test | Shell/Compose config | `sh tests/ops/prefect-ui-url.sh` | PASS — `Prefect UI API URL checks passed` (exit 0). | A2 |
| S3 | C3 complete ops test suite under requested safe env | Shell scripts | `for f in tests/ops/*.sh; do SECRETS_GID=$(id -g) NOCODB_BASE_URL=https://invalid.local sh "$f"; done` | PASS — adversarial, backup-restore, local-image-deploy, prefect-ui-url, preflight-retention, release-trust, and rollback-slots all exited 0. | A3 |
| S4 | C4 static operations gate | Shell script | `SECRETS_GID=$(id -g) NOCODB_BASE_URL=https://invalid.local sh scripts/check-ops.sh` | PASS — `operations static checks passed` (exit 0). | A4 |
| S5 | C5 public Prefect availability and protection | HTTPS public Prefect endpoint | `curl -i -sS --max-time 20 https://conform-v2-stagging.celeratesapps.com/v2/`; `curl -i -sS --max-time 20 https://conform-v2-stagging.celeratesapps.com/api/health`; unauthenticated `curl -i -sS --max-time 20 -X POST -H 'content-type: application/json' --data '{}' https://conform-v2-stagging.celeratesapps.com/api/deployments/filter` | PASS — root returned HTTP 200 with `Prefect Server` HTML, health returned HTTP 200/`true`, and protected deployment filter returned HTTP 401. Existing browser transcript also records dashboard title and `visible_deployment_count=5`. | A5, A6 |
| S6 | C6 cleanup/no leftover QA resources | Docker daemon | `docker ps -a --filter name=dbastverify --format '{{.ID}} {{.Names}}'`; `docker network ls --filter name=dbastverify --format '{{.ID}} {{.Name}}'`; `docker volume ls --filter name=dbastverify --format '{{.Name}}'` | PASS — all three filtered listings are empty; full inventory also contains no `dbastverify` match. | A7, A8 |

## adversarialCases

| Scenario | Criterion reference | Adversarial class | Expected behavior | Verdict | artifactRefs |
|---|---|---|---|---|---|
| S2-A | C2 | Configuration override/fallback | Explicit public `PREFECT_SERVER_UI_API_URL` propagates to both Prefect services; unset value falls back to loopback `/api`. | PASS — targeted script validates both branches. | A2 |
| S3-A | C3 | Missing secrets / lock contention / mutable image / rollback safety | Ops scripts reject unsafe preconditions and preserve safety gates while still passing their positive assertions. | PASS — `adversarial.sh`, `local-image-deploy.sh`, and `rollback-slots.sh` passed. | A3 |
| S5-A | C5 | Unauthenticated protected API access | Public root/health remain reachable, while deployment data endpoint rejects unauthenticated access with 401. | PASS — direct `curl -i` probes returned 200, 200, and 401 respectively. | A5 |
| S6-A | C6 | Residual-resource leakage | No stopped/running container, network, or volume named `dbastverify` remains. | PASS — all filtered Docker queries returned no rows. | A7, A8 |

## artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | command transcript | Exact SHA, commit summary, changed-file list, and working-tree status. | `.omo/evidence/qa-review-307c5db/commit-and-files.txt` |
| A2 | command transcript | Targeted Prefect UI API URL test output. | `.omo/evidence/qa-review-307c5db/prefect-ui-url.log` |
| A3 | command transcript | All `tests/ops/*.sh` outputs and per-script exit statuses. | `.omo/evidence/qa-review-307c5db/all-tests.log` |
| A4 | command transcript | `scripts/check-ops.sh` output. | `.omo/evidence/qa-review-307c5db/check-ops.log` |
| A5 | HTTP transcript | Unauthenticated `curl -i` root, health, and protected deployment-filter probes. | `.omo/evidence/qa-review-307c5db/public-prefect-curl.txt` |
| A6 | browser transcript | Existing authenticated-safe Prefect UI smoke showing title, protected API behavior, and five visible deployments. | `.omo/evidence/deployment/prefect-ui-fix/12-browser-deployments.txt` |
| A7 | command transcript | Filtered `docker ps`, `docker network ls`, and `docker volume ls` no-match checks. | `.omo/evidence/qa-review-307c5db/dbastverify-checks.txt` |
| A8 | command transcript | Full Docker container/network/volume inventory and no-match confirmation. | `.omo/evidence/qa-review-307c5db/docker-inventory.txt` |

Overall verdict: **PASS**.
