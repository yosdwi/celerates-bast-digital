# Payroll Attendance — Current Execution Checkpoint

This is the small rolling execution checkpoint for
`docs/payroll-attendance-implementation-plan.md`.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`  
Checkpoint date: 19 September 2026

## Completed through P08

P00–P06 remain completed as recorded in the master implementation plan.

### P07 — Stable reminder context schema

Status: `DONE`

Commits:

- `29bc1e2fd263f78703b067ce43dcad915a4dd00b` — additive DB schema.
- `b1d817abca44f31bae522fec7d11cc3003623229` — typed durable context service.
- `e21f521c60d1ed5a57354d6ab8c483024ca5c8be` — initial context tests.
- `019626df38253df52c82ac91f068c8985d34b2e8` — strict JSON parsing hardening.
- `4be5fd809f72c0043affda50647461861a60b9d6` — final-service-aligned test fakes.

Files:

- `migrations/versions/20260919_0022_attendance_reminder_context.py`
- `src/digital_bast/bot/attendance_context.py`
- `tests/unit/bot/test_attendance_context.py`

Delivered contract:

- Stable reminder snapshot is separate from legacy `bot_conversations.updated_at`
  and existing `talent_context_*` navigation state.
- Snapshot stores `context_id`, schema `version`, canonical `employee_id`, immutable
  Payroll `cycle_id`, exact ordered attendance keys, and absolute `expires_at`.
- JSONB is used only to preserve ordered attendance identities. It does not store
  Payroll status/readiness/business decisions.
- User-visible numbering is 1-based and resolves only against the persisted
  snapshot. If item 1 changes elsewhere, reply `2` still resolves to the exact
  attendance identity originally sent as item 2.
- Empty, duplicate, oversized, malformed or corrupt key snapshots fail closed.
- Expired context loads as no active context.
- Saving/clearing attendance context does not mutate `talent_context_*`, pending
  task/image state, or the legacy conversation `updated_at` TTL.
- P07 adds no reminder dispatch, DM routing or attendance mutation behavior.

Migration chain:

`20260911_0021 -> 20260919_0022`

### P08 — Reminder message composer

Status: `DONE`

Commits:

- `a074bd7397592a28f4148cd13eacf393209820ab` — initial Payroll attendance reminder composer.
- `6dfa9d145af7a347ca885b7a9d484230df3ff672` — initial composer unit coverage.
- `6833ce522b3b2e3298f5f878c52323119438dcaf` — transport-safe/public action contract hardening.
- `302de2e3122f10eebfc46e48e52a83e9fb00eb44` — ordering, duplicate and concise-message test hardening.
- `47d6fc2a80db7419897455222cd79c4642ef6040` — strict-safe rejected-action lookup.

Files:

- `src/digital_bast/bot/attendance_reminder.py`
- `tests/unit/bot/test_attendance_reminder.py`

Delivered contract:

- Composer is side-effect free: no WhatsApp send and no attendance mutation.
- It consumes the P03 Payroll closing projection and includes only rows currently
  marked `talent_action_required=true`.
- `WAITING_SUBMITTED`, `COMPLETE` and source-unverified-only Talent produce no
  reminder draft.
- Any actionable row without a canonical attendance key fails closed rather than
  producing a reminder that cannot later be resolved safely.
- The draft carries the exact P07 `AttendanceReminderContext` with canonical
  employee ID, immutable cycle ID, ordered actionable attendance keys and expiry.
- Actionable rows are ordered chronologically before both rendering and snapshot
  creation, so the message and persisted context share one order.
- Normal gaps use direct wording such as `Clock Out belum ada`; rejected requests
  use current-action wording such as `Clock Out perlu diperbaiki` rather than
  pretending the previous submission never happened.
- Reminder exposes only two decisions: `Lengkapi` and `Nanti`, with stable public
  action IDs for P09 and a plain-text `1/2` plus `lengkapi/nanti` fallback.
- At most five gap lines are rendered to keep WhatsApp concise; additional current
  gaps are summarized as `+N attendance lainnya`, while the P07 snapshot still
  retains every actionable attendance key.
- The existing `InteractiveReply` envelope can be produced when a transport
  supports it, but current scheduled follow-up plain-text outbound is not changed
  in P08. This prevents accidental JSON-as-text delivery.
- Existing monthly BAST `TalentReminderService` behavior remains untouched.

Validation evidence:

- P07→P08 branch compare contains only the composer and its unit-test file.
- Tests cover actionable-only filtering, chronological stable snapshot order,
  waiting/complete/unverified skip behavior, unaddressable/duplicate fail-closed,
  rejected correction wording, two-action fallback, and large-list truncation
  without losing snapshot identities.
- Full repository `pytest + ruff + basedpyright` is not claimed in this tool
  environment because there is no repository checkout/dependency runtime attached
  to the GitHub connector. PR/main CI remains the complete quality gate.

## Next card

**P09 — Reminder -> current gap routing**

Scope remains locked:

- `dm_entry.py` / attendance workflow recognize the P08 start/later action IDs and
  their text/number fallback after the gateway resolves them.
- Load the P07 stable reminder context; never rebuild the sent list from a fresh
  projection merely to interpret the reply.
- `Lengkapi` opens the first still-actionable attendance identity from the stable
  snapshot directly in WhatsApp.
- Before opening/mutating, revalidate identity ownership and current projection.
  Skip snapshot items that are no longer actionable instead of changing the
  meaning/order of later items.
- If no snapshot item remains actionable, clear/finish the reminder flow with a
  concise no-action message; do not send Talent to Mobile or a generic menu.
- `Nanti` ends the immediate prompt without mutating attendance.
- Do not implement time entry/evidence mutation yet; collecting the missing clock
  starts in P10.

For a new session: read the master implementation plan first, then this checkpoint,
verify branch HEAD, and continue P09 without redesigning locked requirements.
