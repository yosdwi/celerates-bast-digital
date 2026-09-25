# Local source commit verification

Date: 2026-08-03 (Asia/Jakarta)

## Scenario

Verify the local, source-only Digital BAST v2 commit before any push.

## Invocation and binary observables

```sh
git log -1 --format='%H%n%s'
git diff-tree --no-commit-id --name-only -r HEAD | awk '...'
git show --check --format=oneline HEAD
git status --short
git rev-list --left-right --count HEAD...origin/main
git rev-parse --abbrev-ref '@{upstream}'
SECRETS_GID=0 scripts/check-ops.sh
sh tests/ops/adversarial.sh
sh tests/ops/preflight-retention.sh
sh tests/ops/rollback-slots.sh
sh tests/ops/local-image-deploy.sh
```

Observed:

- Commit: `f010a7983107c6165916593cbb3dd44649d93f70` — `Initial Digital BAST v2 implementation`.
- Commit tree audit: `tracked commit paths=149 forbidden=0`; the forbidden set covered `.omo`, `diff.png`, `.env`, secret/credential paths, private-key extensions, runtime databases, and archive extensions.
- `git show --check` exited 0, so the committed patch has no whitespace errors.
- All five lightweight operations gates exited 0: static checks, adversarial checks, preflight/retention, rollback slots, and local-image deploy.
- Upstream is `origin/main`; `HEAD...origin/main` is `1 0` (one local-only commit, no remote commits missing locally).
- Current non-ignored worktree items are `.omo/` and `diff.png`; neither is committed. No source paths are staged or modified.
- `gitleaks` is unavailable in this environment. Before the commit, targeted staged-content scans for private-key and known live-token signatures passed without emitting values.

## Judgment

The required local commit exists, contains the complete 149-path source snapshot, excludes the stated forbidden artifacts, and has passed the repository's cheap shell/ops gates. It remains unpushed.
