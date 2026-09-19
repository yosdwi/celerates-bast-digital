# Toolchain direct verification 3

`DoneClaim: PASS` — the third direct execution passed all isolation and version assertions.

Scenario: from `/mnt/d/Github/celerates/digital-bast/v2-prod`, source `/tmp/digital-bast-v2-toolchain/env.sh`, set `UV_PROJECT_ENVIRONMENT=/tmp/digital-bast-v2-toolchain/project-venv`, then run:

```text
uv --version
uv run --python 3.12 python --version
uv run --python 3.12 python -c 'import sys; print("exe="+sys.executable); print("prefix="+sys.prefix); assert sys.version_info[:2] == (3,12); assert sys.executable.startswith("/tmp/digital-bast-v2-toolchain/python/")'
uv python list --only-installed
sha256sum /tmp/digital-bast-v2-toolchain/bin/uv
test -x /tmp/digital-bast-v2-toolchain/bin/uv
test -d /tmp/digital-bast-v2-toolchain/python/cpython-3.12.13-linux-x86_64-gnu
test ! -e /home/yosdwi/.local/bin/python3.12
test ! -e /tmp/digital-bast-v2-toolchain/project-venv
```

Observed binary output:

- uv: `0.12.1 (x86_64-unknown-linux-gnu)` at `/tmp/digital-bast-v2-toolchain/bin/uv`.
- Python: `3.12.13`.
- Executable: `/tmp/digital-bast-v2-toolchain/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12`.
- uv SHA-256: `92face6b1f0462ad911857957bd168cd4ae45515e2a2cb3fcc3ecbda3d4d82b1`.
- Final assertion: `verification=PASS`.

Captured raw output: `/tmp/digital-bast-v2-toolchain/logs/hook-recheck-3.log`.
