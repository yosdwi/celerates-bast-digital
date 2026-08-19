# PAMA sync bridge

Runs on a Windows PC inside the PAMA network. It is the only remaining
component that must live there: the VPS cannot resolve `jiepsqco423` or
`JIEPBDSQ403` at all, so attendance and Redmine can only be read from inside.

The bridge does I/O only — it reads the two SQL Servers plus the IoT Google
Sheet and posts the raw rows to the VPS over outbound HTTPS. Every transform
runs on the VPS, so the business rules exist in exactly one place.

```
PAMA PC                          VPS
  attendance SQL Server ─┐
  Redmine SQL Server ────┼─ HTTPS ─→ POST /internal/sync/{attendance,redmine,iot-sheet}
  IoT Google Sheet ──────┘  bearer      ↓
                                     digital_bast_app (typed tables)
```

No inbound port is opened on the PC, and Postgres is never exposed publicly.

## Install

```bat
py -m venv .venv
.venv\Scripts\pip install httpx pymssql google-api-python-client google-auth
copy .env.example .env
```

Fill in `.env`, then get `BAST_INGEST_TOKEN` from the VPS
(`/home/debian/script/digital-bast-v2/secrets/sync_ingest_token`).

## Run

```bat
.venv\Scripts\python pama_bridge.py                     :: last 14 days
.venv\Scripts\python pama_bridge.py --since 2026-07-01  :: initial seed
.venv\Scripts\python pama_bridge.py --only attendance
```

Exit code is non-zero if any source failed, so Task Scheduler shows it as a
failed run rather than a silent success.

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

## Scheduling (only after one verified manual run)

Task Scheduler → Create Task → trigger every 5 minutes, action:

```
Program:   C:\digital-bast\bridge\.venv\Scripts\python.exe
Arguments: pama_bridge.py
Start in:  C:\digital-bast\bridge
```

Tick "Run whether user is logged on or not". Verify the first few runs report
`unmatched NRPs: []` — a non-empty list means a roster NRP no longer matches
the source, which silently drops that person's entire history.

## Verifying a run

The summary lines are the check:

```
window 2026-07-01 .. 2026-08-19; roster 17 employees
attendance: 1284 punches -> 642 employee-days
redmine: 318 rows -> 291 tasks
iot-sheet: 412 rows -> 380 tasks
```

`roster 17` and an empty unmatched-NRP list are the two numbers that matter.
Running it twice in a row should change no counts on the VPS.
