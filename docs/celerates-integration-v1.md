# Celerates integration API v1 (provider contract)

Status: v1, implemented 2026-09-28 on `chore/session-20260918-fixes`. Additive v1 extensions (attendance log, task evidence, direct messages, links without expiry, audience with tasks, bot `masuk`) implemented 2026-09-29 on `feat/celerates-integration-v1` per `celerates-digital-intelligence/docs/implementation/pmo-talent-completion-contract.md`.

Product decision: Celerates is the single user-facing operational product. ConForm stays an independent bounded service that owns readiness, corrections, evidence, the canonical BAST, the canonical attendance CSV, WhatsApp identity and delivery. Consumer-side requirements, identity, RBAC, journeys and the retirement plan are in `celerates-digital-intelligence/docs/21-conform-bounded-service-execution.md` (execution record; planning record doc 19) and ADR-019.

This document is the **authoritative wire contract**. A breaking change requires `/api/celerates/v2`.

## Ownership (what this adapter must never do)

- It reuses existing services only: `PayrollReadService`, `PayrollReviewService`, `AttendanceResolutionService`, `AttendanceEvidenceService`, `RequirementAwareTaskEvidenceSubmissionService` (Talent Mobile task evidence), `BastWorkflowService`, `BastGenerationJobService`, `PayrollExportService`, `BotBridgeWhatsAppOutboundGateway`, `PostgresSourceSyncStateStore`. It adds no second readiness, correction, export or BAST rule.
- It never exposes raw tables or NocoDB state, JIDs, phone numbers or evidence metadata beyond what a PMO reviewer needs.
- **Before every mutation it re-validates authoritative state:** requirement still actionable, correction still reviewable, blocker still active.

## Transport and authentication

- **Base URL:** `{CONFORM_BASE_URL}/api/celerates/v1`. The same Nginx and Cloudflare path as the web app serves it. Celerates calls it only from its server.
- **Authentication:** `Authorization: Bearer <CELERATES_SERVICE_TOKEN>`.
  - The secret is `celerates_service_token` (`CELERATES_SERVICE_TOKEN` or `CELERATES_SERVICE_TOKEN_FILE`, mode 0640). It is separate from `SYNC_INGEST_TOKEN`.
  - It is compared in constant time.
  - Unconfigured → `503 integration_unconfigured`. Wrong → `401 unauthorized`.
- **Actor:** every mutation requires `X-Celerates-Actor`, max 200 characters. Examples: `celerates:Owner Name <owner@example.test>` for PMO; `celerates-talent:<user uuid>` for a talent. ConForm records it as `reviewed_by`, `requested_by_jid`, `exported_by`, `requested_by` or campaign actor.
- **Idempotency:** mutating JSON and multipart commands require `Idempotency-Key` (8–160 characters, `[A-Za-z0-9:_.-]`). The endpoints are listed below.
  - Replays with the same key and the same request hash return the stored response.
  - Replays with a different hash return `409 idempotency_conflict`.
  - Storage: `celerates_idempotency`.
- **Errors:** `{"error": {"code": "…", "message": "…", "retryable": false}}`, with the HTTP status matching.
- **Time:** instants are ISO 8601 with offset. Dates are `YYYY-MM-DD`, Asia/Jakarta business dates.

## Periods

- **Payroll cycle:** `year` and `month` name a Payroll cycle label (`payroll_cycle(year, month)`, closing day 20). For example, `2026-09` covers 2026-08-21 to 2026-09-20.
  - Omitting both means the cycle containing today (Asia/Jakarta).
  - Talent requirements and corrections use this correction-aware projection.
- **BAST:** BAST endpoints use the calendar month `year`-`month` (`BastWorkflowService`).
- **Tasks:** task endpoints use the same calendar month (the Talent Mobile task period). Omitting both means the current month (Asia/Jakarta). The campaign and direct-message task counts use the calendar month the Payroll cycle is named after (`year`, `month`).

## Resources

`Cycle`:
```json
{"id":"2026-09:2026-08-21:2026-09-20","label":"Payroll September 2026","year":2026,"month":9,"start":"2026-08-21","end":"2026-09-20","closing_day":20}
```
- `status`: one of `NEEDS_TALENT_ACTION`, `WAITING_SUBMITTED`, `COMPLETE`.
- `reason`: one of the `AttendanceClosingReason` values.

## Endpoints

| Method and path | Idempotency | Purpose |
|---|---|---|
| `GET /meta` | – | `{api_version:"1", service:"conform", capabilities:[…], now}` |
| `GET /readiness?year&month` | – | Closing summary for the cycle. See below. |
| `GET /talents/lookup?employee_id=` | – | `{employee_id, nrp, name, role, whatsapp_bound}` for identity linking. `404 talent_not_found` |
| `GET /talents/requirements?employee_id&year&month` | – | The talent's open requirements (needs action and waiting review) for the cycle |
| `GET /talents/attendance?employee_id&year&month` | – | The talent's daily attendance log for the cycle. `404 talent_not_found` |
| `GET /talents/tasks?employee_id&year&month` | – | Closed tasks that need evidence in the calendar month. `404 talent_not_found` |
| `POST /talents/tasks/{task_key}/evidence` (multipart) | required | Stage one evidence image on a task (Talent Mobile rule) |
| `POST /talents/tasks/submit` | required | `{employee_id, year, month}` → move staged evidence into the final evidence ("Ajukan ke PMO") |
| `POST /talents/messages` | required | `{employee_id, year, month, link:{url, expires_at\|null}}` → one personal WhatsApp reminder |
| `POST /talents/attendance-corrections` (multipart) | required | Submit a correction and evidence for a requirement that is still actionable |
| `GET /attendance-corrections?year&month` | – | PMO review queue. Without a period: the current and previous cycles |
| `GET /attendance-corrections/{id}` | – | One correction (queue item, or its final status) |
| `GET /attendance-corrections/{id}/evidence` | – | Evidence image bytes (`image/*`) |
| `POST /attendance-corrections/{id}/decision` | required | `{decision:"approve"\|"reject", reason?}` → `PayrollReviewService.bulk_decide` for this id (staleness re-checked) |
| `GET /bast/readiness?year&month&report_type` | – | BAST gate for `developer` or `iotoperation` |
| `POST /bast/generations` | – (the job id is the handle) | `{year, month, report_type, mode:"preview"\|"final", force?, force_reason?}` → `202` job. `409 bast_not_ready` for an ungated final |
| `GET /bast/generations/{job_id}` | – | Job status (`queued`, `running`, `succeeded`, `failed`, `stale`) |
| `GET /bast/generations/{job_id}/document` | – | PDF, only when the job succeeded (`X-Bast-Fingerprint`) |
| `POST /exports/attendance` | – (each call is an audited export) | `{year, month, report_type:"developer"\|"shifting"}` → canonical `;` CSV, with headers `X-Export-Id`, `X-Cycle-Id`, `X-Row-Count` |
| `POST /campaigns` | required | Draft talent-attendance reminder campaign with an audience snapshot |
| `GET /campaigns?limit` / `GET /campaigns/{id}` | – | Campaigns, and one campaign with recipients and events |
| `POST /campaigns/{id}/approve` | required | `{links:[{employee_id, url, expires_at\|null}]}` → `running` |
| `POST /campaigns/{id}/pause` `/resume` `/stop` | required | State control. `pause` takes `{reason?}` |
| `POST /campaigns/dispatch` | – | Scheduler tick; also called by the `pmo-notifications` flow |
| `GET /control` / `PUT /control` | PUT required | `{kill_switch}` |
| `GET /pmo-summary/preview?year&month&link=` | – | Aggregate PMO group text |
| `POST /pmo-summary/send` | required | `{year, month, link}` → group message, one per cycle and day |

### `GET /readiness`

```json
{"cycle": {…}, "evaluated_through": "2026-09-20",
 "summary": {"total_talents":12,"complete":9,"waiting_submitted":1,"needs_talent_action":2,"unverified":0},
 "talents": [{"employee_id":"MTG-TF/2025070332","nrp":"…","name":"…","role":"Developer","status":"NEEDS_TALENT_ACTION",
              "actionable_days":1,"waiting_days":0,"unverified_days":0,"whatsapp_bound":true}],
 "pending_corrections": 1,
 "sources": [{"source_key":"attendance","label":"PAMA attendance","last_success_at":"…","age_seconds":3600}],
 "bast": [{"report_type":"developer","ready":false,"ready_talents":9,"total_talents":10}]}
```

### `GET /talents/requirements`

Each requirement:
```json
{"requirement_id":"attendance:2026-09-01","kind":"attendance_gap","work_date":"2026-09-01",
 "attendance_key":"attendance:2026-09-01:MTG-TF/…","gap":"missing_clock_in",
 "raw_check_in":null,"raw_check_out":"17:02","state":"needs_action","reason":"GAP_UNCOVERED",
 "allowed_actions":["worked"],
 "correction":{"id":"…","status":"rejected","resolution_type":"missing_clock_in","absence_type":null,
               "proposed_check_in":"08:00","proposed_check_out":null,"rejection_reason":"…"}}
```
- `state` is either `needs_action` or `waiting_review`.
- `allowed_actions` depends on the gap:
  - `missing_clock_in` and `missing_clock_out` → `["worked"]`;
  - `missing_both` → `["worked","sakit","izin","cuti","libur"]`.
- `attendance_key` is `null` when no source row exists yet. The submit creates the manual stub row, exactly as Talent Mobile does.

### `POST /talents/attendance-corrections`

- Fields: `employee_id`, `work_date`, `action`, `check_in?`, `check_out?`, `caption?`, `file` (JPG, PNG or WebP, 5 MB max).
- The flow is the Talent Mobile rule set, anchored on the Payroll projection instead of the calendar-month completion:
  1. The day must be `talent_action_required`, else `409 requirement_not_actionable`.
  2. `resolution_shape` validates the action.
  3. `AttendanceEvidenceService.upload`, then `AttendanceResolutionService.submit`.
- Response: `201 {"status":"submitted"|"already_open","correction_id","requirement_id"}`.

### `GET /talents/attendance`

```json
{"employee_id":"…","cycle":{…Cycle…},"source":"conform:pama","evaluated_through":"2026-09-20",
 "days":[{"work_date":"2026-09-01","check_in":"07:58","check_out":"17:02","origin":"pipeline",
          "state":"complete","gap":null,"reason":"RAW_COMPLETE","evidence_count":0,
          "correction":{"id":"…","status":"approved","resolution_type":"missing_clock_in","absence_type":null,
                        "proposed_check_in":"08:00","proposed_check_out":null,"rejection_reason":null}}]}
```
- Read-only. One entry per projected day of the cycle up to `evaluated_through`, ascending (none when `evaluated_through` is `null`). It is the Payroll projection used by `/talents/requirements`; no rule is added.
- `check_in` / `check_out`: raw `HH:MM` (Asia/Jakarta) or `null`. `origin`: `pipeline`, `manual` (a stub row created by a correction, or a row edited by hand) or `null` (no source row). `evidence_count`: attendance evidence files on that row. `correction`: the latest correction (approved, then pending, then the newest rejected), or `null`. `reason`: the raw `AttendanceClosingReason`.
- `state` is a mapping of the projection, in this order:

  | Projection | `state` |
  |---|---|
  | OFF schedule (`SCHEDULED_OFF`) | `not_required` |
  | `talent_action_required` (`GAP_UNCOVERED`, `CORRECTION_REJECTED`, and `SOURCE_UNAVAILABLE` on a working day, the same set `/talents/requirements` shows as `needs_action`) | `needs_action` |
  | `WAITING_SUBMITTED` (`GAP_COVERED_BY_SUBMITTED_REQUEST`) | `waiting_review` |
  | `GAP_COVERED_BY_APPROVED_CORRECTION` with `resolution_type = absence` (sakit, izin, cuti, libur) | `excused` |
  | Other `COMPLETE` (`RAW_COMPLETE`, approved clock correction) | `complete` |
  | Anything else | `unverified` (the current projection produces none: a working day without a source row is actionable) |
- `gap`: `null` for `not_required` and for days with both raw clocks; otherwise `missing_clock_in`, `missing_clock_out` or `missing_both` from the raw clocks (kept for corrected and excused days).

### Tasks (Talent Mobile rules, unchanged)

`GET /talents/tasks`:
```json
{"employee_id":"…","period":{"year":2026,"month":9,"start":"2026-09-01","end":"2026-09-30","label":"September 2026"},
 "summary":{"total":14,"complete":11,"missing":3,"staged":1},
 "items":[{"task_key":"…","title":"…","work_date":"2026-09-03","task_source":"redmine","status":"Closed",
           "evidence_count":0,"staged_count":1,"complete":false}]}
```
- Items are the Closed Redmine and IoT-sheet tasks in the month whose category requires evidence (`bast_evidence_rules`), as in Talent Mobile. `complete` means final evidence exists. `staged` counts incomplete tasks with staged evidence. Missing items first, then `work_date` descending. `period.label` uses Indonesian month names (for example `Agustus 2026`).

`POST /talents/tasks/{task_key}/evidence` (multipart `employee_id`, `year`, `month`, `file`, `caption?`):
- `201 {"status":"staged"|"already_present"}`. The request hash covers the file bytes.
- Errors: `404 task_not_found` (not an evidence task of this Talent in the month), `409 task_changed`, `413 file_too_large` (5 MB), `415 unsupported_type` (JPG, PNG or WebP).

`POST /talents/tasks/submit` (`{employee_id, year, month}`):
- `200 {"status":"submitted","count":N}`. Errors: `409 nothing_staged`, `409 task_changed`.
- `X-Celerates-Actor` is recorded as `task_evidence.submitted_by_jid`. Task evidence has no PMO approval (existing behaviour).

### `POST /talents/messages` (direct message)

- Body: `{employee_id, year, month, link:{url, expires_at|null}}`. `year`/`month` name the Payroll cycle; the task count uses that calendar month.
- Validation: `422 link_not_allowed` when `CELERATES_PUBLIC_URL` is set and `url` does not start with it; `422 invalid_link_expiry` when `expires_at` is in the past; `404 talent_not_found`.
- Checks, in order: kill switch → `409 kill_switch`; WhatsApp binding → `409 not_bound`; a direct message to the same employee in the last 10 minutes (`sending`, `sent` or `unknown`; a failed attempt does not count) → `409 recently_sent`. The check and the insert are atomic per employee. The campaign sending window does not apply.
- Message: a greeting with the Talent's first name, the open attendance days of the cycle (up to five dates listed) and the number of tasks without evidence in the month, then the link. With nothing open it says everything is complete and still carries the link. No ids, JIDs or phone numbers.
- Sent through the bridge with `request_id = celerates-direct:<id>`.
- Responses: `201 {"status":"sent","message_id":"<id>","sent_at":"…"}`; `202 {"status":"unknown","message_id":"<id>"}` (`delivery_outcome_unknown`; never resent automatically); `503 transport_unavailable` (`retryable: true`); `503 transport_auth_failed`; `502 delivery_failed` (any other bridge refusal). Errors are not stored for idempotent replay, so the same `Idempotency-Key` may be retried after a `503`.
- Audit: `celerates_direct_messages` (status `sending` → `sent` | `failed` | `unknown`, actor, link, attendance and task counts, provider message id, error).
- A `sent` direct message counts as a recent send for the campaigns' 20-hour cross-campaign dedupe.

### Campaigns

**Create body:** `{year, month, window_start_hour=8, window_end_hour=18, batch_size=10 (1–50), cooldown_seconds=600 (60–86400), min_interval_seconds=3 (0–60), max_attempts=3 (1–5)}`.

**Audience snapshot:**
- Every talent with actionable days in the cycle **or** tasks without evidence in the calendar month named by the cycle (`year`, `month`) becomes a recipient row with a fingerprint of its actionable dates and those task keys (dates only when no task is open, so earlier fingerprints are unchanged).
- Recipient rows carry `actionable_days` and `missing_tasks`.
- `eligibility` is `eligible` when WhatsApp is bound, otherwise `not_bound`.
- The message (`compose_talent_message`) mentions both counts.

**Approve:**
- Recipients without a supplied link become `skipped_no_account`.
- If `CELERATES_PUBLIC_URL` is configured, links must start with it (`422 link_not_allowed`).
- `expires_at` is nullable: `null` means the link never expires by time (Celerates enforces single use and supersession). A non-null expiry must be in the future and within 7 days (`422 invalid_link_expiry`).

**Recipient states:** `pending`, `sending`, `sent`, `failed_retryable`, `failed_final`, `unknown`, `skipped_resolved`, `skipped_recent`, `skipped_link_expired`, `skipped_no_account`, `skipped_not_bound`, `skipped_stopped`.

**Campaign states:** `draft` → `running` → (`paused` ↔ `running`) → `completed` | `stopped`.

**Dispatch (per tick, per running campaign; `pg_advisory_xact_lock` per campaign):**
1. Do nothing if the kill switch is on, outside the window, or before `next_dispatch_at`.
2. Project the cycle once.
3. Take up to `batch_size` recipients in state `pending` or `failed_retryable`, in order.
4. For each recipient:
   1. Re-check the blocker (open attendance days or tasks without evidence), recent sends (20 h, across campaigns and direct messages), link expiry (only a non-null expiry in the past skips) and the JID.
   2. Mark it `sending`.
   3. Send with `request_id = celerates-campaign:<recipient id>`.
   4. Record the outcome.
   5. Sleep `min_interval_seconds` before the next recipient.
5. Outcome handling:
   - `bridge_unavailable` → `failed_retryable` (becomes `failed_final` at `max_attempts`) and the campaign auto-pauses (`transport_unavailable`).
   - `delivery_outcome_unknown` → `unknown`, which is never retried; auto-pause.
   - `bridge_auth_failed` → auto-pause (`transport_auth_failed`).
   - A `sending` row found on a later tick becomes `unknown`.
6. `next_dispatch_at = now + cooldown_seconds`. The campaign is `completed` when nothing is pending or retryable.

**Audit:** every transition and outcome is written to `celerates_campaign_events` with its actor.

## Bot `masuk` (WhatsApp re-entry; Celerates is the grant authority)

- A DM from a **bound** JID whose whole message (trimmed, case-insensitive) is `masuk`, `login` or `link` calls `POST {CELERATES_PUBLIC_URL}/api/internal/talent/links` with `Authorization: Bearer <CELERATES_SERVICE_TOKEN>` and `{"employee_id":"…"}` (5 s timeout).
- `200 {"url","expires_at"}` → the bot replies with the link and "Link ini hanya bisa dipakai sekali." A `url` outside `CELERATES_PUBLIC_URL` is treated as a failure.
- `404 {"error":{"code":"no_account"}}` → the bot replies that the Celerates account is not active yet and to contact PMO. Any other outcome → a short "coba lagi nanti" reply.
- The words are checked before every other DM route (reminder contexts, the natural attendance parser, menus, the LLM interpreter), except that `masuk` stays an answer ("masuk kerja") while an attendance correction draft is open.
- Unconfigured (no `CELERATES_PUBLIC_URL` or no token): not intercepted; behaviour unchanged. Unbound JID: not intercepted; the existing not-bound reply.

## Configuration (ConForm)

| Setting | Purpose |
|---|---|
| `CELERATES_SERVICE_TOKEN` / `_FILE` | Adapter bearer secret (≥ 32 characters). |
| `CELERATES_PUBLIC_URL` | Optional allow-list prefix for campaign and direct-message links; with the token, also enables the bot `masuk` link request. |
| `BOT_BRIDGE_BASE_URL` plus the bridge token | Existing transport; unchanged. |
| `BAST_RENDERER_URL`, `BAST_EXPORTS_DIR` | Existing BAST pipeline; unchanged. |

Existing scheduled Payroll and BAST Talent reminders (`payroll_closing` / `bast_closing` `enabled`) **stay off** while Celerates campaigns are the target surface, so a gap never gets two reminders.

## Known provider defects surfaced during integration (not changed here)

- **BAST readiness vs Payroll readiness.** `domain/completion` treats any attendance evidence as complete, even after a rejected correction; Payroll does not.
- **BAST PDF overwrites.** The PDF path is per team and month, so a later generation overwrites an earlier one. The fingerprint also ignores corrections.
- **Unguarded group commands.** Group-chat `generate bast` and `export attendance` bypass operator checks, the readiness gate and the audit.
- **Unreachable PMO DM path.** `dm_entry` returns the not-bound reply for PMO DMs before operator routing.
- **Task evidence insert.** `task_evidence` `ON CONFLICT (task_id, sha256)` had no matching unique index since migration 0011, so the final "Ajukan ke PMO" move failed on PostgreSQL. Fixed 2026-09-29 by dropping the conflict target (0011 allows repeated uploads on purpose).
