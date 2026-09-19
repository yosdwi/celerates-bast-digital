# Payroll Attendance — Current Execution Checkpoint

This is the rolling execution checkpoint for
`docs/payroll-attendance-implementation-plan.md`.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`  
Checkpoint date: 20 September 2026

## Execution standard

This project follows `docs/development-execution-standard.md`.

Cards remain audit/commit boundaries, but implementation proceeds by end-to-end
waves. Keep changes small and reversible, preserve source-of-truth boundaries, and
checkpoint only after integration/validation review. The canonical Payroll plan
remains authoritative; this file records the latest execution state.

## Completed through P27

P00–P14 remain completed as recorded in the canonical implementation plan and
prior checkpoint history.

P15–P18 delivered the PMO Payroll review queue, evidence inspection, per-item
revalidation, bulk approve/reject with partial success, and rejection back into
the existing Talent correction lifecycle.

P19–P22 delivered the Contacts & WhatsApp Mapping wave:

- real group/member discovery through the active `whatsapp-web-session` runtime,
- Talent↔WhatsApp mapping using existing `wa_identity`,
- Contacts & WhatsApp operational UI,
- one stable configured Payroll closing-group JID,
- no provider migration, fuzzy identity inference, or group outbound cutover.

P23–P27 delivered the Reminder Automation Foundations wave described below.

---

## Wave 5 — Reminder Automation Foundations (P23–P27)

Status: `DONE`

Baseline before this wave:

- `0703ddd9c8c94414bc8bb523fdf65e99a675dcab`

Pre-checkpoint implementation head:

- `73e4200001cf4d2027cae9d4d25cbaf4c7819094`

Comparison from the P22 checkpoint baseline to the P27 pre-checkpoint head:

- 31 commits ahead,
- 0 commits behind,
- 20 changed files,
- scope limited to Payroll closing policy/settings, reminder scheduling/runtime,
  durable delivery lifecycle, response correlation, UI/API, additive migrations,
  and focused tests.

No legacy attendance CSV contract, raw attendance authority, BAST monthly/calendar
semantics, or active WhatsApp provider was replaced by this wave.

### P23 — Closing settings migration/control model

Status: `DONE`

Delivered:

- Added migration `20260919_0024_payroll_closing_policy` after P22 migration
  `0023`.
- Extended the existing `workflow_notification_settings` control-plane instead of
  creating another workflow/settings database.
- Added an independent typed Payroll closing policy with:
  - enabled state,
  - pause state,
  - closing day,
  - reminder hour,
  - H-N reminder offsets,
  - target Talent roles,
  - next-day evaluation-ready hour,
  - desired policy version,
  - applied policy version,
  - updated-by audit identity.
- Payroll closing settings do **not** reuse legacy BAST `talent_reminder_days`.
  The two concepts retain separate semantics.
- Migration/default policy is `enabled=false`, so applying schema alone cannot
  unexpectedly start a Payroll reminder campaign.
- The configured next-day ready hour is wired into Closing Projection evaluation;
  it is not a display-only setting.
- Validation remains fail-closed for unsupported roles, invalid closing day/hour,
  invalid reminder offsets, and invalid desired/applied version relationships.

Primary files:

- `migrations/versions/20260919_0024_payroll_closing_policy.py`
- `src/digital_bast/application/payroll_closing_settings.py`
- `src/digital_bast/infrastructure/payroll_closing_settings.py`
- `src/digital_bast/application/payroll_read.py`
- `tests/unit/application/test_payroll_closing_settings.py`

### P24 — Reminder settings UI + preview

Status: `DONE`

Delivered:

- Added typed Payroll closing settings API under the existing Payroll router.
- Added compact Settings UI component:
  `frontend/src/components/PayrollClosingPolicySettings.tsx`.
- Operators can inspect/edit the supported policy without a generic workflow
  designer.
- Preview is computed from the same cycle/policy/projection authority and exposes:
  - current Payroll cycle,
  - H-N milestone dates,
  - estimated actionable Talent audience,
  - estimated technically unverified Talent count,
  - desired/applied policy version.
- Source-unverified attendance is kept separate from Talent-action audience and is
  not presented as Talent fault.
- Save remains CSRF-protected and owner/admin-authorized.

Primary files:

- `src/digital_bast/web/payroll_contracts.py`
- `src/digital_bast/web/payroll_router.py`
- `frontend/src/api/payroll.ts`
- `frontend/src/components/PayrollClosingPolicySettings.tsx`
- `frontend/src/pages/SettingsPage.tsx`

### P25 — Durable logical delivery reservation

Status: `DONE`

Delivered:

- Added migration `20260919_0025_payroll_delivery_lifecycle` after `0024`.
- Reused existing `talentops_followups` as the durable logical-delivery ledger;
  no separate reminder queue/event bus was introduced.
- Added explicit Payroll delivery lifecycle:
  - `RESERVED`
  - `SENDING`
  - `SENT`
  - `FAILED_RETRYABLE`
  - `FAILED_FINAL`
  - `UNKNOWN`
- Reservation uses a stable idempotency key per scope/cycle/milestone/Talent.
- Retryable transport failure reuses the same logical delivery and increments an
  attempt count instead of creating duplicate follow-up rows.
- A process interruption after delivery claim is handled conservatively: a
  pre-existing `SENDING` state encountered on a later run becomes `UNKNOWN` and is
  **not** blindly resent.
- Provider receipt/error facts, context identity, cycle, milestone, timestamps,
  and response-correlation fields are retained on the ledger.
- SQL statements remain static with bound values; the final adapter no longer
  relies on concatenated query construction.

Primary files:

- `migrations/versions/20260919_0025_payroll_delivery_lifecycle.py`
- `src/digital_bast/application/payroll_reminder_delivery.py`
- `src/digital_bast/infrastructure/payroll_reminder_delivery.py`
- `tests/unit/application/test_payroll_reminders.py`

### P26 — Scheduled Talent reminder cutover

Status: `DONE`

Delivered:

- Kept the existing scheduler/Prefect cadence; no new scheduling service was
  introduced.
- Added `PayrollTalentReminderService` over the canonical Closing Projection,
  current configured policy, existing WhatsApp identity binding, stable reminder
  context, existing outbound gateway, and durable delivery ledger.
- Only current Talent rows with real `talent_action_required=true` are eligible.
- WAITING, COMPLETE, technically unverified-only, and unsafe/no-stable-attendance-
  identity cases are not silently converted into Talent action.
- Stable P07 attendance context is persisted before outbound so user-visible
  numbering remains bound to the exact ordered attendance identities sent.
- Unbound Talent is recorded as a final non-deliverable outcome rather than being
  guessed from names/numbers.
- While Payroll policy is disabled, the legacy BAST Talent reminder path continues
  unchanged.
- Once Payroll policy is enabled, Payroll becomes the scheduled Talent reminder
  authority for that scope, including when the Payroll policy is paused. This
  prevents a paused Payroll campaign from silently falling back to the legacy path
  and double-sending.
- Active WhatsApp transport remains the existing `whatsapp-web-session` /
  `whatsapp-web.js` bridge.

Primary files:

- `src/digital_bast/application/payroll_reminders.py`
- `src/digital_bast/payroll_runtime.py`
- `src/digital_bast/bot/attendance_reminder_runtime.py`
- `src/digital_bast/flows/notifications.py`
- `tests/unit/application/test_payroll_reminders.py`

### P27 — Correlated response tracking

Status: `DONE`

Delivered:

- Added response correlation against the specific successful Payroll reminder
  context/delivery.
- `responded_at` is written only after a subsequent attendance interaction that
  successfully routes into the Payroll attendance action flow.
- Generic DM traffic, navigation, `Nanti`, and generic conversation
  `bot_conversations.updated_at` do not count as a Payroll attendance response.
- Correlation requires matching stable reminder context + employee identity and a
  `SENT` logical delivery.
- This creates the required source for later `unresponded` projections without
  inventing engagement from unrelated chat activity.

Primary files:

- `src/digital_bast/bot/attendance_reminder_runtime.py`
- `src/digital_bast/application/payroll_reminder_delivery.py`
- `src/digital_bast/infrastructure/payroll_reminder_delivery.py`
- `tests/unit/bot/test_attendance_reminder_response_tracking.py`

### Validation truth

Validation PR #73 CI run `#505` / `35454927546` on pre-checkpoint head
`73e4200001cf4d2027cae9d4d25cbaf4c7819094`:

- `uv sync --all-groups`: **PASS**.
- `uv run python -m compileall -q src tests`: **PASS**.
- `migration-smoke`: **PASS**.
  - migration gate: PASS,
  - migration idempotency gate: PASS,
  - smoke/shadow gate: PASS.
- `gitleaks`: **PASS**.
- repository-wide `uv run ruff check .`: **FAIL** with 108 existing findings.
- After the final P23–P27 lint cleanup, none of the new P23–P27 implementation
  files appears in the current Ruff failure list, including:
  - `src/digital_bast/application/payroll_closing_settings.py`
  - `src/digital_bast/application/payroll_reminder_delivery.py`
  - `src/digital_bast/application/payroll_reminders.py`
  - `src/digital_bast/infrastructure/payroll_closing_settings.py`
  - `src/digital_bast/infrastructure/payroll_reminder_delivery.py`
  - `src/digital_bast/payroll_runtime.py`
  - `src/digital_bast/web/payroll_router.py`
  - `tests/unit/application/test_payroll_closing_settings.py`
  - `tests/unit/application/test_payroll_reminders.py`
  - `tests/unit/bot/test_attendance_reminder_response_tracking.py`
- Remaining Ruff findings are branch-wide debt from earlier Payroll cards and
  unrelated legacy/BAST/infrastructure code. They intentionally were not swept
  into this wave.
- Because repository-wide Ruff fails first, the quality job does **not** reach
  `basedpyright`, `pytest`, or `scripts/check-ops.sh`; a full green quality job is
  therefore not claimed.
- The container job failure is infrastructure/setup-only: GitHub Actions cannot
  resolve `aquasecurity/trivy-action@0.30.0`. It fails in job setup before checkout
  or image build, so it does not execute or invalidate P23–P27 application code.
- Frontend component behavior is implemented, but this repository CI does not run
  the frontend npm test/typecheck suite; a frontend green suite is not claimed.

PR #73 is used only as a CI validation trigger for the long-lived working branch.
It is **not** a merge/release candidate and must not be merged into `main`.

### Wave acceptance result

The system now has the following end-to-end reminder foundation:

```text
Payroll closing policy (disabled by default)
  -> real 21–20 cycle + H-N milestone evaluation
  -> canonical Closing Projection
  -> current actionable Talent audience only
  -> stable attendance reminder context
  -> durable logical delivery reservation
  -> existing WhatsApp outbound transport
  -> SENT / retryable / final / UNKNOWN receipt state
  -> subsequent attendance action correlated back to the exact reminder
```

without converting evidence into approval truth, storing a synthetic
`payroll_ready` flag, changing the legacy CSV contract, adding a new transport,
or using generic conversation timestamps as response evidence.

---

## Next execution wave — PMO Closing Digest & Follow-up (P28–P30)

Execute P28–P30 continuously as one integration wave unless an implementation
finding creates a genuine source-of-truth conflict.

### P28 — Digest projection

Status: `TODO`

Build the PMO-facing closing digest projection from existing Payroll truth and
P25/P27 delivery facts. Keep business status to the locked three primary states;
`unverified`, delivery failure, and `unresponded` remain operational dimensions,
not new Payroll readiness states.

Expected digest dimensions include current cycle summary, actionable Talent,
waiting submissions, technical-unverified cases, delivery failures/UNKNOWN, and
Talent who received a successful reminder but have not subsequently entered the
attendance action flow.

### P29 — Group digest outbound

Status: `TODO`

Use the configured P22 Payroll closing-group JID and existing WhatsApp session to
send PMO digest messages only at the intended closing milestones/final/incident
conditions. Do not send per-Talent correction submissions to the PMO group.

Group delivery must use durable/idempotent delivery semantics and must not alter
Talent reminder authority or attendance truth.

### P30 — Follow-up panel actions

Status: `TODO`

Expose the digest/follow-up projection on the PMO web surface with operational
actions for items that need attention. Reuse current review/mapping/reminder
contracts rather than creating a second task system.

The panel should make it easy to distinguish:

- Talent still needing attendance action,
- Talent already submitted/waiting review,
- source-unverified technical cases,
- reminder delivery failures/UNKNOWN,
- successfully reminded but genuinely unresponded Talent.

### Continuation instructions

For a new session:

1. Read `docs/development-execution-standard.md`.
2. Read `docs/payroll-attendance-implementation-plan.md`.
3. Read this rolling checkpoint.
4. Verify branch HEAD and inspect any commits after this checkpoint before editing.
5. Continue with P28–P30 as one integration wave without redesigning the locked
   Payroll, review, identity, delivery, or WhatsApp source-of-truth boundaries.
