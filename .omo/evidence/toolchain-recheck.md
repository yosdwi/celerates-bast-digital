# Toolchain completion recheck

## Verdict

`DoneClaim: PASS` — direct rerun succeeded after the completion hook challenge.

## Scenario and invocation

From `/mnt/d/Github/celerates/digital-bast/v2-prod`, the exact environment prefix and commands were run:

```bash
source /tmp/digital-bast-v2-toolchain/env.sh
export UV_PROJECT_ENVIRONMENT=/tmp/digital-bast-v2-toolchain/project-venv
uv --version
uv run --python 3.12 python --version
uv run --python 3.12 python -c 'import sys; print(sys.executable); print(sys.prefix); assert sys.version_info[:2] == (3,12); assert "/tmp/digital-bast-v2-toolchain/python/" in sys.executable'
uv python list --only-installed
sha256sum /tmp/digital-bast-v2-toolchain/bin/uv
test ! -e /home/yosdwi/.local/bin/python3.12
test ! -e /tmp/digital-bast-v2-toolchain/project-venv
```

## Binary observables

- `command -v uv` returned `/tmp/digital-bast-v2-toolchain/bin/uv`.
- `uv --version` returned `uv 0.12.1 (x86_64-unknown-linux-gnu)`.
- `uv run --python 3.12 python --version` returned `Python 3.12.13`.
- The interpreter path was `/tmp/digital-bast-v2-toolchain/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12`; the assertion passed.
- `uv python list --only-installed` listed only the `/tmp` managed installation.
- uv SHA-256 was `92face6b1f0462ad911857957bd168cd4ae45515e2a2cb3fcc3ecbda3d4d82b1`.
- The user-local `python3.12` link and temporary project environment were absent.

## Captured artifact

Complete stdout/stderr is recorded at `/tmp/digital-bast-v2-toolchain/logs/hook-recheck.log`.
