# Server preflight capacity documentation commit

## Scenario

Commit only the correction to the server preflight capacity guidance.

## Commands and observables

```sh
git diff --cached --name-status
git diff --cached -- docs/server-preflight.md
git diff --cached --check
rg -n -i --glob '!\\.omo/**' --glob '!diff.png' '(150[[:space:]]*GB|150GB|root filesystem of at least 150)' .
rg -n -i 'at least 20 GB available|no minimum total root-filesystem capacity' docs/server-preflight.md
git commit -m 'Correct server preflight capacity guidance'
git log -1 --format='%H%n%s'
git status --short
git rev-list --left-right --count HEAD...origin/main
```

Observed:

- The staged scope was exactly `docs/server-preflight.md` (`1 insertion`, `1 deletion`).
- The sole change removes the stale 150 GB total-capacity requirement and states both `at least 20 GB available` and `no minimum total root-filesystem capacity`.
- `git diff --cached --check` exited 0.
- The stale-policy `rg` scan returned no source-tree matches; the required replacement wording was present on line 3 of the document.
- Commit created: `66e1ce670db8019489c8eeb6430718ececf827f0` — `Correct server preflight capacity guidance`.
- Worktree status after commit contains only untracked `.omo/` and `diff.png`; neither was staged or committed.
- `HEAD...origin/main` is `2 0`, and no push was run.

## Judgment

The requested one-file follow-up documentation commit exists, has the intended policy-only diff, passes the requested static validation, and remains local.

## Direct re-verification (2026-08-03)

The following command was executed after this record was created:

```sh
git log -1 --format='%H%n%s'
git diff-tree --no-commit-id --name-status -r HEAD
git show --check --format=oneline HEAD
rg -n -i --glob '!\.omo/**' --glob '!diff.png' '(150[[:space:]]*GB|150GB|root filesystem of at least 150)' .
rg -n -i 'at least 20 GB available|no minimum total root-filesystem capacity' docs/server-preflight.md
git status --short
git rev-list --left-right --count HEAD...origin/main
git rev-parse --abbrev-ref '@{upstream}'
```

Exact observables (sensitive values are not emitted):

```text
COMMIT
66e1ce670db8019489c8eeb6430718ececf827f0
Correct server preflight capacity guidance
SCOPE
M\tdocs/server-preflight.md
WHITESPACE
66e1ce670db8019489c8eeb6430718ececf827f0 Correct server preflight capacity guidance
STALE_POLICY
no matches
REPLACEMENT_POLICY
line 3 contains both required policy phrases
STATUS
?? .omo/
?? diff.png
UPSTREAM
2\t0
origin/main
```

Judgment: the commit still has exactly one changed path, the stale policy remains absent from the source tree, the replacement policy remains present, the patch remains whitespace-clean, and it has not been pushed.
