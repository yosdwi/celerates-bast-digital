# Bootstrap repository evidence

## Initial repository

- Scenario: create an isolated V2 Git repository and publish its required README-only initial commit.
- Invocation: `git init --initial-branch=main /mnt/d/Github/celerates/digital-bast/v2-prod`, `git commit -m 'Initial README'`, and `git push --set-upstream origin main`.
- Observable: Git created commit `f3741d1 Initial README`; `git ls-remote --heads origin main` returned `f3741d18b009c3aae872a2986288cc439e01fbea refs/heads/main`; upstream resolves to `origin/main`.
- Artifact: both `git ls-files` and `git ls-tree -r --name-only f3741d1` printed only `README.md`.

## Shared scaffold

- Scenario: validate the strict Python project manifest and empty import packages.
- Invocation: `npx --yes @taplo/cli check pyproject.toml` and `python3 -m compileall -q src/digital_bast`.
- Observable: Taplo completed with `found files total=1 excluded=0`; compileall completed with `EMPTY_PACKAGE_COMPILE_OK`.
- Artifact: `pyproject.toml` and `src/digital_bast/` in this repository.

## Environment limitation

- Scenario: generate the uv lockfile.
- Invocation: `command -v uv`.
- Observable: no executable was found, so `uv.lock` was intentionally not generated from an unverifiable resolver environment.
- Artifact: the manifest is ready for `uv lock` in the target Python 3.12 container or CI environment.

## Direct re-verification

- Scenario: verify the claimed repository state after completion.
- Invocation: `git status --short; git diff --check; git log --oneline --all; git ls-files; git ls-tree -r --name-only f3741d1; git remote -v; git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}'; git ls-remote --heads origin main; npx --yes @taplo/cli check pyproject.toml; python3 -m compileall -q src/digital_bast`.
- Observable: `git log --oneline --all` returned `f3741d1 Initial README`; both tracked-file commands returned only `README.md`; the upstream resolved to `origin/main`; remote main resolved to `f3741d18b009c3aae872a2986288cc439e01fbea`; Taplo found and validated one manifest; compileall returned `EMPTY_PACKAGE_COMPILE_OK`; `git diff --check` returned no diagnostics.
- Artifact: this verification record and the listed repository files.

## Captured terminal output

```text
$ git log --oneline --all
f3741d1 Initial README
$ git ls-files
README.md
$ git ls-tree -r --name-only f3741d1
README.md
$ git remote -v
origin https://github.com/yosdwi/celerates-bast-digital.git (fetch)
origin https://github.com/yosdwi/celerates-bast-digital.git (push)
$ git rev-parse --abbrev-ref --symbolic-full-name @{upstream}
origin/main
$ git ls-remote --heads origin main
f3741d18b009c3aae872a2986288cc439e01fbea refs/heads/main
$ git diff --check
git_diff_check_exit=0
$ npx --yes @taplo/cli check pyproject.toml
INFO taplo:lint_files:collect_files: found files total=1 excluded=0 cwd="/mnt/d/Github/celerates/digital-bast/v2-prod"
taplo_exit=0
$ python3 -m compileall -q src/digital_bast
compileall_exit=0
```

The repository was created as required: `f3741d1` is the only commit and its complete tree contains only `README.md`. The locally untracked scaffold deliberately remains outside that pushed initial commit for the other workers to use.

## Runtime dependency amendment

- Scenario: add runtime support for Jinja templates, multipart form parsing, and holiday calculations.
- Invocation: `npx --yes @taplo/cli check pyproject.toml; grep -Fx '    "jinja2>=3.1,<4",' pyproject.toml; grep -Fx '    "python-multipart>=0.0.20,<1",' pyproject.toml; grep -Fx '    "holidays>=0.76,<1",' pyproject.toml; python3 -m compileall -q src/digital_bast; git diff --check; git status --short`.
- Observable: Taplo completed successfully; each exact dependency line was returned; compileall and `git diff --check` exited 0. Final status lists only uncommitted shared scaffold paths: `.dockerignore`, `.env.example`, `.gitignore`, `.omo/`, `.python-version`, `pyproject.toml`, and `src/`.
- Artifact: `pyproject.toml` contains `jinja2>=3.1,<4`, `python-multipart>=0.0.20,<1`, and `holidays>=0.76,<1`.

```text
$ npx --yes @taplo/cli check pyproject.toml
INFO taplo:lint_files:collect_files: found files total=1 excluded=0 cwd="/mnt/d/Github/celerates/digital-bast/v2-prod"
taplo_exit=0
$ grep runtime dependencies
    "holidays>=0.76,<1",
    "jinja2>=3.1,<4",
    "python-multipart>=0.0.20,<1",
dependency_grep_exit=0
$ python3 -m compileall -q src/digital_bast
compileall_exit=0
$ git diff --check
diff_check_exit=0
$ git status --short
?? .dockerignore
?? .env.example
?? .gitignore
?? .omo/
?? .python-version
?? pyproject.toml
?? src/
```

## Hatch package discovery correction

- Scenario: make Hatch wheel package discovery explicit for the hyphenated distribution and underscore source package.
- Invocation: `npx --yes @taplo/cli check pyproject.toml; grep -A 1 -Fx '[tool.hatch.build.targets.wheel]' pyproject.toml; python3 -m compileall -q src/digital_bast; python3 -c 'import hatchling'`.
- Observable: Taplo parser and source compilation exited `0`; the configuration printed `[tool.hatch.build.targets.wheel]` followed by `packages = ["src/digital_bast"]`. The installed Python 3.10 runtime does not provide Hatchling, so local wheel construction cannot run; that is an environment limitation, not a metadata validation failure.
- Artifact: `pyproject.toml` lines in the Hatch wheel target configuration.

```text
$ npx --yes @taplo/cli check pyproject.toml
INFO taplo:lint_files:collect_files: found files total=1 excluded=0 cwd="/mnt/d/Github/celerates/digital-bast/v2-prod"
taplo_exit=0
$ grep -A1 [tool.hatch.build.targets.wheel] pyproject.toml
[tool.hatch.build.targets.wheel]
packages = ["src/digital_bast"]
hatch_config_grep_exit=0
$ python3 -m compileall -q src/digital_bast
compileall_exit=0
$ python3 -c import hatchling
ModuleNotFoundError: No module named 'hatchling'
hatchling_import_exit=1
```

## Final Hatch re-verification

```text
$ grep -A1 -Fx [tool.hatch.build.targets.wheel] pyproject.toml
[tool.hatch.build.targets.wheel]
packages = ["src/digital_bast"]
hatch_config_exit=0
$ npx --yes @taplo/cli check pyproject.toml
INFO taplo:lint_files:collect_files: found files total=1 excluded=0 cwd="/mnt/d/Github/celerates/digital-bast/v2-prod"
taplo_exit=0
$ python3 -m compileall -q src/digital_bast
compileall_exit=0
$ git diff --check
diff_check_exit=0
```

The explicit package mapping remains present and both applicable checks passed. The concurrent worktree now includes additional untracked application files from other workers; they were observed only and not modified by this task.

## Evidence integrity check

```text
$ test -s .omo/evidence/bootstrap-repository.md
evidence_nonempty_exit=0
$ sha256sum pyproject.toml .omo/evidence/bootstrap-repository.md
87815754fa63e91c66b874b259a0c4059cf47a4971211f3c4038015180821b33  pyproject.toml
3c7f663cc8603b07a203e28050d8decf1bbe3d2c4ff52906baf09578d2c661e5  .omo/evidence/bootstrap-repository.md
$ grep -F packages mapping
packages = ["src/digital_bast"]
mapping_grep_exit=0
$ npx --yes @taplo/cli check pyproject.toml
INFO taplo:lint_files:collect_files: found files total=1 excluded=0 cwd="/mnt/d/Github/celerates/digital-bast/v2-prod"
taplo_exit=0
```

The evidence file was nonempty before this record was added; the pre-update checks confirm both the package mapping and TOML validity.

## Ruff docstring-policy verification

- Scenario: ensure the Ruff configuration honors the project policy that authored source contains no comments or docstrings.
- Invocation: `source /tmp/digital-bast-v2-toolchain/env.sh; uvx ruff check src/digital_bast` followed by a probe for diagnostic codes beginning with `D`, plus `npx --yes @taplo/cli check pyproject.toml` and `git diff --check`.
- Observable: `d_family_diagnostics=absent`, while the full command exit was `1` because concurrent source files currently have unrelated strict Ruff diagnostics. Taplo and the whitespace check exited `0`.
- Artifact: `[tool.ruff.lint]` in `pyproject.toml` now uses `ignore = ["COM812", "CPY001", "D", "FBT001", "FBT002", "FIX002", "ISC001", "TD002", "TD003"]`.

```text
$ uvx ruff check src/digital_bast (D-family diagnostic probe)
ruff_exit=1
d_family_diagnostics=absent
I001 [*] Import block is un-sorted or un-formatted
UP035 [*] Import from `collections.abc` instead: `Sequence`
TC001 Move application import `digital_bast.flows.contracts.RunContextFactory` into a type-checking block
T201 `print` found
PLR0911 Too many return statements (7 > 6)
$ npx --yes @taplo/cli check pyproject.toml
taplo_exit=0
$ git diff --check
diff_check_exit=0
```
