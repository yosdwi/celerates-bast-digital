# PAMA sync bridge

Runs on a Windows PC inside the PAMA network. It is the only component that
must stay there: the VPS cannot resolve `jiepsqco423` or `JIEPBDSQ403` at all,
so attendance and Redmine can only be read from inside.

The bridge does I/O only — it reads the two SQL Servers plus the IoT Google
Sheet and posts raw rows to the VPS over outbound HTTPS. Every transform runs
on the VPS, so the business rules exist in exactly one place.

```
PAMA PC                          VPS
  attendance SQL Server ─┐
  Redmine SQL Server ────┼─ HTTPS ─→ POST /internal/sync/{attendance,redmine,iot-sheet}
  IoT Google Sheet ──────┘  bearer      ↓
                                     digital_bast_app (typed tables)
```

No inbound port is opened on the PC, and Postgres is never exposed publicly.

## The one script you run

`pama_bridge.py`. There is only one.

## Folder layout

```
bridge/
  pama_bridge.py     <- the script
  .env               <- your real config (gitignored)
  .env.example       <- template, safe to commit
  creds/
    service_account.json   <- Google key (gitignored)
    README.md              <- how to issue that key
```

`.env` and everything in `creds/` are gitignored — verified with
`git check-ignore`, since this repo is public.

## Setup on the PAMA PC

Copy the whole `bridge/` folder to the PC, e.g. `C:\digital-bast\bridge`.

```bat
cd C:\digital-bast\bridge
py -m venv .venv
.venv\Scripts\pip install httpx pymssql google-api-python-client google-auth
```

Then fill in the three blanks in `.env`:

| Variable | Where it comes from |
|---|---|
| `BAST_INGEST_TOKEN` | on the VPS: `sudo cat /home/debian/script/digital-bast-v2/secrets/sync_ingest_token` |
| `PAMA_SQL_PASSWORD` | the `mobile_user` password for the attendance SQL Server |
| `creds/service_account.json` | a **fresh** Google key — see `creds/README.md`; the old one is dead |

Everything else (Redmine host/user/password, spreadsheet id, sheet name) is
already filled in.

## Run

```bat
.venv\Scripts\python pama_bridge.py                     :: last 14 days
.venv\Scripts\python pama_bridge.py --since 2026-07-01  :: initial seed
.venv\Scripts\python pama_bridge.py --only attendance   :: one source at a time
```

Do the `--since 2026-07-01` run first — that is the initial load. Use
`--only attendance` / `--only redmine` / `--only iot` to isolate a source while
you are still sorting out credentials; each one is independent, so a dead
Google key does not block attendance.

Exit code is non-zero if any source failed, so Task Scheduler shows it as a
failed run rather than a silent success.

## Reading the output

```
window 2026-07-01 .. 2026-08-19; roster 17 employees
attendance: 1284 punches -> 642 employee-days
redmine: 318 rows -> 291 tasks
iot-sheet: 412 rows -> 380 tasks
```

Two numbers matter: `roster 17`, and an **empty** unmatched-NRP list. A
`WARNING unmatched NRPs: [...]` line means a roster NRP no longer matches the
source, which silently drops that person's entire history — exactly the failure
that went unnoticed for months when three NRPs carried a stray leading `L`.

Running it twice in a row should change no counts on the VPS.

## Recovery

Every run re-sends a fixed overlapping window and the VPS upserts on
`record_key`. That single property covers all the failure modes:

| Situation | What to do |
|---|---|
| PC was offline for hours | nothing — the next run's window covers the gap |
| Network dropped mid-batch | nothing — re-sent next run |
| Run fired twice | nothing — upserts are no-ops |
| VPS restarted | nothing — no cursor state to rebuild |
| Gap longer than the window | run once with `--since <date>` |

There is deliberately no cursor or watermark: nothing to corrupt, and no way
to silently skip a day.

## Scheduling — only after one clean manual run

If the PAMA network can reach the VPS directly (test:
`curl https://conform-v2-web.celeratesapps.com/health/ready`), schedule the
plain form:

```
Program:   C:\digital-bast\bridge\.venv\Scripts\python.exe
Arguments: pama_bridge.py
Start in:  C:\digital-bast\bridge
```

Tick "Run whether user is logged on or not". The service-account path resolves
against the script's own folder, so a missing "Start in" will not break the
Google read.

### If the PAMA network can't reach the VPS at all

This is the normal case (SSH is reset network-wide, TLS to every
`*.celeratesapps.com` host is SNI-blocked) — schedule the relay form instead,
every 30 minutes:

```
Arguments: pama_bridge.py --dump out --upload-sheet
```

Requires `SYNC_LOOKBACK_DAYS` set short (e.g. `2`) in `.env` and
`GOOGLE_SHEETS_RELAY_CREDENTIALS` / `GOOGLE_SHEETS_RELAY_SHEET_ID` filled in —
see `.env.example`. The VPS side (`scripts/sheet_replay_poller.py`, its own
cron) reads and replays what lands there; local dump files are deleted once
they're safely uploaded, so nothing accumulates on this PC.

`--dump` reads its roster from the relay sheet's `Roster` tab, not a local
file — `scripts/push_roster_to_sheet.py` keeps that tab current from the VPS
side. There is no local-roster fallback: if the Sheets relay isn't reachable
or configured, `--dump` fails loudly rather than silently running against a
roster someone forgot to update (a stale roster is exactly what let a
leading-`L` NRP typo silently drop three people's data for months).
