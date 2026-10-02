# Code quality review — Digital BAST v2

**Reviewed commit:** `f010a7983107c6165916593cbb3dd44649d93f70`  
**Comparison parent:** `f3741d18b009c3aae872a2986288cc439e01fbea`  
**Verdict:** BLOCK / REQUEST_CHANGES

## Scope and verification

The requested commit SHA and parent SHA were independently confirmed. The exact
commit is a 149-file initial implementation. The worktree contains untracked
review artifacts only; review conclusions use the commit tree, not those
artifacts. Cheap read-only gates passed locally: Ruff, basedpyright, shell
syntax checking, and Compose config when supplied the required configuration.
The full suite was intentionally not run.

### Skill-perspective check

The required `omo:remove-ai-slops` and `omo:programming` perspectives were
loaded and applied. The diff violates the remove-ai-slops perspective because
the operations tests give false confidence while the CI path never executes
them, and because several checks merely grep for implementation phrases. It
also violates the programming perspective: a production retention boundary is
not connected to the schema it executes against. No untyped escape hatch was a
release blocker in the inspected Python path.

## CRITICAL

1. **Committed operational scripts are non-executable, while the product runs
   them directly.** Every `scripts/*.sh` file has mode `100644` in the reviewed
   commit (including `scripts/deploy.sh`, `scripts/check-ops.sh`, and
   `scripts/postgres-entrypoint.sh`). GitHub checks out that mode, so CI fails
   at [ci.yml:31](../../.github/workflows/ci.yml#L31), both release SSH commands
   fail at [release.yml:80](../../.github/workflows/release.yml#L80) and
   [release.yml:107](../../.github/workflows/release.yml#L107), and Postgres
   cannot exec its bind-mounted entrypoint at [compose.yaml:96](../../compose.yaml#L96)
   and [compose.yaml:109](../../compose.yaml#L109). This prevents CI, database
   initialization, and deployment from operating. Set executable Git modes for
   all directly invoked scripts (or consistently invoke an interpreter).

2. **The required CI quality job is intrinsically misconfigured even if script
   modes are fixed.** [check-ops.sh:11](../../scripts/check-ops.sh#L11) runs
   Compose interpolation without `SECRETS_GID`, although [compose.yaml:10](../../compose.yaml#L10)
   declares it mandatory. Reproduced directly: `scripts/check-ops.sh` exits 1
   with `required variable SECRETS_GID is missing`. The workflow neither sets
   it nor creates the secret fixture files required by Compose. Consequently
   [ci.yml:31](../../.github/workflows/ci.yml#L31) cannot become green.

## HIGH / MAJOR

1. **Scheduled retention always fails against the committed schema.**
   [retention.sh:26](../../scripts/retention.sh#L26) deletes from
   `nocodb_audit_events`, but the only migration creates no such table
   ([20260803_0001_durable_state.py:14](../../migrations/versions/20260803_0001_durable_state.py#L14)
   through [line 78](../../migrations/versions/20260803_0001_durable_state.py#L78)).
   With `ON_ERROR_STOP`, the transaction aborts before it can prune generation
   plans. Either migrate and populate the audit table, or remove/replace this
   deletion according to the approved retention model.

2. **Backup and retention default to a database the Compose bootstrap never
   creates.** Postgres is initialized with `POSTGRES_DB=postgres` at
   [compose.yaml:100](../../compose.yaml#L100), while
   [postgres-init.sh:13](../../scripts/postgres-init.sh#L13)-[line 16](../../scripts/postgres-init.sh#L16)
   create `digital_bast_app` and `digital_bast_prefect`. In contrast,
   [backup.sh:40](../../scripts/backup.sh#L40) and
   [retention.sh:24](../../scripts/retention.sh#L24) default to
   `digital_bast`. On the documented/default configuration these lifecycle
   procedures fail with database-not-found, so recovery/retention guarantees
   are not met. Use the application database consistently or require the
   correct database variable.

## MEDIUM

1. **Operations tests are not part of CI and several only check text/log
   shapes.** Pytest is limited to Python tests in [pyproject.toml:84](../../pyproject.toml#L84),
   and CI runs only `pytest` plus `check-ops.sh`
   ([ci.yml:30](../../.github/workflows/ci.yml#L30)-[line 31](../../.github/workflows/ci.yml#L31)).
   The meaningful shell scenarios under `tests/ops/` are never invoked.
   Further, [check-ops.sh:22](../../scripts/check-ops.sh#L22)-[line 24](../../scripts/check-ops.sh#L24)
   only grep wording in `deploy.sh`, which is a brittle implementation-mirroring
   test rather than proof that rollback/migration behavior works. Add a CI step
   that runs the ops scenarios, and retain a real Compose-level smoke path for
   the mounted PostgreSQL entrypoint and blue-green switch.

2. **Migration ordering weakens blue-green compatibility.** The target web
   slot must pass health and shadow checks before Alembic runs
   ([deploy.sh:63](../../scripts/deploy.sh#L63)-[line 74](../../scripts/deploy.sh#L74)).
   Any legitimate release that needs its schema migration to become ready is
   rejected before migration. Conversely, migration is applied while the old
   slot is still active, with no compatibility check of that old version. This
   is scope-critical deployment logic; explicitly define/enforce an
   expand-contract compatibility policy and test both cases.

## LOW

No additional low-severity findings were recorded.

## Recommendation

`codeQualityStatus: BLOCK`  
`recommendation: REQUEST_CHANGES`

**Blockers:** correct committed executable modes; make the CI operations check
self-contained; repair retention/schema and lifecycle database targeting.
