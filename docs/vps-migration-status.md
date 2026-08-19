# VPS migration — deployment handover

Code is done and committed (`633cc4d`). What remains is deployment and live
E2E. Read this before touching the VPS.

**Credentials are not in this file (the repo is public).** SSH details live in
Claude's own memory (`reference: vps-access`); ask the user otherwise.

## What changed in the code

The VPS was running the NocoDB arm of a store-selection branch while every
report read app Postgres, so imports landed in one database and the reports
read another. That branch is gone.

`durable_records` (one jsonb table) is replaced by typed tables — `employees`,
`holidays`, `schedules`, `attendance`, `tasks`, `timesheets` — each with a
surrogate `id` primary key. That shape is forced, not chosen: NocoDB cannot
UPDATE or DELETE a relation without a single-column PK, and both NocoDB and the
WhatsApp bot must edit the *same* rows.

`record_key` carries the existing `RecordKey` strings, so `domain/identity.py`
is untouched and identity semantics are unchanged.

Manual-edit protection is now one mechanism instead of two: the trigger
`mark_manual_edit()` sets `origin='manual'` for any writer that is not the
`digital_bast_app` role, and every pipeline upsert carries
`WHERE origin <> 'manual'`.

`durable_records` still exists and is no longer read or written. Dropping it is
a separate migration after a month of verified operation.

## Current VPS state (verified 2026-08-19, before this deploy)

| Item | Reality |
|---|---|
| Running image | `digital-bast:local`, built 2026-08-04 — predates all of this |
| Deploy dir | `/home/debian/script/digital-bast-v2/`, **not a git repo** (rsynced) |
| Alembic head | `20260803_0001` — three migrations behind |
| Missing tables | `task_evidence`, `wa_identity`, `activation_codes`, `bot_conversations`, `bast_artifacts` |
| Active slot | `web-green` |
| Host | 4 vCPU / 7.6 GB RAM / 74 GB disk, **58 G used, 14 G free** |
| PAMA hosts | `jiepsqco423` and `JIEPBDSQ403` do **not** resolve — the bridge is mandatory |
| Ollama / bot-bridge | neither installed |
| `nc_audit_v2` | 11 GB / 10.28 M rows — the whole 11 GB of `neondb` |
| Google service account | dead (`invalid_grant: Invalid JWT Signature`) |
| Legacy V1 | `digital-bast-web` exited, `digital-bast-nginx` crash-looping — **leave alone** |

## Deployment

Ordering matters: migration `20260820_0004` creates the `nocodb_editor` role,
so nocodb-v2 cannot connect before `alembic upgrade head` has run.

### 0. Back up first

```bash
sudo mkdir -p /home/debian/backups && cd /home/debian/backups
docker exec digital-bast-v2-postgres-1 pg_dump -U digital_bast_app digital_bast_app \
  | gzip > app-$(date +%F).sql.gz
docker exec postgresql-local-postgre-1 pg_dump -U 'celerates-admin' neondb \
  | gzip > neondb-$(date +%F).sql.gz
```

### 1. Reclaim disk

nocodb-v2 (~1.5 GB) and Ollama (~2 GB) do not fit comfortably in 14 GB.
`nc_audit_v2` is pure NocoDB audit history (who changed what) — no business
table depends on it. Dump before deleting.

```bash
docker exec postgresql-local-postgre-1 pg_dump -U 'celerates-admin' -d neondb \
  -t public.nc_audit_v2 | gzip > nc_audit_v2-$(date +%F).sql.gz
docker exec postgresql-local-postgre-1 psql -U 'celerates-admin' -d neondb \
  -c "DELETE FROM public.nc_audit_v2 WHERE created_at < now() - interval '90 days';"
docker exec postgresql-local-postgre-1 psql -U 'celerates-admin' -d neondb \
  -c "VACUUM FULL public.nc_audit_v2;"
df -h /     # expect ~10 GB freed
```

### 2. New secrets and env

Two new secrets, both mode `0640` and group `SECRETS_GID` or `preflight.sh`
rejects them:

```bash
cd /home/debian/script/digital-bast-v2
openssl rand -hex 32 > secrets/sync_ingest_token
chmod 640 secrets/sync_ingest_token && chgrp "$SECRETS_GID" secrets/sync_ingest_token
```

Add to `.env`:

```
NOCODB_V2_DB_PASSWORD=<the digital_bast_app password, from secrets/app_database_password>
NOCODB_V2_PORT=8082
BOT_LLM_URL=http://172.17.0.1:11434
BOT_LLM_MODEL=llama3.2:3b
BOT_ALLOWED_GROUPS=<the WhatsApp group id used in local E2E>
```

`SQLSERVER_CONNECTION_STRING` and `GOOGLE_APPLICATION_CREDENTIALS` are no
longer required in production — the VPS cannot reach either source, and both
now belong to the bridge host. The secret files can stay; nothing reads them.

### 3. Sync the code and deploy

The deploy directory is not a git checkout, so rsync current `main` into it
(preserving `.env` and `secrets/`), then:

```bash
./scripts/preflight.sh
./scripts/deploy.sh          # blue/green: green -> blue, runs alembic upgrade head
```

`deploy.sh` gates on container health, a shadow request, the migration, then
`nginx -t` before flipping traffic. A migration failure leaves the active slot
serving the old image.

Expect `alembic current` to move `20260803_0001 → 20260820_0004`.

### 4. Seed the roster

Nothing else works before this: every typed table has a foreign key to
`employees`.

```bash
docker compose run --rm --no-deps web-blue \
  python scripts/seed_employees_from_nocodb.py
```

It prints all 17 rows. Confirm the three NRPs that carried a leading-`L` typo
now read `JIMT25004`, `JIMT22012`, `JIMT24002`. NocoDB's roster is the correct
one — `employee_data.json` was the file with the typo.

### 5. Set the nocodb_editor password

The migration creates the role without a password so no secret lands in a
migration file:

```bash
docker exec digital-bast-v2-postgres-1 psql -U digital_bast_app -d digital_bast_app \
  -c "ALTER ROLE nocodb_editor PASSWORD '<pick one>';"
```

### 6. nocodb-v2

```bash
docker compose up -d nocodb-v2      # http://127.0.0.1:8082
```

First boot: create an admin account (separate from the old instance — the V2
web admin login still authenticates against the *old* NocoDB's `nc_users_v2`
and is unaffected). Then add a data source:

- host `postgres`, port `5432`, database `digital_bast_app`, schema `public`
- user `nocodb_editor` with the password from step 5
- **editable ON**

The six business tables appear as normal editable grids. The pre-existing
`nocodb_bast` instance is never touched.

### 7. Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl edit ollama          # Environment="OLLAMA_HOST=127.0.0.1:11434"
sudo systemctl restart ollama
ollama pull llama3.2:3b
```

Never publish the port. If disk is still tight, leave `BOT_LLM_URL` empty —
`operations.py` degrades to the regex command parser with no LLM.

### 8. bot-bridge

**Copy `bot-bridge/auth/` from the laptop into the volume before first start**,
otherwise WhatsApp demands a fresh QR pairing and the bot is offline until
someone scans it.

```bash
docker compose build bot-bridge
docker volume create digital-bast-v2_bot-bridge-data
docker run --rm -v digital-bast-v2_bot-bridge-data:/data -v /tmp/auth:/src:ro \
  alpine sh -c 'mkdir -p /data/auth && cp -a /src/. /data/auth/ && chown -R 10001:10001 /data'
docker compose up -d bot-bridge
```

Known degradation: `system-status` shells out to `docker`, which is absent
inside the container. Leave it — do not mount the docker socket.

### 9. First bridge run (from the PAMA Windows PC)

See `bridge/README.md` for install. Then:

```bat
.venv\Scripts\python pama_bridge.py --since 2026-07-01
```

Watch for `unmatched NRPs` — a non-empty list means a roster NRP no longer
matches the source, which silently drops that person's entire history. That is
exactly the failure that went unnoticed for months.

Configure the 5-minute Task Scheduler job **only after** one clean manual run.

## Quick checks before handing to E2E

```bash
# schema
docker exec digital-bast-v2-postgres-1 psql -U digital_bast_app -d digital_bast_app -c "\dt"
docker exec digital-bast-v2-postgres-1 psql -U digital_bast_app -d digital_bast_app \
  -c "select * from alembic_version;"

# roster landed
docker exec digital-bast-v2-postgres-1 psql -U digital_bast_app -d digital_bast_app \
  -c "select nrp, role, full_name from employees order by role, full_name;"

# ingest rejects an anonymous caller
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  http://127.0.0.1:8080/internal/sync/attendance -H 'Content-Type: application/json' -d '{"rows":[]}'
# expect 401

# manual-edit trigger works: edit a row in nocodb-v2, then
docker exec digital-bast-v2-postgres-1 psql -U digital_bast_app -d digital_bast_app \
  -c "select record_key, origin from timesheets where origin = 'manual' limit 5;"
```

Then run the real E2E over WhatsApp: `status`, `detail <name>`,
`export attendance developer`, DM NRP onboarding, an evidence photo upload, and
a BAST PDF for the month.

## Rollback

`scripts/rollback.sh` flips the nginx slot back. The migration is the part that
is not automatic — `20260820_0004` has a working `downgrade()`, but restoring
`app-*.sql.gz` is the safer move if data has already landed.

Stop if: the BAST PDF differs structurally from the laptop reference, attendance
CSV row count drops, the bot fails twice in a row, ingest returns non-2xx twice
in a row, or free disk falls below 5 GB.

## Test status

`ruff`, `ruff format` and `basedpyright` are clean across the repo.
`pytest tests/unit tests/shadow tests/characterization` → **141 passed, 1
failed**.

The one failure is
`test_current_period_uses_jakarta_calendar_independent_of_source_offset`
(`lookback_months: 1 != 0`). It is **pre-existing** — verified by stashing all
of this work and re-running it against the original code, where it fails
identically. Not a regression from this migration.

`tests/integration/*` need a live Postgres and were not run here.

## Still open

1. **Rotate the Google service-account key.** The current one is dead
   (`invalid_grant`), and a fragment of it was printed to a terminal during the
   2026-08-19 audit. The bridge needs a fresh key on the Windows PC.
2. **Schedule Shifting feed.** `scripts/import_schedule_csv.py` takes a file
   path in the `simulasi shifting(Schedule Shifting).csv` layout; the download
   or Sheets connection is yours to wire.
3. **Retention.** No period is enforced. `scripts/retention.sh` exists and
   `retention_runs` has never been written by anything.
4. **`durable_records` drop** — separate migration after a verified month.
5. **Cloudflare Access SSH** still needs a Short-Lived Certificate CA in Zero
   Trust. Direct port 22 works.
