# Digital BAST v2 — domain checkbox 2 runtime QA

Status: PASS (light evidence lane; verification only)

Scope: `src/digital_bast/domain`, `src/digital_bast/application`,
`tests/unit/domain`, and `tests/shadow/test_domain_parity.py`.
No product files were edited.

## Automated targeted tests

Scenario: run the repository-targeted unit and shadow domain suites.

Invocation (bounded to 120 seconds):

```text
timeout 120s env PYTHONPATH=src uv run --isolated --no-project \
  --with 'pytest>=8.4,<9' --with 'pytest-asyncio>=1.1,<2' \
  pytest -q tests/unit/domain tests/shadow/test_domain_parity.py
```

Binary observable:

```text
..................                                                       [100%]
18 passed in 3.41s
EXIT_STATUS=0
```

Coverage includes typed domain rules/ports for holidays, attendance, tasks,
schedules, timesheets, deterministic identity keys, manual-lock merge
semantics, timezone/naive timestamp rejection, and cursor/schedule ports.

The project-local environment invocation was also attempted and exited 1
before collection because its installed `pytest-cov` dependency imports a
missing `coverage.disposition` module. This is an environment defect, not a
product failure; the isolated uv invocation above exercised the same targeted
tests successfully without modifying the worktree.

## Real-surface fresh-process driver

Scenario: against importable project code (`PYTHONPATH=src`, `.venv/bin/python`),
construct one manual attendance and a competing pipeline attendance, merge
them, generate a February 2024 leap-month timesheet, and compute the leap-day
timesheet key twice.

Invocation (each process bounded to 20 seconds):

```text
printf '<driver>' | timeout 20s env PYTHONPATH=src .venv/bin/python - > /tmp/domain_driver_1.out
printf '<driver>' | timeout 20s env PYTHONPATH=src .venv/bin/python - > /tmp/domain_driver_2.out
```

Binary observables (both fresh processes exited 0; outputs were byte-identical):

```json
{"changed": false, "keys_identical": true, "leap_day_key_one": "timesheet:2024-02-29:qa-employee", "leap_day_key_two": "timesheet:2024-02-29:qa-employee", "leap_day_remarks": "Leap Holiday", "locked": true, "manual_start_after": "2024-02-29T07:30:00+07:00", "manual_start_before": "2024-02-29T07:30:00+07:00", "timesheet_count": 29}
```

Assertions proved: manual value unchanged, `locked=true`, `changed=false`,
leap-day keys equal, leap-month row count 29, and leap-day holiday linkage.
`cmp -s /tmp/domain_driver_1.out /tmp/domain_driver_2.out` returned success.

Typed-port probe (bounded to 20 seconds) constructed `SourceWindow` and
`SyncCursor` with Jakarta-aware datetimes and confirmed a naive `SourceWindow`
timestamp is rejected:

```text
TYPED_PORTS_OK=True NAIVE_SOURCE_WINDOW_REJECTED=True
PORT_PROBE_EXIT=0
```

## Adversarial probes

- `stale_state`: reran the real-surface driver in a fresh process; deterministic
  JSON matched byte-for-byte and both exits were 0.
- `dirty_worktree`: captured `git status --short` immediately before and after
  both drivers; the listings were identical (all pre-existing untracked
  project files; no driver or product-file changes).
- `misleading_success_output`: a command emitted `SUCCESS` but exited 7;
  recorded `MISLEADING_EXIT=7`, so output was not accepted as success.
- `malformed_input`: naive attendance timestamp and `Month(2024, 13)` were
  rejected with typed errors; output was
  `NAIVE_REJECTED=True INVALID_PERIOD_REJECTED=True`, exit 0.
- `long_command`: `timeout 2s sh -c 'sleep 10'` terminated with exit 124,
  confirming a bounded timeout.

## Explicit N/A

- `prompt_injection`: N/A — no untrusted text or LLM boundary is involved.
- `cancel_resume`: N/A — synchronous deterministic driver; no resumable
  operation.
- `flaky_tests`: N/A — targeted tests and driver are deterministic/synchronous;
  no sleeps or wall-clock assertions.
- `repeated_interruptions`: N/A — no mid-operation state machine to interrupt.

Cleanup receipt: no repository temporary files or containers were created; the
driver was stdin-only. All temporary `/tmp` outputs created for this attempt
were removed with explicit `unlink` calls and verified absent.

## Stop-hook re-verification (2026-08-03)

The prior completion claim was independently re-run before this section was
written. The targeted test command exited 0 with:

```text
..................                                                       [100%]
18 passed in 5.37s
EXIT_STATUS=0
```

Two fresh stdin-driven processes (each `timeout 20s`) both exited 0 and emitted
the following identical JSON; `cmp -s` returned `BYTE_IDENTICAL_EXIT=0`:

```text
{"changed": false, "keys_identical": true, "leap_day_key_one": "timesheet:2024-02-29:qa-employee", "leap_day_key_two": "timesheet:2024-02-29:qa-employee", "locked": true, "manual_start_after": "2024-02-29T07:30:00+07:00", "manual_start_before": "2024-02-29T07:30:00+07:00", "timesheet_count": 29}
```

The re-run adversarial outputs were:

```text
MALFORMED_EXIT=0 OUTPUT=NAIVE_REJECTED=True INVALID_PERIOD_REJECTED=True
PORTS_EXIT=0 OUTPUT=TYPED_PORTS_OK=True NAIVE_SOURCE_WINDOW_REJECTED=True
MISLEADING_EXIT=7 OUTPUT=SUCCESS
LONG_EXIT=124 OUTPUT=
DIRTY_STATUS_IDENTICAL_EXIT=0
```

These outputs were captured from direct invocations and appended only after
their exit codes/assertions were checked.

## Stop-hook re-verification #2 (2026-08-03)

A second independent execution was performed after the hook rejected the prior
completion claim. The bounded targeted suite produced:

```text
TEST_EXIT=0
..................                                                       [100%]
18 passed in 2.45s
```

The manual-lock/leap-timesheet driver was executed in two fresh processes:

```text
DRIVER1_EXIT=0 DRIVER2_EXIT=0 BYTE_CMP_EXIT=0
D1={"after": "2024-02-29T07:30:00+07:00", "before": "2024-02-29T07:30:00+07:00", "changed": false, "key1": "timesheet:2024-02-29:qa-employee", "key2": "timesheet:2024-02-29:qa-employee", "keys_identical": true, "locked": true, "rows": 29}
D2={"after": "2024-02-29T07:30:00+07:00", "before": "2024-02-29T07:30:00+07:00", "changed": false, "key1": "timesheet:2024-02-29:qa-employee", "key2": "timesheet:2024-02-29:qa-employee", "keys_identical": true, "locked": true, "rows": 29}
```

The second adversarial run produced:

```text
MALFORMED_EXIT=0 NAIVE_REJECTED=True INVALID_PERIOD_REJECTED=True
PORTS_EXIT=0 TYPED_PORTS_OK=True NAIVE_SOURCE_WINDOW_REJECTED=True
MISLEADING_EXIT=7 OUTPUT=SUCCESS
LONG_EXIT=124
DIRTY_STATUS_IDENTICAL_EXIT=0
```

The outputs above were captured from live commands before this evidence
section was appended.

## Stop-hook re-verification #3 (2026-08-03)

The third direct audit reran the bounded test suite, fresh-process runtime
driver, and adversarial checks before this section was appended:

```text
TEST_EXIT=0
..................                                                       [100%]
18 passed in 2.85s

D1_EXIT=0 D2_EXIT=0 CMP_EXIT=0
D1={"changed": false, "key1": "timesheet:2024-02-29:qa-employee", "key2": "timesheet:2024-02-29:qa-employee", "keys_identical": true, "locked": true, "manual_after": "2024-02-29T07:30:00+07:00", "manual_before": "2024-02-29T07:30:00+07:00", "rows": 29}
D2={"changed": false, "key1": "timesheet:2024-02-29:qa-employee", "key2": "timesheet:2024-02-29:qa-employee", "keys_identical": true, "locked": true, "manual_after": "2024-02-29T07:30:00+07:00", "manual_before": "2024-02-29T07:30:00+07:00", "rows": 29}

MALFORMED_EXIT=0 NAIVE_REJECTED=True INVALID_PERIOD_REJECTED=True
MISLEADING_EXIT=7 OUTPUT=SUCCESS
LONG_EXIT=124 DIRTY_STATUS_IDENTICAL_EXIT=0
```
