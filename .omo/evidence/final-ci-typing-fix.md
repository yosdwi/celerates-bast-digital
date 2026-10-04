# Final CI typing fix evidence

## Scope and runtime neutrality

Changed only the local type surface and lint configuration:

- `typings/googleapiclient/discovery.pyi`: remove the ineffective stub future import.
- `pyproject.toml`: ignore only `N802` and `N803` for the Google discovery stub, whose
  `batchGet`, `spreadsheetId`, `majorDimension`, `valueRenderOption`, and `serviceName`
  spellings are third-party API contract names.
- `typings/prefect_redis/messaging.pyi`: replace `**kwargs: Any` with the exact published
  consumer keyword parameters and a typed subscription `TypedDict`.
- `typings/holidays/__init__.pyi`: add only `country_holidays(country, *, years)` and its
  `items() -> ItemsView[date, str]` result needed by the production flow.

Scenario: runtime-source-diff. Invocation:
`git diff --name-only -- src/digital_bast`.
Binary observable: exit 0 and no runtime-source paths; the captured result is
`modified_runtime_sources=(none)`, proving no production runtime source was modified.
Artifact: `runtime-source-diff.txt` and
`runtime-source-diff.status` (`0`).

## Red baseline

Scenario: reported-CI-red-baseline. Invocation: `uv run ruff check .` followed by
`uv run basedpyright` at HEAD `ade4fd7` before these changes.
Binary observable: Ruff exited 1 with seven findings, and basedpyright exited 1 with nine
findings from the untyped `holidays` import.
Artifacts: `final-ci-typing-fix.ruff-red.txt` and
`final-ci-typing-fix.basedpyright-red.txt`.

## Green CI gates

Scenario: formatter gate. Invocation: `uv run ruff format --check .`.
Binary observable: exit 0, `136 files already formatted`.
Artifacts: `final-ci-typing-fix.ruff-format-green.txt` and
`final-ci-typing-fix.ruff-format-green.status`.

Scenario: lint gate. Invocation: `uv run ruff check .`.
Binary observable: exit 0, `All checks passed!`.
Artifacts: `final-ci-typing-fix.ruff-green.txt` and
`final-ci-typing-fix.ruff-green.status`.

Scenario: strict type gate. Invocation: `uv run basedpyright`.
Binary observable: exit 0, `0 errors, 0 warnings, 0 notes`.
Artifacts: `final-ci-typing-fix.basedpyright-green.txt` and
`final-ci-typing-fix.basedpyright-green.status`.

## Post-completion direct verification

Scenario: final-direct-CI-rerun. The three exact CI commands were rerun after the first
completion report:

- `uv run ruff format --check .` exited 0; observable: `139 files already formatted`;
  artifact: `post-completion-ci-typing/ruff-format.txt` and `.status`.
- `uv run ruff check .` exited 0; observable: `All checks passed!`; artifact:
  `post-completion-ci-typing/ruff-check.txt` and `.status`.
- `uv run basedpyright` exited 0; observable: `0 errors, 0 warnings, 0 notes`; artifact:
  `post-completion-ci-typing/basedpyright.txt` and `.status`.

The three status artifacts each contain `0`, and `git diff --check` exited 0.

## Focused runtime validation note

Scenario: focused production-flow pytest. Invocation:
`uv run pytest tests/unit/flows/test_production_context.py`.
Binary observable: exit 1 before collection because the existing virtual environment cannot
import `coverage.disposition`. Artifact: `final-ci-typing-fix.production-flow-tests.txt`.

Scenario: Indonesia holiday source invocation. Invocation:
`uv run python -c 'from digital_bast.flows.production import IndonesiaHolidaySource; holidays = IndonesiaHolidaySource().load(2026); assert holidays; print(f"holiday_count={len(holidays)}")'`.
Binary observable: exit 1 before the flow executes because the existing installed
`holidays` distribution cannot import `country_holidays`. Artifact:
`final-ci-typing-fix.indonesia-holiday-source.txt`.

The focused runtime commands cannot validate this environment because of the recorded
dependency-install failures. The runtime-source-diff scenario proves the production source is
unchanged; the required static CI gates above are green.
