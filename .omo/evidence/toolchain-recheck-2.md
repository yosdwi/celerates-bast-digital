# Toolchain direct verification 2

## Verdict

`DoneClaim: PASS` — all required isolated-toolchain assertions passed on the second direct rerun.

## Scenario

Working directory: `/mnt/d/Github/celerates/digital-bast/v2-prod`.

Environment and invocations:

```bash
source /tmp/digital-bast-v2-toolchain/env.sh
export UV_PROJECT_ENVIRONMENT=/tmp/digital-bast-v2-toolchain/project-venv
uv --version
uv run --python 3.12 python --version
uv run --python 3.12 python -c 'import sys; print(sys.executable); print(sys.prefix); print(sys.version); assert sys.version_info[:2] == (3,12); assert sys.executable.startswith("/tmp/digital-bast-v2-toolchain/python/")'
uv python list --only-installed
sha256sum /tmp/digital-bast-v2-toolchain/bin/uv
test "$UV_PYTHON_INSTALL_DIR" = /tmp/digital-bast-v2-toolchain/python
test "$UV_CACHE_DIR" = /tmp/digital-bast-v2-toolchain/cache
test ! -e /home/yosdwi/.local/bin/python3.12
test ! -e /tmp/digital-bast-v2-toolchain/project-venv
```

## Observed output

- uv path: `/tmp/digital-bast-v2-toolchain/bin/uv`.
- uv version: `uv 0.12.1 (x86_64-unknown-linux-gnu)`.
- Python version: `Python 3.12.13`.
- Managed executable: `/tmp/digital-bast-v2-toolchain/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12`.
- Managed prefix: `/tmp/digital-bast-v2-toolchain/python/cpython-3.12.13-linux-x86_64-gnu`.
- uv SHA-256: `92face6b1f0462ad911857957bd168cd4ae45515e2a2cb3fcc3ecbda3d4d82b1`.
- `all_assertions=PASS`.

## Captured artifact

Full command output and timestamp are recorded at `/tmp/digital-bast-v2-toolchain/logs/hook-recheck-2.log`.
