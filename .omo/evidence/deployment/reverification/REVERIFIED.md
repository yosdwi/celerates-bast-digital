# Independent production reverification

Verified directly against `debian@142.44.242.56` on 2026-08-03 after the original
DoneClaim. None of the original runtime observables were trusted as proof for this pass.

## Verdict

**PASS — the production deployment claim is independently reproduced.**

## Direct scenarios

| Scenario | Invocation | Observable | Artifact |
|---|---|---|---|
| Production runtime | SSH with a temporary control socket; `scripts/preflight.sh`; independent Compose/Docker inspection; bounded curls; `alembic current`; `scripts/rollback.sh --dry-run` | exit 0; preflight passed; active `web-green:8000`; green and blue both running/healthy on distinct expected image IDs; live/ready 200; root 303; API 401; migration at `20260803_0001 (head)`; rollback targets blue | `01-runtime.txt` |
| Prefect | Authenticated and unauthenticated requests executed inside the live Prefect server container | exit 0; health/UI 200; deployments endpoint 401 without auth and 200 with auth; exactly five deployments; each has exactly one active schedule; 20 runs returned (3 completed, 17 scheduled) | `02-prefect.txt` |
| Backup restore | Restore both retained custom-format dumps into newly created disposable databases, count public tables, drop databases | exit 0; app restored 7 public tables; Prefect restored 36; both test databases dropped; zero `reverify_%` databases remain | `03-backup-restore.txt` |
| Cleanup and recovery assets | Independent filesystem and post-restore container inspection | exit 0; no candidate tree; zero transfer archives; four expected 0600 recovery assets retained; blue and green still healthy | `04-cleanup-state.txt` |
| SSH cleanup | Close control master, remove socket directory | exit 0; temporary SSH directory absent | `05-ssh-cleanup.txt` |

## Reproduced production state

- Active slot: green.
- Green image ID: `sha256:8c4b9bd97da0f0e373a8750ddfd20b95cc5470e8dd7642bf610dc686b8ca6637`.
- Healthy blue rollback image ID: `sha256:c226d7e60e8f461cd6983380f924e0f977e79f3995a2c90e20723ae5bc2592b9`.
- Prefect deployments: `iot-pic-update`, `monthly-timesheets`, `nightly-reconciliation`, `operational-import`, and `reference-data`.
- Available root space: 22,188,956 KiB; deployment lock available.
- Reverification created no persistent database, candidate, transfer archive, or SSH helper/socket.
