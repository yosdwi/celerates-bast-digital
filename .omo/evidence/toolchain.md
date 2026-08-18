# Isolated uv/Python toolchain

## Result

`DoneClaim: PASS` — an official standalone uv binary and managed CPython 3.12 are usable without system or global package installation. All toolchain files and caches are under `/tmp/digital-bast-v2-toolchain`.

The installer script was fetched from `https://astral.sh/uv/install.sh`; its pinned release is uv `0.12.1`.

Reusable command prefix from `/mnt/d/Github/celerates/digital-bast/v2-prod`:

```bash
source /tmp/digital-bast-v2-toolchain/env.sh
```

The prefix prepends `/tmp/digital-bast-v2-toolchain/bin` and sets `UV_PYTHON_INSTALL_DIR`, `UV_CACHE_DIR`, `UV_PYTHON_PREFERENCE=only-managed`, `UV_NO_CONFIG=1`, `UV_NO_PROJECT=1`, and `UV_NO_ENV_FILE=1`. For project commands, set `UV_PROJECT_ENVIRONMENT=/tmp/digital-bast-v2-toolchain/project-venv` so any environment remains outside the checkout.

## Evidence ledger

| Success criterion | Exact scenario and invocation | Binary observable | Captured artifact |
|---|---|---|---|
| Official uv binary isolated under `/tmp` | `UV_INSTALL_DIR=/tmp/digital-bast-v2-toolchain/bin UV_NO_MODIFY_PATH=1 UV_DISABLE_UPDATE=1 sh /tmp/digital-bast-v2-toolchain/logs/uv-install.sh --quiet` | `/tmp/digital-bast-v2-toolchain/bin/uv` exists; SHA-256 `92face6b1f0462ad911857957bd168cd4ae45515e2a2cb3fcc3ecbda3d4d82b1` | `/tmp/digital-bast-v2-toolchain/logs/uv-install.sh`; `/tmp/digital-bast-v2-toolchain/logs/uv-release.json` |
| uv executable/version | `source /tmp/digital-bast-v2-toolchain/env.sh; command -v uv; uv --version` from target | `command -v` returned `/tmp/digital-bast-v2-toolchain/bin/uv`; `uv 0.12.1 (x86_64-unknown-linux-gnu)` | `/tmp/digital-bast-v2-toolchain/logs/verification-final.log` |
| Managed Python 3.12 provisioned under `/tmp` | `source /tmp/digital-bast-v2-toolchain/env.sh; uv python install 3.12 --no-bin --verbose` | `Python 3.12 is already installed`; `uv python list --only-installed` resolves to `/tmp/digital-bast-v2-toolchain/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12` | `/tmp/digital-bast-v2-toolchain/logs/python-install.log`; `/tmp/digital-bast-v2-toolchain/logs/python-install-nobin.log`; `/tmp/digital-bast-v2-toolchain/logs/python-list.log` |
| Required run command | `source /tmp/digital-bast-v2-toolchain/env.sh; UV_PROJECT_ENVIRONMENT=/tmp/digital-bast-v2-toolchain/project-venv uv run --python 3.12 python --version` from target | `Python 3.12.13` | `/tmp/digital-bast-v2-toolchain/logs/verification-final.log` |
| Run uses the managed interpreter, not system Python | `source /tmp/digital-bast-v2-toolchain/env.sh; UV_PROJECT_ENVIRONMENT=/tmp/digital-bast-v2-toolchain/project-venv uv run --python 3.12 python -c 'import sys; print(sys.executable); print(sys.prefix)'` | `sys.executable=/tmp/digital-bast-v2-toolchain/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12`; `managed_python_path=PASS` | `/tmp/digital-bast-v2-toolchain/logs/verification-final.log` |
| No user-local Python link remains | `source /tmp/digital-bast-v2-toolchain/env.sh; uv python install 3.12 --no-bin`; `test ! -e /home/yosdwi/.local/bin/python3.12` | `user_local_python_link_absent=PASS` | `/tmp/digital-bast-v2-toolchain/logs/python-install-nobin.log` |
| No checkout mutation from verification | `git status --short` before/after the required run command; compare with `cmp` | `git_status_unchanged=PASS`; shared ignored `.venv` stat also unchanged (`target_venv_unchanged=PASS`) | `/tmp/digital-bast-v2-toolchain/logs/git-status-final-before.txt`; `/tmp/digital-bast-v2-toolchain/logs/git-status-final-after.txt`; `/tmp/digital-bast-v2-toolchain/logs/verification-final.log` |

## Notes

- The first managed-Python install briefly created `/home/yosdwi/.local/bin/python3.12`; it was verified as a symlink into this `/tmp` tree and removed immediately. The subsequent `--no-bin` invocation proves the isolated installation does not create a user-local executable link.
- The checkout already had a shared ignored `.venv` from concurrent project verification (mtime `2026-08-03 07:56:24 +0700`); it was left intact per coordination and was not used by the required run command (`sys.executable` points into `/tmp`).
- No `uv lock` or `uv sync` command was run by this task, honoring the instruction not to create/update `uv.lock` yet. Existing sibling-worker changes, including any existing `uv.lock`, were not edited.
