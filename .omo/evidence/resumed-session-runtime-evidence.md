# Resumed-session runtime evidence

Source: the user's preserved terminal transcript supplied when this `start-work` continuation began on 2026-08-03. Values below are copied as non-sensitive observables; credentials and environment contents are omitted.

- Docker quality gate: Ruff format/check, basedpyright, and pytest completed successfully; pytest reported `71 passed in 15.46s`.
- Live Google reader after correcting the `majorDimension=COLUMNS` response shape reported `iot_rows=1257`.
- Two-pass pipeline runtime:
  - pass 1: IoT task import `1257/70/0`, holiday `17/17/0`, schedule `2/31/0`, timesheet `105/62/0`, reconciliation `165/0/165` (`read/written/unchanged`).
  - pass 2: the same reads with `written=0`; unchanged counts were IoT `70`, holiday `17`, schedule `31`, timesheet `62`, reconciliation `165`.
- Legacy PIC production-shaped PostgreSQL harness: first pass inserted `2`; second pass inserted `0`; two links existed and one unmatched task remained safe.
- Prefect local deployment surface: five deployments named `iot-pic-update`, `monthly-timesheets`, `nightly-reconciliation`, `operational-import`, and `reference-data`; protected API returned `401` unauthenticated and `200` authenticated.

This record supplements the independently captured production deployment and reverification artifacts under `.omo/evidence/deployment/`.
