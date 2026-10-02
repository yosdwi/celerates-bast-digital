# Digital BAST v2 direct production deployment DoneClaim

Date: 2026-08-03 Asia/Jakarta  
Target: `debian@142.44.242.56`  
Deploy path: `/home/debian/script/digital-bast-v2`  
Verdict: **LIVE — green active; blue healthy and retained for rollback.**

Authentication used one temporary OpenSSH control socket. The password was sent only to the
interactive SSH password prompt; it was not placed in a command argument, output, repository,
artifact, helper file, or process title. Commands below redact the socket path.

## Success criteria and binary observables

| Scenario | Redacted invocation | Binary observable | Artifact |
|---|---|---|---|
| Host/deploy-path discovery | `ssh -S <socket> debian@142.44.242.56 '<bounded inventory>'` | exit 0; path `/home/debian/script/digital-bast-v2`; Docker 29.2.1; Compose 5.0.2 | `01-remote-inventory.txt` |
| Final local operational gates | `sh -n scripts/*.sh tests/ops/*.sh`; each `tests/ops/*.sh`; `scripts/check-ops.sh` | syntax 0; adversarial/local-image/preflight-retention/rollback-slots all 0; check-ops 0 | `13-final-local-gates.txt`, `preflight-ops-fix-verification-4.md` in parent evidence directory |
| Source artifact integrity | `tar ...` excluding `.git/.omo/.env/secrets/diff/cache`; `scp -o ControlPath=<socket> ...` | final SHA-256 `d75fcfc7f1676d6aa95c4e7f93fd96363e5a22dd17ceb6077b69098225df06d9`; forbidden entries 0; SCP 0 | `23-final-source-sync.txt` |
| Pre-switch backup and restore proof | `pg_dump -Fc` for both v2 databases; restore each into an isolated database; count public tables; drop isolated database | app dump 11,773 bytes / 7 tables; Prefect dump 263,925 bytes / 36 tables; both exit 0; zero restore-test databases remain | `11-predeploy-backup-restore.txt`, `12-backup-cleanup-verification.txt` |
| Required legacy read-only secret | create dedicated role through admin `psql` stdin; write file atomically with 0640; run image with secret bind mount | role is login/non-superuser/non-createrole; `default_transaction_read_only=on`; 99 SELECT grants; runtime SELECT works and UPDATE is denied; exit 0 | `19-legacy-readonly-secret.txt`, `22-legacy-runtime-readonly.txt` |
| Final candidate gates | `scripts/preflight.sh`; `PATH=<temporary-rg> scripts/check-ops.sh`; `APP_IMAGE=<immutable-tag> scripts/deploy.sh --dry-run` | all exit 0; local-image dry-run pulls only Postgres/Redis/Nginx and targets green | `24-final-candidate-gates.txt` |
| Immutable image build | `timeout 900s docker build --pull=false -t <immutable-tag> .` | exit 0; final tag `digital-bast:v2-d75fcfc7f167`; image ID `sha256:8c4b9bd97da0f0e373a8750ddfd20b95cc5470e8dd7642bf610dc686b8ca6637`; size 119,750,874 bytes | `21-remote-image-build.txt`, `24-final-candidate-gates.txt` |
| Active-path preflight | sync verified source while preserving `.env`/`secrets`; `scripts/preflight.sh` | exit 0; pre-state blue healthy; source SHA matches; APP_IMAGE selector is immutable | `25-active-sync-preflight.txt` |
| Production deploy | `timeout 600s scripts/deploy.sh` | exit 0; preflight passed; Alembic ran; target worker/runner started; Nginx syntax passed; `deployment complete: green` | `26-production-deploy.txt` |
| Web health and protection | bounded curl to `/health/live`, `/health/ready`, `/`, `/login`, and valid unauthenticated API POST | live 200; ready 200; login 200; root 303 to login; protected API 401 | `27-postdeploy-surface.txt`, `29-final-runtime-rollback.txt` |
| Prefect reachability/protection | bounded host curl plus authenticated and unauthenticated Prefect API requests | API health/UI reachable; protected deployments filter is 401 without auth and 200 with auth | `27-postdeploy-surface.txt`, `28-prefect-deployments-flows.txt` |
| Five deployments and schedules | authenticated `POST /api/deployments/filter` | count 5; `iot-pic-update`, `monthly-timesheets`, `nightly-reconciliation`, `operational-import`, `reference-data`; each has one active schedule | `28-prefect-deployments-flows.txt` |
| Flow state inspection | authenticated `POST /api/flow_runs/filter` (inspection only; no manual production trigger) | exit 0; 20 recent runs returned; scheduled runs recorded | `28-prefect-deployments-flows.txt` |
| Rollback readiness | `scripts/rollback.sh --dry-run` plus independent container inspection | dry-run exit 0 targets blue; blue remains running/healthy on old image `sha256:c226...`; green remains running/healthy on new image | `29-final-runtime-rollback.txt` |

## Final production state

- Active Nginx slot: `web-green:8000`.
- Green web, worker, runner, Prefect server, and Prefect services use
  `digital-bast:v2-d75fcfc7f167`; green web is healthy.
- Blue web and worker remain running on `digital-bast:v2-verify`; blue web is healthy and is
  the immediate rollback target.
- Alembic reports `20260803_0001 (head)`.
- Final `/health/live` body is `{"status":"healthy","service":"digital-bast-admin"}` and
  `/health/ready` is `{"status":"ready"}`.
- Root available space after deployment is 22,182,904 KiB, above the approved 20-GiB gate.
- Deployment lock is available after completion.

## Preserved recovery assets

- `/home/debian/backups/digital_bast_app-predeploy-20260803T061222Z.dump` — mode 0600.
- `/home/debian/backups/digital_bast_prefect-predeploy-20260803T061222Z.dump` — mode 0600.
- `/home/debian/backups/digital-bast-v2-source-predeploy-20260803T062553Z.tar.gz` — mode 0600.
- `/home/debian/backups/digital-bast-v2-env-predeploy-20260803T063506Z` — mode 0600.
- Old image tag `digital-bast:v2-verify` and healthy blue containers remain present.

## Cleanup receipt

- Removed the candidate tree, including its copied secret directory and temporary `rg` binary.
- Removed both remote transfer archives and the temporary intermediate image tag.
- Removed local transfer archives, final-SHA helper file, SSH control socket, and SSH temp directory.
- Removed the single empty failed dump candidate; retained all successful backups.
- Verified no restore-test database remains, no transfer archive remains remotely, and production
  green/blue services still run after cleanup.
- Cleanup observables: `30-cleanup-receipt.txt` and `31-local-ssh-cleanup.txt`, both exit 0.

## Notes

- The first documented preflight correctly failed before the user-approved policy update removed
  the total-capacity gate; the final enforced gate remains at least 20 GiB available and passed.
- A contaminated local Python test environment produced collection errors and is not cited as
  deployment proof. Operational regression scripts passed independently, and final application,
  migration, Prefect, deployment, flow, health, authentication, and rollback surfaces were
  verified directly on production.
- Encrypted off-host backup automation (`age`/`BACKUP_REMOTE`) remains an operations follow-up;
  this direct deployment used the explicitly authorized local 0600 snapshot plus successful
  disposable restore proof.
