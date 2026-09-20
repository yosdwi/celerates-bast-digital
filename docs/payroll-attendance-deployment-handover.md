# Payroll Attendance — Agentic Deployment Handover

This document is the execution handover for deploying the completed Payroll Attendance
Closing / WhatsApp Attendance Correction implementation.

Repository: `yosdwi/celerates-bast-digital`  
Working branch used to prepare this handover: `chore/session-20260918-fixes`  
Deployment-preparation baseline before this document: `6beb08151d6ef9bd8c414c7baf70d37786853a64`  
Handover date: 20 September 2026  
Timezone for operational timestamps: `Asia/Jakarta`

## Current release state

- P00–P44 implementation is complete.
- Production status is still **HOLD**.
- This handover is an execution guide, not permission to bypass the production gate.
- Normal release authority is:
  `main CI success -> Release workflow -> staging -> production`.
- Do not deploy this feature branch directly to production.
- Do not label the release `GO` merely because commands completed. Record factual
  evidence and leave the final release decision to the authorized release owner.

The deployment-preparation baseline includes two release-bundle corrections discovered
while auditing the real deployment path:

1. `compose.production.yaml` is now included and verified in exact release assets.
2. `bot-worker/` is now included and verified because `scripts/deploy.sh` rebuilds
   `bot-worker` from that local build context on every release.
3. `scripts/check-ops.sh` contains regression guards for those requirements.

---

## 0. Agentic execution contract

The deployment agent MUST follow these rules.

1. Read all authority documents listed below before changing or deploying anything.
2. Verify the approved release SHA before execution. If HEAD differs unexpectedly,
   STOP and inspect the delta before continuing.
3. Do not create a new feature branch, broad refactor, cleanup wave, or unrelated fix
   during deployment execution.
4. Do not force-push or rewrite release history.
5. Do not deploy directly from `chore/session-20260918-fixes` to production.
6. Do not silently bypass failing `main` CI, GitHub environment approvals, or the
   production `HOLD` decision.
7. Do not create a second Payroll scheduler/cron. Payroll runs inside the existing
   Prefect `pmo-notifications` deployment.
8. Do not delete, reset, copy over, or recreate WhatsApp LocalAuth as a recovery
   shortcut.
9. Do not blindly resend durable `UNKNOWN` WhatsApp deliveries.
10. Do not turn transport failure, source unavailability, or ambiguous delivery into
    Talent fault.
11. Do not move Payroll business truth into an LLM or create a second attendance
    projection for deployment convenience.
12. Do not automatically run an Alembic downgrade during application rollback.
13. Preserve evidence for every gate. A missing result is `NOT RUN`, not `PASS`.

If an instruction below conflicts with the currently checked-out code, STOP and use
current repository code plus the release owner as authority; do not guess.

---

## 1. Read before execution

Read in this order:

1. `docs/development-execution-standard.md`
2. `docs/payroll-attendance-implementation-plan.md`
3. `docs/payroll-attendance-current-checkpoint.md`
4. `docs/payroll-attendance-production-gate.md`
5. `docs/payroll-attendance-manual-acceptance.md`
6. this file: `docs/payroll-attendance-deployment-handover.md`

Also inspect the execution sources directly:

- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `compose.yaml`
- `compose.production.yaml`
- `scripts/preflight.sh`
- `scripts/check-ops.sh`
- `scripts/deploy.sh`
- `scripts/rollback.sh`
- `scripts/backup.sh`
- `scripts/restore-test.sh`
- `scripts/smoke.sh`
- `scripts/deploy-whatsapp-web-session.sh`
- `src/digital_bast/flows/deployments.py`
- `src/digital_bast/flows/notifications.py`
- `migrations/versions/20260920_0027_payroll_export_history.py`

---

## 2. Deployment topology and authority

### Main application

The normal application rollout is blue/green and is owned by `scripts/deploy.sh`.
The production compose authority is:

```text
COMPOSE_FILE=compose.yaml:compose.production.yaml
```

`scripts/deploy.sh`:

- takes an exclusive deployment lock;
- runs preflight unless explicitly skipped;
- identifies the currently active blue/green web slot;
- starts the candidate slot without moving public traffic;
- runs `alembic upgrade head` before shadow readiness;
- requires candidate health and `/health/ready` shadow readiness;
- rebuilds/recreates stateless `bot-worker` and health-checks it;
- validates nginx config;
- switches public traffic only after all pre-switch gates pass;
- verifies public `/health/ready` after the switch;
- rolls back web routing and `bot-worker` where applicable when a post-switch gate
  fails;
- restarts `worker` and `runner` after successful cutover.

The application rollout deliberately does **not** recreate WhatsApp session services.

### Automated release chain

`.github/workflows/release.yml` is triggered only by a **successful CI workflow on
`main`**. Its order is:

```text
main CI success
  -> build/push immutable application image to GHCR
  -> provenance/SBOM/attestation
  -> staging deployment
  -> production deployment
```

The release deploys the application image by digest, not by a mutable tag.

The exact remote release bundle must contain at least:

```text
compose.yaml
compose.production.yaml
scripts/
bot-worker/
config/nginx/nginx.conf
```

The host keeps `.env`, secrets, and `config/nginx/active-slot.conf` as persistent
runtime state outside the immutable release directory.

### WhatsApp runtime

The active Payroll transport is `whatsapp-web-session` / `whatsapp-web.js`.
It is a stateful singleton and has a separate deployment path:

```text
scripts/deploy-whatsapp-web-session.sh
```

It is mounted on the persistent `bot-bridge-data` volume with:

```text
BOT_DATA_DIR=/data
BOT_AUTH_DIR=/data/auth-whatsapp-web-js
```

The same persistent `/data` boundary also holds durable gateway receipt state.
Normal application blue/green deployment must not recreate this service.

### Scheduler

Do not create a Payroll-specific Prefect deployment.
The existing deployment is:

```text
name: pmo-notifications
cron: */15 * * * *
timezone: Asia/Jakarta
concurrency_limit: 1
```

`pmo-notifications` runs PMO notifications, Payroll Talent reminders, and Payroll
closing digest. When Payroll closing is disabled, the legacy Talent reminder path
continues. Once Payroll is enabled, Payroll becomes the sole scheduled Talent
reminder authority, including while Payroll is paused.

---

## 3. Mandatory HOLD-clearing validation before production

Do not use the historical P44 CI output as proof that the current release SHA passed
all tests. Re-run or obtain current evidence for the approved SHA.

### Backend / Python

From repository root:

```sh
uv sync --all-groups
uv run python -m compileall -q src tests
uv run ruff check .
uv run basedpyright
uv run pytest
SECRETS_GID=0 scripts/check-ops.sh
```

Known historical condition at the P44 checkpoint:

- repository-wide Ruff had 142 findings;
- the P38–P44 files were cleaned of new Ruff findings;
- because Ruff failed first in CI, basedpyright, full pytest, and check-ops were not
  reached by that quality job.

For release execution:

- any new finding in the release changes is a STOP condition;
- do not call the repository Ruff-green unless the command actually exits zero;
- automated Release will not start from `main` unless CI concludes success;
- therefore historical Ruff debt must either be remediated to CI success or handled
  through an explicit release-owner-approved quality-policy change/waiver. Do not
  bypass the CI/release chain silently.

### Frontend

The repository has `frontend/package-lock.json`. Run:

```sh
cd frontend
npm ci
npm run typecheck
npm test
npm run build
cd ..
```

Required evidence:

- TypeScript typecheck exit code;
- Vitest result/count;
- production Vite build result.

### WhatsApp runtime tests

Run the repository-defined test command for `whatsapp-web-session`:

```sh
cd whatsapp-web-session
npm test
cd ..
```

If dependencies must be installed first, follow the package/Dockerfile dependency
path already defined by the repository. Do not change the dependency source or
regenerate the dependency graph merely to make deployment validation easier.

### Migration rehearsal

Against a non-production/staging-equivalent database:

```sh
uv run alembic upgrade head
uv run alembic upgrade head
```

The second upgrade must also succeed. This verifies migration idempotency at the
Alembic execution level.

### Container/image evidence

Obtain a real application image build and scanner result for the approved SHA.
The historical CI container job failed during runner/action setup before repository
checkout/build, so that result is not product-image evidence.

A tooling waiver, if used, must be explicit and attributable to the release owner.
A setup failure must never be relabeled as a successful image scan.

---

## 4. Target-host preflight

Before backup, migration, or cutover, record:

```text
hostname
current Jakarta timestamp
approved release SHA
intended image digest
deploy path
current active blue/green slot
current container health summary
```

Then verify the runtime prerequisites.

### Required host conditions

`scripts/preflight.sh` requires:

- Docker daemon available;
- Docker Compose v2;
- default minimum 8 GB free on `/` unless `AVAILABLE_MIN_GB` is deliberately
  overridden;
- `SECRETS_GID` set;
- every required secret present;
- each secret mode exactly `0640`;
- every secret group matching `SECRETS_GID`;
- compose configuration valid.

Required secret filenames are currently:

```text
postgres_password
app_database_password
prefect_database_password
session_secret
app_database_dsn
legacy_database_dsn
prefect_database_dsn
prefect_api_auth
redis_url
redis_acl
nocodb_token
nocodb_database_dsn
sync_ingest_token
google_service_account.json
sqlserver_connection_string
groq_api_key
cloudflare_api_token
```

Use the existing secret store/path. Never paste secret values into a deployment
report or Git commit.

Run the real gate from the intended release directory:

```sh
SECRETS_GID=<expected-gid> SECRETS_DIR=<persistent-secret-dir> scripts/preflight.sh
```

Also run the static operational checks where the checkout has the full repository:

```sh
SECRETS_GID=0 scripts/check-ops.sh
```

If preflight or check-ops fails, STOP. Do not deploy with `--skip-preflight` merely
to make the rollout continue.

### Deployment lock

Normal application deployment uses:

```text
/tmp/digital-bast-deploy.lock
```

The WhatsApp session deploy uses a different lock:

```text
/tmp/digital-bast-deploy-whatsapp-web-session.lock
```

Do not break a live lock. Determine who owns the deployment first.

---

## 5. Payroll outbound safety before deployment

Before any production rollout, read current Payroll closing settings for the intended
scope, normally `default`:

```text
GET /api/talentops/v1/payroll/settings?scope_key=default
```

Record at least:

```text
enabled
paused
closing_day
reminder_hour
reminder_offsets
target_roles
next_day_ready_hour
desired_version
applied_version
```

Production deployment/acceptance must start with real outbound Payroll traffic
suppressed. Acceptable initial states are:

```text
enabled = false
```

or, for an already configured Payroll campaign:

```text
enabled = true
paused = true
```

Do not unpause as part of routine application deployment.

The intended closing model remains:

- cycle: day 21 through day 20 inclusive;
- closing day: 20;
- reminder milestones: H-5, H-3, H-1;
- day 20: final assessment/digest.

---

## 6. WhatsApp runtime safety snapshot

Before deployment, capture the System & Sync / API status from:

```text
GET /api/talentops/v1/system/whatsapp/operations
```

Record:

```text
alive
ready
connection
operator_action_required
operator_reason
recovery_state
recovery_reason
recovery_paused
last_probe_at
last_ready_at
last_ack_at
cooldown_until
recovery_attempts
recovery_max_attempts
owner_acquired
owner_conflict_id
storage_healthy
storage_reasons
free_bytes
free_inodes
receipt_store_healthy
receipt_store_error
receipt_sent
receipt_unknown
receipt_in_flight
transport
```

Mandatory safe state before enabling real Payroll outbound:

- intended runtime is the single owner (`owner_acquired` true, no unresolved owner
  conflict);
- storage is healthy;
- receipt store is healthy;
- LocalAuth is present/writable at `/data/auth-whatsapp-web-js`;
- the persistent `bot-bridge-data` volume is mounted;
- there is no unexplained in-flight backlog;
- any existing `UNKNOWN` receipts are understood as ambiguous outcomes and are not
  queued for blind resend.

Do not delete LocalAuth, receipt data, or Chromium state directories as a generic
fix. Use the bounded supervisor/operator controls first.

---

## 7. Backup and restore evidence before production migration

A backup existing somewhere is not sufficient. Produce current encrypted backup and
restore-test evidence.

### Backup

The repository backup script protects both application and Prefect databases:

```text
digital_bast_app
digital_bast_prefect
```

Run with operator-provided values through the secret/environment mechanism:

```sh
AGE_RECIPIENT='<configured-recipient>' \
BACKUP_REMOTE='<configured-rclone-remote>' \
scripts/backup.sh
```

Do not put the actual recipient private key or other credentials in Git.

Record:

- backup timestamp;
- encrypted local file names;
- off-host destination identifiers;
- successful `rclone` checksum verification.

### Restore test

For each fresh encrypted backup, restore into the isolated temporary database using:

```sh
BACKUP_FILE='<app-backup.dump.age>' \
BACKUP_DATABASE='digital_bast_app' \
AGE_IDENTITY_FILE='<identity-file>' \
scripts/restore-test.sh
```

and:

```sh
BACKUP_FILE='<prefect-backup.dump.age>' \
BACKUP_DATABASE='digital_bast_prefect' \
AGE_IDENTITY_FILE='<identity-file>' \
scripts/restore-test.sh
```

Both must print `restore test passed` before production migration is approved.

---

## 8. Staging rollout — preferred release path

Preferred execution is the repository release chain, not hand-crafted host commands.

1. Land the approved release to `main` through the normal review process.
2. Require `main` CI to complete successfully.
3. Confirm Release workflow publishes the image by immutable digest.
4. Let the Release workflow deploy **staging first**.
5. Collect staging evidence before production continues.

The staging release must prove:

- exact `RELEASE_SHA`;
- image digest;
- exact release bundle includes `compose.production.yaml` and `bot-worker/`;
- preflight pass;
- target web health pass;
- `alembic upgrade head` pass;
- shadow `/health/ready` pass;
- `bot-worker` health pass;
- nginx config test pass;
- public `/health/ready` pass;
- worker/runner restart success.

After the workflow deployment, run/record application smoke as applicable:

```sh
WEB_URL=http://127.0.0.1:8080 \
PREFECT_URL=http://127.0.0.1:4200 \
scripts/smoke.sh
```

Do not advance to production when staging evidence is incomplete.

---

## 9. Migration behavior and verification

The current Payroll export migration is:

```text
revision: 20260920_0027
down_revision: 20260920_0026
```

It adds metadata-only table `payroll_export_history` and indexes. It does not replace
attendance truth or store duplicate CSV contents.

`scripts/deploy.sh` intentionally executes migration on the candidate release **before
public traffic switches**:

```text
candidate web health
  -> alembic upgrade head
  -> shadow readiness
  -> bot-worker health
  -> nginx validation
  -> traffic switch
  -> public readiness
```

Verify the production database is at the expected Alembic head after rollout. Record
the observed revision.

Routine rollback is **application rollback, not database downgrade**. Because `0027`
is additive, the safe default is to leave `payroll_export_history` in place while an
older compatible application image is restored.

Do not run `alembic downgrade` automatically. `0027` downgrade drops the history
table and therefore destroys export-history metadata.

---

## 10. Production rollout

Production may proceed only when all mandatory HOLD-clearing evidence and release
approvals exist.

The preferred production execution is the `production` job of
`.github/workflows/release.yml`, after successful staging.

Observe the rollout rather than duplicating its logic manually. `scripts/deploy.sh`
already protects the active slot until candidate health/migration/shadow checks pass.

Capture:

```text
Release workflow run id
production job result
RELEASE_SHA
immutable image digest
previous active slot
new active slot
migration result
shadow readiness result
bot-worker result
nginx test/reload result
public readiness result
worker/runner result
```

After cutover, run/confirm smoke and inspect logs for new errors before considering
scheduler enablement.

---

## 11. WhatsApp deployment — only when actually required

Normal app deployment MUST NOT restart `whatsapp-web-session`.

Only run the dedicated WhatsApp deployment when one of these is true:

- files under `whatsapp-web-session/` changed and the approved release requires them;
- the release owner explicitly approves a WhatsApp runtime rollout;
- a controlled runtime recovery requires the dedicated deployment procedure.

Before doing so:

1. keep Payroll outbound disabled/paused;
2. record the WhatsApp operations snapshot from Section 6;
3. verify `/data/auth-whatsapp-web-js` exists on the persistent volume;
4. verify owner/storage/receipt-store facts;
5. record current session container/image identity;
6. ensure no other WhatsApp deployment lock is held.

Dry-run the dedicated path:

```sh
scripts/deploy-whatsapp-web-session.sh --dry-run
```

Then, only when approved:

```sh
scripts/deploy-whatsapp-web-session.sh
```

The script builds/recreates only `whatsapp-web-session`, waits for health, and attempts
to restore the previous session image if the new runtime fails health.

Afterward, re-read the operations API and require:

- process alive;
- messaging ready before real sends;
- owner acquired;
- storage healthy;
- receipt store healthy;
- durable receipt counts understood;
- no unexpected increase in `UNKNOWN` caused by cutover;
- no unresolved owner conflict.

If pairing becomes necessary, use the controlled operator flow only when the runtime
factually reports operator action/pairing required. Do not repeatedly re-pair and do
not erase LocalAuth to force a new QR.

Recovery controls are available through the authenticated System & Sync APIs:

```text
POST /api/talentops/v1/system/whatsapp/recovery/pause
POST /api/talentops/v1/system/whatsapp/recovery/resume
POST /api/talentops/v1/system/whatsapp/recovery/reconnect
POST /api/talentops/v1/system/whatsapp/pair
```

They require authenticated authority/CSRF according to the application contract.

---

## 12. Manual acceptance before real Payroll traffic

Complete `docs/payroll-attendance-manual-acceptance.md` in the intended environment.
At minimum, execute and record:

- deterministic Talent correction path;
- natural-language Talent correction path with deterministic revalidation;
- evidence handling;
- PMO approve;
- PMO reject and return-to-Talent behavior;
- reminder disabled/paused behavior;
- reminder milestone deduplication;
- manual Follow-up preview/send eligibility revalidation;
- PMO aggregate closing digest;
- durable `UNKNOWN` behavior across restart/no blind resend;
- duplicate request-id safety;
- mobile Follow-up usability;
- Payroll export for a selected 21–20 cycle;
- export history metadata;
- raw attendance remains unchanged by proposal/review/export operations.

A failed acceptance item keeps the production decision at `HOLD`.

---

## 13. Payroll scheduler enablement sequence

Do this only after deployment, smoke, WhatsApp readiness, and manual acceptance pass
and the release owner explicitly authorizes real closing traffic.

1. Read current settings and preserve them in the release evidence.
2. Configure the intended closing policy while still keeping outbound suppressed.
3. Prefer this intermediate state when preparing an enabled campaign:

```text
enabled = true
paused = true
```

4. Verify preview/cycle/roles/hour/offsets and that the existing
   `pmo-notifications` deployment is healthy.
5. Confirm there is only one scheduled Talent reminder authority. Do not create a
   second Prefect deployment.
6. Re-check WhatsApp `ready`, owner, storage, receipt store, and receipt counts.
7. Unpause only as the last explicit business enablement step.
8. Record the settings version/timestamp immediately after activation.
9. Observe the next scheduler evaluation and confirm deduplication/delivery facts.

Settings authority:

```text
GET /api/talentops/v1/payroll/settings?scope_key=default
PUT /api/talentops/v1/payroll/settings?scope_key=default
```

The PUT requires normal authenticated CSRF protection. Do not bypass application
security with direct database edits just to enable the campaign.

---

## 14. Post-enable observability

Immediately after production rollout and again after scheduler enablement, capture:

### Release/runtime

- deployed SHA;
- immutable application image digest;
- active blue/green slot;
- container health summary;
- database Alembic revision;
- web `/health` and `/health/ready`;
- Prefect `/api/health`;
- relevant error logs since rollout.

### Payroll

- selected cycle and evaluated-through date;
- counts for `NEEDS_TALENT_ACTION`, `WAITING_SUBMITTED`, `COMPLETE`, `unverified`;
- Review Queue counts/stale facts;
- Follow-up reasons;
- configured closing settings and versions;
- latest group digest result;
- export history metadata.

### WhatsApp

- alive vs ready;
- connection state;
- owner state/conflict;
- storage health;
- receipt store health;
- `receipt_sent`;
- `receipt_unknown`;
- `receipt_in_flight`;
- recovery state/budget/cooldown;
- operator-action-required state;
- last acknowledged send timestamp.

Do not hide `UNKNOWN` from the release report. It is a real ambiguous-delivery state.

---

## 15. Hard STOP / HOLD conditions

STOP the rollout or keep production `HOLD` when any of the following is true:

- approved release SHA does not match the code being deployed;
- unexpected/unreviewed branch delta exists;
- `main` CI is not successful and no explicit release-owner policy decision exists;
- current release changes introduce Ruff findings;
- basedpyright fails;
- backend tests fail;
- frontend typecheck/Vitest/build fails;
- `whatsapp-web-session` tests fail;
- `scripts/check-ops.sh` fails;
- release bundle is missing `compose.production.yaml`;
- release bundle is missing `bot-worker/` build context;
- meaningful container build/scanner evidence is missing without an explicit waiver;
- preflight fails;
- disk/secrets/mode/group requirements fail;
- backup fails;
- restore test fails;
- migration fails or expected Alembic revision is not reached;
- candidate health or shadow readiness fails;
- `bot-worker` health fails;
- nginx validation/public readiness fails;
- WhatsApp owner conflict exists;
- WhatsApp storage is unhealthy;
- receipt store is unhealthy;
- LocalAuth is missing/unwritable;
- unexpected in-flight sends exist at cutover;
- unexplained `UNKNOWN` growth occurs;
- someone proposes resolving `UNKNOWN` by replay/blind resend;
- someone proposes deleting LocalAuth as routine recovery;
- two scheduled Talent reminder authorities would be active;
- manual acceptance has a failing mandatory item;
- external WhatsApp/provider readiness is not factual;
- release owner has not authorized unpausing real Payroll traffic.

---

## 16. Rollback procedure

### First action: reduce outbound risk

If Payroll behavior, delivery, or business truth is suspect:

1. pause/disable Payroll closing outbound first;
2. preserve current delivery/receipt evidence;
3. do not resend ambiguous messages while investigating.

### Application rollback

Before a manual rollback, inspect:

```sh
scripts/rollback.sh --dry-run
```

Then, if the alternate slot is known healthy and rollback is approved:

```sh
scripts/rollback.sh
```

The script:

- requires the alternate slot to be healthy;
- validates nginx before switch;
- validates public readiness after switch;
- restores the original slot if the rollback public-health check fails.

Do not automatically downgrade the database. Keep migration `0027` by default.

After rollback:

```sh
WEB_URL=http://127.0.0.1:8080 \
PREFECT_URL=http://127.0.0.1:4200 \
scripts/smoke.sh
```

Re-check Payroll settings and WhatsApp operations before any reminder is unpaused.

### WhatsApp-specific rollback

If a dedicated WhatsApp runtime rollout fails, use its dedicated deploy/rollback
behavior and preserve `/data` throughout. Never delete:

```text
/data/auth-whatsapp-web-js
```

and never reset durable gateway receipts to make a failed/unknown send look retryable.

---

## 17. Completion criteria

The agentic deployment task is complete only when it can provide factual evidence for
all of these:

- approved release SHA identified;
- validation status recorded without invented PASS results;
- `main` CI/release-policy decision recorded;
- production image digest recorded;
- preflight pass;
- backup pass;
- isolated restore tests pass for app and Prefect databases;
- staging deployment pass;
- migration revision verified;
- staging/manual acceptance result recorded;
- production blue/green deployment pass;
- application smoke pass;
- WhatsApp LocalAuth/owner/storage/receipt state verified;
- Payroll settings captured before and after any enablement;
- no blind resend of `UNKNOWN` occurred;
- rollback was either not required or its result is documented;
- remaining risks are explicitly listed;
- final `GO`/`HOLD` decision is attributable to the release owner, not invented by the
  deployment agent.

---

## 18. Required final deployment report format

Produce a final Markdown report with this structure:

```text
# Payroll Attendance Deployment Execution Report

Execution date/time (Asia/Jakarta):
Executor:
Release owner:
Approved release SHA:
Main CI run:
Release workflow run:
Application image digest:

## Validation
Backend compile:
Ruff:
Basedpyright:
Pytest:
Check-ops:
Frontend typecheck:
Frontend tests:
Frontend build:
WhatsApp Node tests:
Container build/scan or approved waiver:

## Preflight
Target host:
Deploy path:
Initial active slot:
Disk gate:
Secrets/mode/group gate:
Compose gate:

## Backup / Restore
App backup:
App restore test:
Prefect backup:
Prefect restore test:

## Staging
Deployment result:
Migration revision:
Shadow readiness:
Public readiness:
Smoke:
Manual acceptance:

## Production
Deployment result:
Previous slot:
New slot:
Migration result:
Public readiness:
Smoke:

## WhatsApp
Transport:
Alive:
Ready:
Owner acquired/conflict:
Storage healthy:
Receipt store healthy:
Sent count:
Unknown count:
In-flight count:
LocalAuth preservation verified:
Dedicated WA redeploy performed? yes/no + reason:

## Payroll Scheduler
Settings before deployment:
Settings before enablement:
Settings after enablement:
Observed scheduler evaluation:
Single reminder authority verified:

## Rollback
Required? yes/no
Action/result:

## Remaining risks / waivers
...

## Release decision
GO or HOLD:
Decision owner:
Evidence/reason:
```

The deployment agent must not fill unknown facts with assumptions. Use `NOT RUN`,
`NOT OBSERVED`, or `HOLD` when evidence is missing.
