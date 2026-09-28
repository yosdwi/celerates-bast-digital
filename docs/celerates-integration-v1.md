# Celerates integration API v1 (provider contract)

Status: v1, implemented 2026-09-28 on `chore/session-20260918-fixes`.

Product decision: Celerates is the single user-facing operational product. ConForm stays an independent bounded service that owns readiness, corrections, evidence, the canonical BAST, the canonical attendance CSV, WhatsApp identity and delivery. Consumer-side requirements, identity, RBAC, journeys and the retirement plan are in `celerates-digital-intelligence/docs/21-conform-bounded-service-execution.md` (execution record; planning record doc 19) and ADR-019.

This document is the **authoritative wire contract**. A breaking change requires `/api/celerates/v2`.

## Ownership (what this adapter must never do)

- It reuses existing services only: `PayrollReadService`, `PayrollReviewService`, `AttendanceResolutionService`, `AttendanceEvidenceService`, `BastWorkflowService`, `BastGenerationJobService`, `PayrollExportService`, `BotBridgeWhatsAppOutboundGateway`, `PostgresSourceSyncStateStore`. It adds no second readiness, correction, export or BAST rule.
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
| `POST /campaigns/{id}/approve` | required | `{links:[{employee_id, url, expires_at}]}` → `running` |
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

### Campaigns

**Create body:** `{year, month, window_start_hour=8, window_end_hour=18, batch_size=10 (1–50), cooldown_seconds=600 (60–86400), min_interval_seconds=3 (0–60), max_attempts=3 (1–5)}`.

**Audience snapshot:**
- Every talent with actionable days in the cycle becomes a recipient row with a fingerprint of its actionable dates.
- `eligibility` is `eligible` when WhatsApp is bound, otherwise `not_bound`.

**Approve:**
- Recipients without a supplied link become `skipped_no_account`.
- If `CELERATES_PUBLIC_URL` is configured, links must start with it (`422 link_not_allowed`).

**Recipient states:** `pending`, `sending`, `sent`, `failed_retryable`, `failed_final`, `unknown`, `skipped_resolved`, `skipped_recent`, `skipped_link_expired`, `skipped_no_account`, `skipped_not_bound`, `skipped_stopped`.

**Campaign states:** `draft` → `running` → (`paused` ↔ `running`) → `completed` | `stopped`.

**Dispatch (per tick, per running campaign; `pg_advisory_xact_lock` per campaign):**
1. Do nothing if the kill switch is on, outside the window, or before `next_dispatch_at`.
2. Project the cycle once.
3. Take up to `batch_size` recipients in state `pending` or `failed_retryable`, in order.
4. For each recipient:
   1. Re-check the blocker, recent sends (20 h, across campaigns), link expiry and the JID.
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

## Configuration (ConForm)

| Setting | Purpose |
|---|---|
| `CELERATES_SERVICE_TOKEN` / `_FILE` | Adapter bearer secret (≥ 32 characters). |
| `CELERATES_PUBLIC_URL` | Optional allow-list prefix for campaign links. |
| `BOT_BRIDGE_BASE_URL` plus the bridge token | Existing transport; unchanged. |
| `BAST_RENDERER_URL`, `BAST_EXPORTS_DIR` | Existing BAST pipeline; unchanged. |

Existing scheduled Payroll and BAST Talent reminders (`payroll_closing` / `bast_closing` `enabled`) **stay off** while Celerates campaigns are the target surface, so a gap never gets two reminders.

## Known provider defects surfaced during integration (not changed here)

- **BAST readiness vs Payroll readiness.** `domain/completion` treats any attendance evidence as complete, even after a rejected correction; Payroll does not.
- **BAST PDF overwrites.** The PDF path is per team and month, so a later generation overwrites an earlier one. The fingerprint also ignores corrections.
- **Unguarded group commands.** Group-chat `generate bast` and `export attendance` bypass operator checks, the readiness gate and the audit.
- **Unreachable PMO DM path.** `dm_entry` returns the not-bound reply for PMO DMs before operator routing.
- **Task evidence insert.** `task_evidence` `ON CONFLICT (task_id, sha256)` has no matching unique index since migration 0011.
