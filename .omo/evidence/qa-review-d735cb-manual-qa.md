# Manual QA: exact SHA d735cb092af1ece7292fa9d6b429c3ff82ee4bcd

Verdict: **PASS**

Date: 2026-08-03 Asia/Jakarta
Repository: `/mnt/d/Github/celerates/digital-bast/v2-prod`

The checked-out `HEAD` equals the requested SHA. Exact-SHA probes ran before a concurrent agent's uncommitted edit to `tests/ops/release-trust.sh`; the reviewed commit and all probe commands remain pinned to the requested SHA. QA added only evidence under `.omo/evidence/`.

## surfaceEvidence

| Scenario | Criterion | Invocation | Verdict | artifactRefs |
|---|---|---|---|---|
| SHA-ARCHIVE-MODE | exact-SHA release asset is executable | `git rev-parse HEAD`; `git ls-tree HEAD scripts/deploy.sh`; `git archive --format=tar d735cb... scripts/deploy.sh \| tar -tvf -` | PASS — requested HEAD; tracked/archive deploy entrypoint executable | QA-D735-GATES |
| RELEASE-TRUST | release trust | `timeout 60s sh tests/ops/release-trust.sh` | PASS, exit 0 | QA-D735-GATES |
| OPS-GATES | shell syntax/static/behavior | `bash -n scripts/*.sh tests/ops/*.sh`; `scripts/check-ops.sh`; each targeted ops gate | PASS, all exit 0 | QA-D735-GATES |
| STATIC-PYTHON | static quality | `.venv/bin/ruff check .`; `.venv/bin/ruff format --check .` | PASS, exit 0; 140 files formatted | QA-D735-GATES |
| PROD-READY | production readiness/rollback | SSH preflight, Compose inspection, bounded curl health/auth, `scripts/rollback.sh --dry-run`, Alembic current | PASS — live/ready 200; green active; blue healthy rollback | PROD-REVERIFY, PROD-RUNTIME |
| PREFECT-SCHEDULES | five deployments/schedules | Authenticated and unauthenticated Prefect API filters | PASS — exactly five; one active schedule each; 20 runs | PROD-PREFECT |
| BACKUP-RESTORE | retained backups/restores | Restore both dumps into disposable DBs, count tables, drop DBs | PASS — app 7 tables; Prefect 36; zero reverify DBs | PROD-BACKUP, PROD-CLEANUP |
| CLEANUP | residue/SSH cleanup | Remote filesystem/container inspection; close control master | PASS — no candidate/archive/restore/SSH residue | PROD-CLEANUP, PROD-SSH |
| PREDECESSOR-QUALITY | 71 tests/PIC/two-pass | Inspect preserved runtime transcript | PASS — 71 tests; PIC 2 then 0; pass 2 writes 0 | PREDECESSOR |

## adversarialCases

| Scenario | Class | Expected behavior | Verdict | artifactRefs |
|---|---|---|---|---|
| ADV-MUTABLE-IMAGE | mutable image selector | Reject mutable registry tag; local image only with explicit opt-in | PASS | QA-D735-GATES |
| ADV-LOCK-GUARD | concurrent deployment lock | Reject while lock held | PASS | QA-D735-GATES |
| ADV-LOW-DISK | below-policy disk | Reject below 20 GB and preserve retention SQL contract | PASS | QA-D735-GATES |
| ADV-BACKUP-SCOPE | wrong DB/empty restore | Reject invalid binding and empty restore | PASS | QA-D735-GATES |
| ADV-ROLLBACK-SLOTS | rollback safety | Target healthy blue and stop paired green services | PASS | QA-D735-GATES, PROD-RUNTIME |
| ADV-CLEANUP-RESIDUE | temporary residue | Remove candidate/archive/restore residue; retain recovery assets | PASS | PROD-CLEANUP, PROD-SSH |
| ADV-LOCAL-READINESS | absent local NocoDB | Local 503 is caveat only; production readiness authoritative | PASS | LOCAL-CAVEAT, PROD-RUNTIME |

## artifactRefs

| id | kind | description | path |
|---|---|---|---|
| QA-D735-GATES | transcript | Exact-SHA archive mode, release-trust, ops gates, syntax, diff, Ruff | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/qa-review-d735cb-exact-gates.txt` |
| PROD-REVERIFY | report | Independent production reverification summary | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/REVERIFIED.md` |
| PROD-RUNTIME | transcript | Production health/auth/migration/slots/rollback | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/01-runtime.txt` |
| PROD-PREFECT | transcript | Five deployments, schedules, flow runs | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/02-prefect.txt` |
| PROD-BACKUP | transcript | Both backup restores and table counts | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/03-backup-restore.txt` |
| PROD-CLEANUP | transcript | Cleanup and recovery assets | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/04-cleanup-state.txt` |
| PROD-SSH | transcript | SSH cleanup | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/05-ssh-cleanup.txt` |
| PREDECESSOR | report | 71-test/PIC/two-pass evidence | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/resumed-session-runtime-evidence.md` |
| LOCAL-CAVEAT | transcript | Local readiness 503 without external NocoDB | `/mnt/d/Github/celerates/digital-bast/v2-prod/.omo/evidence/deployment/reverification/final-qa-probes.txt` |

## Blockers

No P0 or P1 blockers found. DONECLAIM notes encrypted off-host backup automation as a follow-up; local mode-0600 snapshots and independent restore proof passed.
