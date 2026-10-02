# Final operations consistency fix

## Scope and baseline

- Repository: `/mnt/d/Github/celerates/digital-bast/v2-prod`
- Baseline HEAD: `66e1ce670db8019489c8eeb6430718ececf827f0`
- Scope: CI `SECRETS_GID`, retention SQL, two-database backup/restore contract, operator documentation, shell regression tests, and Git executable modes.
- Explicitly excluded shared changes to `release.yml`, `deploy.sh`, and `tests/ops/local-image-deploy.sh`.

## Red evidence

The shell regressions were added before the implementation:

- `tests/ops/preflight-retention.sh` exited 1 because retention still contained `nocodb_audit_events` and targeted the obsolete default database.
- `tests/ops/backup-restore.sh` exited 1 at the first exact invocation assertion because `backup.sh` called only `pg_dump ... -d digital_bast`.

## Implemented contract

- CI passes the valid, non-secret numeric group ID `SECRETS_GID: "0"` to `scripts/check-ops.sh`.
- Retention deletes only expired `generation_plans` rows from `digital_bast_app`; the nonexistent `nocodb_audit_events` dependency is removed.
- One `scripts/backup.sh` run produces separate encrypted custom-format backups for `digital_bast_app` and `digital_bast_prefect`, with per-database local and remote retention patterns.
- Restore testing requires `BACKUP_DATABASE` to be one of those two databases and requires the encrypted artifact filename to match it before restoring into an isolated temporary database.
- Operator documentation describes the two-artifact backup and two-database restore-test requirement.
- Actual directly executed operational scripts and assigned shell tests are recorded as mode `100755`; `scripts/lib.sh` remains `100644`. Explicitly excluded `scripts/deploy.sh` and `tests/ops/local-image-deploy.sh` were left at their existing Git modes.

## Final verification

The final combined verification exited 0 and printed `FINAL OPS CONSISTENCY VERIFICATION PASSED`:

- `bash -n` and `sh -n` for all operational scripts and assigned ops tests.
- Safe `SECRETS_GID=$(id -g) scripts/check-ops.sh`: `operations static checks passed`.
- `tests/ops/adversarial.sh`: passed.
- `tests/ops/preflight-retention.sh`: passed.
- `tests/ops/rollback-slots.sh`: passed with a controlled immutable image reference.
- `tests/ops/backup-restore.sh`: passed; its fake Docker harness asserts exactly two `pg_dump` database invocations (`digital_bast_app`, `digital_bast_prefect`), database-bound `createdb`/`pg_restore`/`psql`, and rejection of the obsolete `digital_bast` database name.
- `.github/workflows/ci.yml` parsed with `yaml.safe_load`.
- `git ls-files -s` assertions passed for all intended `100755` modes and the non-executable `100644` files.
- Production-scope scan found no 150 GB requirement, `nocodb_audit_events`, obsolete `POSTGRES_DB:-digital_bast` fallback, or stale backup/retention contract.

No commit or push was performed. Temporary fake binaries, logs, dumps, and identities were isolated under `mktemp -d` and removed by test traps.
