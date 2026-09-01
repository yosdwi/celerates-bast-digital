# BAST Bot V1

Official WhatsApp Cloud API assistant for Digital BAST. The Meta gateway
normalizes inbound messages, calls the existing `digital-bast` workflow, and
sends the deterministic response through Graph API. Business rules remain in
the CLI and application services, never in the transport.

```text
WhatsApp DM -> Meta webhook -> meta-wa-gateway -> bot-worker -> digital-bast CLI
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

## WhatsApp Cloud API integration

The integration is intentionally split at the existing stable business
boundary:

- **`meta-wa-gateway/`** verifies signed WABA webhooks, downloads/uploads
  media, renders native Meta interactions, applies durable idempotency, and
  sends through `/{PHONE_NUMBER_ID}/messages`.
- **`bot-worker/`** remains the stateless wrapper around `digital-bast
  bot-reply` and `bot-evidence`. It owns no provider connection or credentials.

The public callback is `GET/POST /webhooks/whatsapp`. All worker and outbound
endpoints remain private on the Docker backend network. See
`meta-wa-gateway/README.md` for required Meta assets, secrets, template
contract, and callback setup.

Menus with one to three actions render as native reply buttons. Larger menus
render as a list message, and Talent Mobile links render as CTA URL buttons.
Typed menu numbers remain valid for compatibility with existing users.
TalentOps follow-up history promotes Meta lifecycle events to `delivered`,
`read`, or `failed` and retains the provider error code for operations.

The runtime is DM-first. The standard WhatsApp Business Platform does not
provide parity with consumer-group mention/listener behavior, so group-specific
business commands remain available through the CLI/web surfaces instead of an
unofficial linked-device transport.

## Automation

The same services (`digital_bast.operations`) are importable by Prefect flows.
Scheduled completion and PMO notifications use the approved utility template
through the same durable application outboxes. Replies within the active
customer-service window remain free-form; Meta error `131047` automatically
falls back to the utility template.

## Production activation

1. Create the Meta Business Portfolio, app, WABA, production phone number, and
   System User token.
2. Approve the Indonesian utility template documented by the gateway.
3. Populate the three Meta secret files and non-secret `.env` identifiers.
4. Run `scripts/meta-wa-setup.sh check`, then `subscribe` to validate the
   assets and subscribe the app to the WABA.
5. Run Alembic migration `20260901_0018`, deploy, and register the HTTPS
   callback with the configured verify token.
6. Subscribe the callback field `messages`, send an inbound DM, upload evidence,
   exercise all menus, then verify sent/delivered/read events.

On a successful cutover the deploy script removes the retired `wa-session`
container from this Compose project. If the previously shipped standalone
systemd transport is still active, preflight stops before mutation and requires
an operator to disable that unit explicitly.
