# VPS migration status (in progress)

Tracks the "move the whole Digital BAST runtime off the dev laptop onto the
VPS" effort. Read this before starting a new session on this task instead of
re-discovering everything from scratch.

**VPS SSH credentials are not in this file (repo is public).** Ask the user,
or check Claude's own memory (`reference: vps-access`) if this session has
carried it over.

## Current VPS state (as of 2026-08-19)

Host: `142.44.242.56` (`vps-4e0cf8f6`), OVH. 4 vCPU / 7.6 GB RAM / 74 GB disk
(58 GB used -- getting tight, watch it before adding Ollama models).
Deploy path: `/home/debian/script/digital-bast-v2/` (compose project name
`digital-bast-v2`). A separate, unrelated legacy V1 stack also lives on this
box at `/home/debian/script/digital-bast/` (`digital-bast-web`/
`digital-bast-nginx` containers) -- out of scope, do not touch it without
being asked.

Domain (staging): `conform-v2-stagging.celeratesapps.com`, fronted by a
Cloudflare Tunnel (`cloudflared` systemd service, token-based, no local
`/etc/cloudflared/*.yml` -- routing rules live in the Cloudflare dashboard,
not on the box). A *separate* Cloudflare Access application exists for
interactive SSH (`conformssh.celeratesapps.com`) -- that one needs a
Short-Lived Certificate CA enabled in Zero Trust before `cloudflared access
ssh-gen` will work; it was never gotten working this session. Direct SSH on
port 22 to the raw IP is what actually worked (see access notes below).

Running (`docker ps`): postgres, redis, prefect-server, prefect-services,
worker, runner, web-blue, web-green, reverse-proxy -- all healthy. **The
image tag deployed is `digital-bast:v2-nocodb-postgres-20260803162252`
(Aug 3) -- it predates this entire session's work** (E2E stabilization,
WhatsApp UX/persona, BAST PDF parity fixes, the NRP data-quality fix). A
fresh deploy of current `main` has not happened yet.

`.env` on the box has `DIGITAL_BAST_DISABLED_OPERATIONS=attendance-import,redmine-import`
-- both source imports are currently OFF on the VPS. Nothing has synced
Redmine/attendance data into VPS Postgres yet.

## Incident fixed this session: reverse-proxy crash loop

A host reboot (via OVH manager, done by the user after the VPS became
unreachable) exposed a pre-existing bad permission on
`config/nginx/{nginx.conf,active-slot.conf}` (`700`, owner `debian` only).
The `reverse-proxy` container runs hardened or non-root (`user: "101:101"`,
`read_only: true`, `cap_drop: ALL` -- see `compose.yaml`), so it could never
open() those files on a fresh start. It had likely been silently broken for
weeks; the running container just never needed to re-open the file until the
reboot forced a fresh container start.

Fixed: `chmod o+x config config/nginx && chmod o+r config/nginx/{nginx.conf,active-slot.conf}`,
then `docker restart digital-bast-v2-reverse-proxy-1`. Made durable:
`scripts/deploy.sh` now re-applies this at the start of every deploy
(commit `5c049d8`), so it can't silently regress again regardless of how a
bad-permission file lands there next time.

## CI status

`quality` (ruff/basedpyright/pytest) was failing on `main` since before this
session started -- `ruff check .` scans the *whole* repo, not just
`src/`+`tests/`, and `scripts/*.py` + one migration file had ~20 lint
violations nobody had cleaned up. Fixed.

`migration-smoke` was failing because `.github/workflows/ci.yml` started
uvicorn against `digital_bast.web.app:app`, which doesn't exist -- `app.py`
is a `create_app(dependencies)` factory, not a module-level instance; the
real ASGI entrypoint is `digital_bast.web.asgi:app` (matches `Dockerfile`'s
own `CMD`, which was already correct). Fixed (one-line change).

`container` job (docker build + Trivy scan) fails at the "Set up job" step
with no visible cause -- GitHub's job logs API returned 403 "must have admin
rights" for this token, so the actual reason is still unknown. This failed
identically on `bb72cd101f6ae06b23d10877784586ea7c5853da`, i.e. before this
session touched anything, so it's pre-existing infra debt, not a regression.
**Unresolved** -- needs someone with admin/logs access to the GitHub repo to
actually read that job's log.

Because `Release` only triggers after the whole `CI` workflow concludes
successfully (`workflow_run` + `conclusion == 'success'`), the auto-deploy
pipeline (`git push` -> staging -> production) will stay blocked on the
`container` job until that's resolved -- **a manual deploy over SSH is the
practical path until then** (see below).

## Real data-quality bug found via live WhatsApp E2E: NRP typo

Real E2E testing (`export attendance developer`, `detail <name>` in the
WhatsApp group) surfaced that Aris Purnomo, Ovianto, and Yoses Dwi Maheswara
had **zero** attendance and **zero** Redmine tasks for the whole test period,
while everyone else had real data. Root cause confirmed by querying the real
Redmine SQL Server (`JIEPBDSQ403`, reachable from this sandbox) directly:
`employee_data.json` had an erroneous leading `"L"` on exactly these three
NRPs (`LJIMT25004`/`LJIMT22012`/`LJIMT24002` vs the real
`JIMT25004`/`JIMT22012`/`JIMT24002` -- confirmed by matching real Redmine
rows, 117/34/92 respectively, under the correct NRP). Both the Redmine task
importer and the PAMA attendance importer join purely on NRP
(`nrp_to_employee = {employee.external_id: employee.id ...}` in
`infrastructure/production_sources.py`; equivalent join in
`scripts/load_pama_attendance.py`), so a wrong NRP silently drops 100% of
that person's rows with no error, ever.

Fixed in `employee_data.json` (this session, uncommitted -- see below).
Re-ran `redmine-import` locally afterward and confirmed Task List/Evidence
now populate correctly for all three. **Attendance is still unverified**
-- the PAMA attendance SQL Server (`jiepsqco423`) does not resolve/isn't
reachable from this dev sandbox at all (different host than Redmine's), so
the same NRP fix could not be confirmed against live attendance data this
session. Also found and fixed: two `full_name: "Owner Test"` rows from a
stray `tests/integration/test_postgres.py` fixture run were leaking into
real attendance exports (`ATTENDANCE`/`ATTENDANCE_LEGACY` SQL now filter
`employee_id LIKE 'MTG-TF/%'`).

## What's actually left from the original migration ask

Reminder of the full ask (do not re-plan it, just track progress):
PAMA Windows PC -> `pama_bridge.py` (outbound HTTPS, SQL Server + Redmine
reads) -> VPS ingest API -> Postgres -> existing Digital BAST app (WhatsApp
bot, Ollama, Attendance/Task/Evidence/BAST generation) running entirely on
the VPS, laptop no longer required.

Not started yet:
- [ ] `pama_bridge.py` + its own small handoff folder (§4-6, §9 of the
      original task) -- has NOT been built. `scripts/load_pama_attendance.py`
      and `infrastructure/production_sources.py`/`sqlserver.py` are the
      *existing, proven* SQL Server access code to reuse/adapt for it, not
      rewrite.
- [ ] VPS ingest HTTPS endpoint (`POST /internal/sync/attendance`,
      `POST /internal/sync/tasks`) with machine-to-machine auth,
      idempotent upsert, bounded batch size (§7) -- not started.
- [ ] Ollama running *on the VPS* instead of the dev laptop (§12) -- not
      started; `BOT_LLM_URL`/`BOT_LLM_MODEL` contract should not change.
- [ ] WhatsApp bot-bridge running continuously *on the VPS* (§13) -- not
      started; no bot-bridge container exists on the VPS yet. It currently
      only runs from this dev sandbox (and dies when the sandbox does).
      Auth session (`bot-bridge/auth/`) should migrate rather than force a
      fresh QR pairing.
- [ ] Employee roster (`employee_data.json`) needs a real home in VPS
      runtime, not just a file the dev laptop happens to have (§11).
- [ ] Windows Task Scheduler config for the PAMA bridge, every 5 min (§15)
      -- explicitly deferred until after one verified manual bridge run.
- [ ] Sync observability (last attempt/success timestamps, counts) surfaced
      through the existing system-status/WhatsApp status flow (§16).

## VPS access notes (for whoever/whatever connects next)

- Direct `ssh -p 22 <user>@142.44.242.56` works from a network that isn't
  blocked by whatever firewall/DPI policy this dev sandbox's corporate
  network applies (see below) -- it did NOT work reliably from this WSL
  sandbox until the user rebooted the box from the OVH manager console.
- Connections reset intermittently (`ConnectionResetError`) roughly one in
  three attempts even when the box is healthy -- retry with backoff, don't
  treat one reset as "the VPS is down."
- The Cloudflare Access path (`conformssh.celeratesapps.com`,
  `cloudflared access ssh-gen`) never worked this session ("Please create a
  ca for application" -- the Zero Trust dashboard needs a Short-Lived
  Certificate CA enabled for that Access app first). Direct IP+port 22 is
  what actually worked; treat Cloudflare Access as a nice-to-have, not the
  primary path, until that dashboard step is done.
- This dev sandbox's own network (WSL, routed through what looks like a
  pamapersada.net corporate DNS/proxy) silently breaks TLS to some
  Cloudflare edge IP ranges (reproduced against `1.1.1.1` too) intermittently
  -- if `curl`/`cloudflared` to any `*.celeratesapps.com` host hangs or
  resets, retry before assuming the target is broken.
