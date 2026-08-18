## LegacyIoTPicUpdater evidence

- Scenario: injected sync executor receives the direct Step10 relation SQL and returns its inserted count.
- Invocation: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -p pytest_asyncio.plugin tests/unit/infrastructure/test_legacy_pic.py -q`
- Binary observable: `1 passed in 12.15s`.
- Contract artifact: `src/digital_bast/infrastructure/legacy_pic.py` contains one static `INSERT ... SELECT DISTINCT`, trigram `similarity`, `employee.id IS NOT NULL`, existing-link exclusion, and `ON CONFLICT DO NOTHING`.
- Static checks: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` pass for the implementation and focused test; `compileall` exits 0.
