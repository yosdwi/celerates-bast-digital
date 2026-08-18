# Final-review release trust and typing commit

## Scenario

Commit the final-review release workflow hardening, deploy executable mode, release-trust coverage, and scoped typing fixes only.

## Commands and observables

```sh
git diff --cached --name-status
git diff --cached --summary
git diff --cached --check
.venv/bin/python -c '... yaml.safe_load(release.yml) ...'
bash -n scripts/deploy.sh tests/ops/release-trust.sh
SECRETS_GID=0 scripts/check-ops.sh
sh tests/ops/release-trust.sh
sh tests/ops/local-image-deploy.sh
uv run ruff format --check .
uv run ruff check .
uv run basedpyright
git commit -m 'Harden release trust and typing checks'
```

Observed:

- Staged scope was exactly seven files. The staged path and recognized private-key/live-token signature audits passed; `.omo` and `diff.png` were not staged.
- `git diff --cached --check` exited 0.
- `release.yml` parsed through installed PyYAML, and `bash -n` passed for the changed deploy and release-trust scripts.
- Static operations, release-trust, and local-image deploy checks all exited 0.
- `uv run ruff format --check .`, `uv run ruff check .`, and `uv run basedpyright` all exited 0.
- Commit created: `d735cb092af1ece7292fa9d6b429c3ff82ee4bcd` — `Harden release trust and typing checks`.
- The only mode change is `scripts/deploy.sh` from `100644` to `100755`; `typings/holidays/__init__.pyi` was added at `100644`.
- Post-commit status contains only untracked `.omo/` and `diff.png`. `HEAD...origin/main` is `4 0`; no push was run.

## Committed files

```text
.github/workflows/release.yml
pyproject.toml
scripts/deploy.sh
tests/ops/release-trust.sh
typings/googleapiclient/discovery.pyi
typings/holidays/__init__.pyi
typings/prefect_redis/messaging.pyi
```

## Judgment

The requested seven-file final-review commit exists locally, passes all requested checks, and remains unpushed.
