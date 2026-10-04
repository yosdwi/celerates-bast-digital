# Final commit-bound manual QA — Digital BAST v2

Reviewed SHA: `f010a7983107c6165916593cbb3dd44649d93f70`  
Surface: local `dbastverify-*` runtime plus independently recorded production reverification  
Date: 2026-08-03 Asia/Jakarta

The requested SHA was verified before probes began. Because this is a shared worktree, a parent-agent commit advanced the checkout to `66e1ce6` (with `f010a798` as its parent) after the probes; no checkout or revert was performed. The scenario matrix therefore records the initial exact-SHA result and the final observed drift.

<verdict>FAIL</verdict>

P0 result: PASS for the production evidence reviewed: green active, green/blue healthy, web health/auth protection, Prefect protection and five schedules, migration head, backup restore, cleanup, and rollback dry-run are all exit-0 in the independent reverification artifacts.

P1 result: FAIL for the local readiness criterion. The healthy-container `dbastverify-*` verification stack returns `503 {"status":"not_ready"}` from `/health/ready`; its external NocoDB/backend dependency is unavailable. This is a local-environment blocker, while production reverification records `/health/ready` 200.

Blocking issue: `P1-LOCAL-READY` — provide a ready local dependency fixture (or explicitly waive local readiness) before treating the local web readiness gate as passed. No production mutation was attempted.

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| WEB-LIVE-LOGIN-AUTH | local web live/ready/login protection | `http://127.0.0.1:8080` through local reverse proxy | `curl -i --max-time 10 http://127.0.0.1:8080/health/live`; `curl -i --max-time 10 http://127.0.0.1:8080/login`; `curl -i --max-time 10 http://127.0.0.1:8080/`; `curl -i --max-time 10 -X POST --data 'type=developer&month=8' http://127.0.0.1:8080/api/generate/plan` | PASS — live 200, login 200, root 303 to `/admin/login`, protected API 401 | `A1`, `A2` |
| WEB-READY | local web live/ready/login protection | `curl -i --max-time 10 http://127.0.0.1:8080/health/ready` | FAIL — 503 `{"status":"not_ready"}` in local stack; production counterpart is 200 in `A3` | `A1`, `A3` |
| PREFECT-LOCAL-PROTECTION | Prefect API/UI protected behavior | `curl -i --max-time 10 http://127.0.0.1:4200/api/health`; `curl -i --max-time 10 http://127.0.0.1:4200/`; `curl -i --max-time 10 -X POST -H 'Content-Type: application/json' --data '{"limit":100}' http://127.0.0.1:4200/api/deployments/filter`; authenticated requests inside `dbastverify-prefect-server-1` using mounted auth file | PASS — health/UI 200, unauth deployments 401, authenticated filters 200 (local data set empty) | `A1`, `A2` |
| PREFECT-PRODUCTION-SCHEDULES | five deployment schedules | production Prefect server; authenticated `POST /api/deployments/filter` and `POST /api/flow_runs/filter` as recorded by independent reverification | PASS — exactly five named deployments, each one active schedule; 20 flow runs returned | `A3` |
| RUNTIME-IMAGE-USER-COMPOSE | current image/user/Compose state | `SECRETS_GID=$(id -g) NOCODB_BASE_URL=https://invalid.local docker compose -p dbastverify -f compose.yaml -f compose.local.yaml ps`; `docker inspect -f ... <containers>`; `docker image inspect digital-bast:verify -f ...` | PASS — services up; app user `10001:10001`, read-only rootfs; proxy `101:101`, read-only rootfs | `A1`, `A2` |
| OPS-GATES | targeted ops shell gates affected by final changes | `timeout 30s bash -n scripts/*.sh tests/ops/*.sh`; each `timeout 60s tests/ops/{adversarial,local-image-deploy,preflight-retention,rollback-slots}.sh`; `timeout 60s env SECRETS_GID=$(id -g) NOCODB_BASE_URL=https://invalid.local scripts/check-ops.sh`; `docker exec dbastverify-web-blue-1 sh -c 'alembic current 2>&1 | tail -n 8'` | PASS — all shell gates exit 0; migration `20260803_0001 (head)` | `A1` |
| ROLLBACK-CLEANUP | blue rollback and cleanup evidence | independent production reverification artifacts; `scripts/rollback.sh --dry-run` and post-cleanup container/filesystem checks as recorded | PASS — blue healthy rollback target, green/blue healthy, no candidate tree/transfer archives, SSH cleanup exit 0, backups retained | `A3` |
| SHA-DIRTY | exact SHA and dirty status | `git rev-parse HEAD`; `git status --short --branch` at probe start and final handoff | FAIL at handoff — probe start was exact `f010a798…`; shared worktree later advanced to `66e1ce6`; only untracked `.omo/` and `diff.png` otherwise | `A1`, `A4` |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| ADV-WEB-UNAUTH | login protection | unauthenticated access | root redirects to login; valid protected API request returns 401 | PASS | `A1`, `A2` |
| ADV-PREFECT-UNAUTH | Prefect protected behavior | unauthenticated API access | deployments filter returns 401 | PASS | `A1`, `A2` |
| ADV-DEPENDENCY-FAIL-CLOSED | readiness | unavailable external dependency | readiness fails closed with 503 `not_ready`, not a false 200 | PASS (adversarial behavior); contributes to `WEB-READY` P1 gate failure | `A1` |
| ADV-ROLLBACK-SLOT | rollback safety | active green with retained blue | dry-run targets healthy blue and does not mutate slots | PASS | `A3` |
| ADV-CLEANUP-RESIDUE | cleanup | post-deploy residue | no candidate tree, transfer archives, restore-test DBs, or SSH helper remain | PASS | `A3` |

## artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | command transcript | Fresh local dbastverify HTTP probes, image/user/Compose inspection, targeted shell gates, migration, SHA and dirty status | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/final-qa-probes.txt` |
| A2 | live surface output | Raw local probe observables from the final QA run, summarized without auth/secrets | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/final-qa-probes.txt` |
| A3 | independent production transcript | Prior independent production reverification of runtime, Prefect five schedules, backup restore, cleanup, rollback, and SSH cleanup | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/REVERIFIED.md`; `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/01-runtime.txt`; `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/02-prefect.txt`; `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/03-backup-restore.txt`; `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/04-cleanup-state.txt`; `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/05-ssh-cleanup.txt` |
| A4 | commit-state check | Final shared-worktree SHA/log check showing post-probe advancement | `/mnt/d/Github/celerates/digital-bast/v2-prod/.git` (`git log --oneline -5` observed `66e1ce6` with `f010a79` parent) |
