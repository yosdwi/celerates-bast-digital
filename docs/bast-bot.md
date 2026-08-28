# BAST Bot V1

WhatsApp group bot for Digital BAST. Hermes Agent parses the message, calls one
allowlisted `digital-bast` command and posts the deterministic reply back to the
group. Business rules live in the CLI, never in the agent.

```text
WhatsApp group -> Hermes Agent -> digital-bast CLI -> NocoDB / PostgreSQL
```

## Commands

Every business command takes an explicit inclusive date range.

```bash
digital-bast completion-status --start-date 2026-08-01 --end-date 2026-08-31 --format json
digital-bast completion-status --start-date 2026-08-01 --end-date 2026-08-31 --employee "Titin"
digital-bast export-attendance --start-date 2026-07-20 --end-date 2026-08-18 \
  --label "Attendance August 2026" --output attendance.csv
digital-bast generate-bast --start-date 2026-08-01 --end-date 2026-08-31 --output bast.html
digital-bast system-status --format json
digital-bast bot-reply --text "@BAST Bot status 1 sampai 31 Agustus"
```

`--format text` renders the Indonesian WhatsApp message; the default `json`
output is machine readable. Business incompleteness is not a process error:
`completion-status` exits `0` while reporting `"state": "incomplete"`.
Configuration and range errors exit `2`.

`bot-reply` is the integration Hermes should use: it parses the Indonesian date
phrase ("1 sampai 31 Agustus", "20 Juli sampai 18 Agustus", "2026-08-01 sampai
2026-08-31", "Agustus"), routes to the matching command and returns the reply
text. Container mutation requests are answered with a refusal; V1 only inspects
status.

## Completion rules

| Check | Rule |
| --- | --- |
| Log 1 PAMA | Working shift needs an attendance row with Clock In and Clock Out, or Evidence Attendance when a clock is missing. OFF/holiday may have no attendance row. |
| Timesheet | Working shift needs a valid Log 1 PAMA for that date plus a timesheet row. OFF/holiday needs a timesheet row with non-empty remarks. |
| Task List | Every task in range must be `Closed` (trimmed, case-insensitive). Zero tasks returns `needs_review`. |
| Evidence | At least one Task List evidence per employee per range. |

OFF days come from `Schedule Shifting` for IoT Operations and from the national
holiday calendar plus weekends for Developers, reusing `domain.timesheets.day_status`.

## Unresolved field mapping

Two mappings are not discoverable from the repository and are therefore
configuration, not code. Until they are set, the affected check reports
`needs_review` instead of a fabricated result.

| Setting | Purpose |
| --- | --- |
| `NOCODB_ATTENDANCE_MAPPING` | JSON describing the NocoDB attendance table: `table`, `date_column`, `clock_in_column`, `clock_out_column`, `evidence_column`, `employee_link_table`, `employee_link_column`. |
| `NOCODB_TASK_EVIDENCE_COLUMN` | Column on `Tasklist IoT Operations` / `Tasklist Developer` holding the Task List evidence. |

```bash
export NOCODB_ATTENDANCE_MAPPING='{"table":"Attendance","date_column":"Date","clock_in_column":"Clock_In","clock_out_column":"Clock_Out","evidence_column":"Evidence_Attendance","employee_link_table":"_nc_m2m_Attendance_Employee Data","employee_link_column":"Attendance_id"}'
export NOCODB_TASK_EVIDENCE_COLUMN='Evidence'
```

The example values above are placeholders. Replace them with the real NocoDB
table and column names before enabling the checks.

## System status

`system-status` runs `docker compose --profile blue --profile green ps --all
--format json` read-only, from the repository root, through a subprocess
argument list. It never starts, stops, restarts or execs anything, and the
Docker socket is not mounted into any container. Required services: `postgres`,
`redis`, `prefect-server`, `prefect-services`, `worker`, `runner`,
`reverse-proxy`, plus at least one healthy `web-blue` or `web-green` slot.

## WhatsApp bridge

What used to be a single `bot-bridge/` service is split into two, so that
deploying an app/business-logic change never has to restart the process
holding the live WhatsApp connection (repeated rapid reconnects get the
session revoked by WhatsApp's own anti-abuse system):

- **`wa-session/`** -- Baileys + the setup page on `127.0.0.1:8090`. Pairs
  the bot number, keeps the group allowlist, and forwards each qualifying
  message to bot-worker over HTTP. Not part of the normal blue/green deploy;
  see `scripts/deploy-wa-session.sh`. Full instructions in
  `wa-session/README.md`.
- **`bot-worker/`** -- a stateless HTTP wrapper that shells out to
  `digital-bast bot-reply` / `bot-evidence` exactly as the combined service
  used to. Holds no WhatsApp state, so it rebuilds and redeploys on every
  release like any other app change. Full instructions in
  `bot-worker/README.md`.

```bash
cd wa-session && npm install && npm start   # needs bot-worker reachable at BOT_WORKER_BASE_URL
cd bot-worker && npm install && BAST_CLI="uv run digital-bast" npm start   # local
```

The setup page carries the QR code (and pairing code, if
`BOT_PAIRING_NUMBER` is set), the group allowlist form, a "Uji perintah" box
that round-trips through bot-worker, and the recent log. Session files are in
`wa-session/`'s `BOT_AUTH_DIR`, the allowlist in `BOT_DATA_DIR/config.json`.

Hermes Agent can replace bot-worker's CLI call later: the contract
(`digital-bast bot-reply`) is unchanged, so no business rule moves.

## Hermes setup

1. Deploy Hermes with a dedicated WhatsApp number (Baileys) on the host that
   runs the compose project.
2. Load `config/hermes/bast-bot.yaml` and replace `allowed_groups` with the real
   group JID.
3. Ensure `digital-bast` is on the agent `PATH` and the process can read the
   application `.env` (NocoDB DSN, base id, app database DSN).
4. Group mention only; direct messages stay disabled in V1.

## Automation

The same services (`digital_bast.operations`) are importable by Prefect flows.
No scheduled completion deployment ships in V1 because no delivery channel is
approved yet, and the bot answers only when it is mentioned; adding one is a
thin wrapper around `completion_status`, not a second rule set.

## Implementation status (2026-08-18)

Done and verified:

- Completion engine, CLI commands, docker status, WhatsApp formatting and
  parsing, NocoDB completion source, BAST HTML rendering.
- `ruff check src tests` clean; `basedpyright` reports no error in the new or
  modified files (10 pre-existing errors remain in
  `src/digital_bast/infrastructure/nocodb_repository.py`).
- `pytest tests/unit tests/e2e/flows`: 151 passed, 1 failed. The failure is
  `tests/unit/flows/test_pipelines.py::test_current_period_uses_jakarta_calendar_independent_of_source_offset`,
  pre-existing since commit `bd8cdd9` (`lookback_months` 1 vs 0), unrelated to
  the bot work.
- Bridge run locally: QR rendered on the setup page, `system status` answered
  through the bridge, container mutation refused, invalid settings reported as
  one line with exit `2` instead of a traceback.

Not done yet, in rough priority order:

1. Pair a real WhatsApp number, invite it to the group, and run the four
   commands from the group (the only step that needs a phone).
2. Fill `NOCODB_ATTENDANCE_MAPPING` and `NOCODB_TASK_EVIDENCE_COLUMN` with the
   real NocoDB names, then re-check that Log 1 PAMA and Evidence stop reporting
   `needs_review`.
3. Point `.env` at real DSNs (the local copy still has the container
   `/run/secrets/*` paths) and run `completion-status` against real data.
4. Decide whether the BAST document needs PDF output; today it renders HTML
   through the existing Jinja2 templates and adds no dependency.
5. Optional: a Prefect deployment wrapping `digital_bast.operations`, once a
   delivery channel for scheduled reports is approved.

Deliberately skipped, with the reason:

- No new Prefect deployment (no approved push channel; bot answers on mention).
- No PDF renderer dependency (no renderer existed; HTML path already there).
- No web routes added (the CLI is the integration surface; the web route
  inventory characterization test stays untouched).
