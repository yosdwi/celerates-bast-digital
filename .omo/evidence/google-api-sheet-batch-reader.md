# Google Sheets batch reader evidence

Scenario: a fake discovery service and fake service-account loader exercise the production adapter without network access.

Invocation:

```text
timeout 45 .venv/bin/python <inline adapter-driver>
```

Binary observables:

```text
{'build': (('sheets', 'v4'), {'credentials': ('credentials.json', {'scopes': ['https://www.googleapis.com/auth/spreadsheets.readonly']}), 'cache_discovery': False}), 'batch': {'spreadsheetId': 'sheet-id', 'ranges': ['Sheet!A:A', 'Sheet!B:B'], 'majorDimension': 'COLUMNS', 'valueRenderOption': 'FORMATTED_VALUE'}}
{'valueRanges': [{'values': [['Date'], ['2026/08/03']]}]}
status:0
```

The first line proves Sheets v4 discovery, readonly credentials, discovery-cache disabling, and all required `batchGet` options. The second proves the adapter returns the executed `GooglePayload` unchanged.

Static validation:

```text
.venv/bin/ruff check src/digital_bast/infrastructure/google_api.py
All checks passed!
.venv/bin/ruff format --check src/digital_bast/infrastructure/google_api.py
1 file already formatted
uv run --no-project --with basedpyright basedpyright --project pyproject.toml src/digital_bast/infrastructure/google_api.py
0 errors, 0 warnings, 0 notes
```

## Verification rerun

Invocation: `set -o pipefail; .venv/bin/ruff check src/digital_bast/infrastructure/google_api.py; .venv/bin/ruff format --check src/digital_bast/infrastructure/google_api.py; uv run --no-project --with basedpyright basedpyright --project pyproject.toml src/digital_bast/infrastructure/google_api.py typings/googleapiclient/discovery.pyi; .venv/bin/python -m py_compile src/digital_bast/infrastructure/google_api.py`.

Captured output:

```text
=== ruff check ===
All checks passed!
=== ruff format ===
1 file already formatted
=== basedpyright ===
0 errors, 0 warnings, 0 notes
=== py_compile ===
STATIC_STATUS=0
```

Manual invocation: `timeout 45 .venv/bin/python <fake discovery/service-account driver>`.

Captured output:

```text
{'build': (('sheets', 'v4'), {'credentials': ('credentials.json', {'scopes': ['https://www.googleapis.com/auth/spreadsheets.readonly']}), 'cache_discovery': False}), 'batch': {'spreadsheetId': 'sheet-id', 'ranges': ['Sheet!A:A', 'Sheet!B:B'], 'majorDimension': 'COLUMNS', 'valueRenderOption': 'FORMATTED_VALUE'}}
{'valueRanges': [{'values': [['Date'], ['2026/08/03']]}]}
MANUAL_STATUS=0
```

Judgment: all requested static gates exit zero. The manual output proves the service-account readonly scope, Sheets v4 service construction, disabled discovery cache, list-normalized ranges, required rendering options, and unchanged executed payload.
