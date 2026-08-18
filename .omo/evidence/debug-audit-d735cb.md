# Runtime debugging audit — exact SHA `d735cb092af1ece7292fa9d6b429c3ff82ee4bcd`

**AUDIT FAIL**

The release-trust and operational gates are green at the requested SHA, but a full
pytest gate could not be completed in this environment (`coverage.disposition` is
missing when the installed pytest coverage plugin loads; disabling plugins then
hung on the mounted `/mnt/d` filesystem and was terminated). The independently
captured production reverification is strong runtime evidence, but it identifies
the previously deployed source as `f010a798…`, not this exact SHA; therefore exact
SHA production provenance remains unproven.

## Environment and exact-SHA checks

- Repository: `/mnt/d/Github/celerates/digital-bast/v2-prod`
- `git rev-parse d735cb092af1ece7292fa9d6b429c3ff82ee4bcd` returned the requested SHA;
  current `HEAD` was the same SHA at audit start.
- Runtime: Python 3.12.13 via `uv`; Docker 28.3.3 and Compose v2.39.1 available.
- Exact archive invocation: `git archive --format=tar d735cb... -- compose.yaml scripts config/nginx/nginx.conf`.
  Extracted `scripts/deploy.sh` is mode `755` and executable; extracted hashes for
  `scripts/deploy.sh`, `compose.yaml`, and `config/nginx/nginx.conf` exactly match
  `git show d735cb...:<path> | sha256sum`.
- No repository files were edited other than this evidence receipt. Temporary
  archive/test files under `/tmp` were removed by traps; orphaned pytest processes
  from the hung attempt were terminated.

## Hypothesis matrix

### H1 — exact-SHA archive loses the deploy executable or carries stale assets

Distinguishing check: archive the requested SHA, inspect extracted mode and compare
content hashes with the commit objects. Result: `scripts/deploy.sh` extracted as
`-rwxr-xr-x` (`755`), and all three archived file hashes match the commit objects.
`tests/ops/release-trust.sh` also passed. **Rejected.**

### H2 — a mutable/local image bypasses digest trust

Distinguishing check: fake-Docker deployment harness must pull app services for a
registry digest, allow a local image only with `ALLOW_LOCAL_APP_IMAGE=1`, and reject
a mutable registry tag. `tests/ops/local-image-deploy.sh` passed; the script contains
the explicit local opt-in, `compose pull --policy always`, and immutable digest
validation. `tests/ops/release-trust.sh` passed. **Rejected.**

### H3 — production success is misleading while readiness, Prefect schedules,
rollback, or restore are stale

Distinguishing check: inspect independently captured production reverification, not
the original claim. It records preflight exit 0; active green with both slots
healthy; `/health/ready` 200; five named Prefect deployments each with one active
schedule and 20 flow runs; rollback dry-run targeting healthy blue; both app and
Prefect dumps restored with 7 and 36 public tables, respectively; zero reverify
databases/candidate trees/transfer archives. **Rejected for the recorded production
state**, with the provenance caveat above because those artifacts are tied to
`f010a798…`, not d735.

### H4 — CI/static gate failure hides a release defect

Distinguishing checks at d735: `compileall`, `ruff check`, `basedpyright`, shell
syntax, `scripts/check-ops.sh`, and all six ops harnesses (`release-trust`,
`local-image-deploy`, `rollback-slots`, `preflight-retention`, `backup-restore`,
`adversarial`) all exited 0. A plain `uv run pytest` did not reach test collection:
it failed with `ModuleNotFoundError: No module named 'coverage.disposition'` from
the installed `pytest_cov` plugin. Re-running with plugin autoload disabled hung in
`p9_client_rpc` on the `/mnt/d` mount and was stopped at the process level. **Static
gate rejected; full test gate unresolved (environment blocker).**

## Artifact sources

- Exact archive and object-hash transcript: this receipt's Environment section
  (commands and observed values above).
- Release-trust/ops harness sources and assertions: `tests/ops/release-trust.sh`,
  `tests/ops/local-image-deploy.sh`, `scripts/deploy.sh`.
- Independent production runtime: `.omo/evidence/deployment/reverification/01-runtime.txt`.
- Independent Prefect verification: `.omo/evidence/deployment/reverification/02-prefect.txt`.
- Independent restore verification: `.omo/evidence/deployment/reverification/03-backup-restore.txt`.
- Independent cleanup/rollback state: `.omo/evidence/deployment/reverification/04-cleanup-state.txt` and
  `.omo/evidence/deployment/reverification/REVERIFIED.md`.
- Prior manual-QA note identifying the production evidence SHA: `.omo/evidence/deployment/reverification/final-qa-review-manual-qa.md`.

## Cleanup

No service, credential, Docker image, source, or deployment state was changed.
Only this Markdown artifact remains; all ephemeral `/tmp` outputs and hung local
pytest processes were cleaned up.
