# Production source evidence

- Scenario: employee and Google-column parsing unit tests.
  - Invocation: `/tmp/digital-bast-v2-toolchain/project-venv/bin/pytest -p no:cov -q tests/unit/infrastructure/test_production_sources.py`.
  - Observable: `2 passed in 31.40s`.
  - Artifact: `/tmp/production_sources_pytest_final.log`.
- Scenario: Google source adapter batch range order, period filtering, fallback employee, and Jakarta time.
  - Invocation: fake `SheetBatchReader` driver using `/tmp/digital-bast-v2-toolchain/project-venv/bin/python` and `anyio.run`.
  - Observable: `GOOGLE_QA_OK`, `GOOGLE_QA_STATUS=0`.
  - Artifact: `/tmp/production_sources_google_qa_final.log`.
- Scenario: owned-module lint and formatting.
  - Invocation: `.venv/bin/ruff check src/digital_bast/infrastructure/production_sources.py` and `.venv/bin/ruff format --check src/digital_bast/infrastructure/production_sources.py`.
  - Observable: `All checks passed!`; `1 file already formatted`.
  - Artifact: command output captured in the task transcript.
- Scenario: strict type checking of the owned module.
  - Invocation: `uvx basedpyright src/digital_bast/infrastructure/production_sources.py`.
  - Observable: `0 errors, 0 warnings, 0 notes`.
  - Artifact: command output captured in the task transcript.

## Direct stop-hook re-verification

- The first direct pytest invocation used `PYTEST_DISABLE_PLUGIN_AUTOLOAD=0`; pytest treats any
  non-empty value as disabled and therefore reported `Unknown config option: asyncio_mode` with
  status 4. This was a verification-command setup failure, not a source failure.
- Corrected invocation: `/tmp/digital-bast-v2-toolchain/project-venv/bin/pytest -p no:cov -q tests/unit/infrastructure/test_production_sources.py`.
  Observable: `2 passed in 15.02s`, status 0.
  Artifact: `/tmp/production_sources_hook_pytest_retry.log`.
- Corrected direct adapter scenario used a fake `SheetBatchReader`, exact D/E/P/F/H/K/M ranges,
  period exclusion, IOT_TEAM fallback, and Jakarta time assertion.
  Observable: `MANUAL_QA_OK`, status 0.
  Artifact: `/tmp/production_sources_hook_manual.log`.
- Direct lint/type checks were rerun: Ruff check and format both status 0; basedpyright reported
  `0 errors, 0 warnings, 0 notes`.
  Artifacts: `/tmp/production_sources_hook_ruff.log`, `/tmp/production_sources_hook_pyright.log`.

## Stop-hook 2 direct command transcript

Working directory: `/mnt/d/Github/celerates/digital-bast/v2-prod`.

```text
$ /tmp/digital-bast-v2-toolchain/project-venv/bin/pytest -p no:cov -q tests/unit/infrastructure/test_production_sources.py
..                                                                       [100%]
2 passed in 12.55s
exit=0

$ .venv/bin/ruff check src/digital_bast/infrastructure/production_sources.py
All checks passed!
exit=0

$ .venv/bin/ruff format --check src/digital_bast/infrastructure/production_sources.py
1 file already formatted
exit=0

$ uvx basedpyright src/digital_bast/infrastructure/production_sources.py
0 errors, 0 warnings, 0 notes
exit=0

$ git diff --check
exit=0

$ fake SheetBatchReader driver (GoogleIoTTaskSource)
MANUAL_QA_OK
exit=0
```

Artifacts: `/tmp/production_sources_hook2_pytest.log`,
`/tmp/production_sources_hook2_ruff.log`,
`/tmp/production_sources_hook2_pyright.log`,
`/tmp/production_sources_hook2_diff.log`, and
`/tmp/production_sources_hook2_manual.log`.

Judgment: all owned-module behavior and quality gates passed on this direct rerun; no fix was
needed after inspection.

## Stop-hook 3 direct verification

Fresh execution from the current worktree produced the following binary observables:

```text
test -s .omo/evidence/production-sources.md: exit=0
sha256: ba915fff3f82f544cfd27786a1070c0425e7265c2f137a5359b890ab2e2b2563
pytest: .. [100%] / 2 passed in 13.39s / exit=0
ruff check: All checks passed! / exit=0
ruff format --check: 1 file already formatted / exit=0
basedpyright: 0 errors, 0 warnings, 0 notes / exit=0
```

Artifacts: `/tmp/production_sources_hook3_sha.log`,
`/tmp/production_sources_hook3_pytest.log`,
`/tmp/production_sources_hook3_ruff.log`, and
`/tmp/production_sources_hook3_pyright.log`.

Judgment: the evidence file is present and non-empty, and every fresh source-quality check exited
zero; no implementation change was required.
