# Payroll Attendance — Current Execution Checkpoint

This is the small rolling execution checkpoint for
`docs/payroll-attendance-implementation-plan.md`.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`  
Checkpoint date: 19 September 2026

## Completed through P09

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
  use current-action wording such as `Clock Out perlu diperbaiki`.
- Reminder exposes only two decisions: `Lengkapi` and `Nanti`, with stable public
  action IDs and a plain-text `1/2` plus `lengkapi/nanti` fallback.
- At most five gap lines are rendered; the P07 snapshot still retains every
  actionable attendance key.
- Current scheduled follow-up plain-text outbound is not changed in P08.
- Existing monthly BAST `TalentReminderService` behavior remains untouched.

### P09 — Reminder -> current gap routing

Status: `DONE`

Commits:

- `db9cc446cdaaef757fb27948e21d95b84e32e88f` — stable-snapshot gap routing core.
- `845cfd92e9e4b7fab17b3d86df727ae32f3ea49d` — routing/parser/prompt unit coverage.
- `4eaae7108cb51e5300df6106543fa80500bca417` — production runtime assembly.
- `117c8c6cc055f2db8f46d1e8b072344a18af874b` — DM entry routing integration.
- `dfc118e52d12627ac95fa76d3a30aff17b597aa5` — Payroll reminder DM integration tests.
- `fbd676fef9294a73bd1aac6fee0374ca7af8c8ec` — legacy bare-digit regression lock.
- `066c69d0101e7cab0c7b1996ed6efe8c767ffa89` — strict type/style hardening for routing.
- `c7b115a7dc2b47237c0ecfaaeec4104ebbb5be63` — runtime configuration error alignment.
- `853c3c43c3ba0609988ca1a0428cf01336a79cc2` — DM message line-length/style hardening.

Files:

- `src/digital_bast/bot/attendance_reminder_routing.py`
- `src/digital_bast/bot/attendance_reminder_runtime.py`
- `src/digital_bast/bot/dm_entry.py`
- `tests/unit/bot/test_attendance_reminder_routing.py`
- `tests/unit/bot/test_dm_entry_payroll_reminder.py`
- `tests/unit/bot/test_dm_entry.py`

Delivered contract:

- P08 action IDs, exact `lengkapi/nanti`, and guarded `1/2` fallback are recognized.
- A P07 context is re-read and ownership checked against the currently bound Talent.
- The stored cycle ID is validated before current Payroll projection is loaded.
- `Lengkapi` walks the persisted attendance-key order and selects the first key that
  is still `talent_action_required=true` in the fresh P03 projection.
- If an earlier snapshot key has already become complete/waiting, it is skipped;
  later keys keep their original identity/order rather than being renumbered.
- The direct WhatsApp prompt asks only the current missing fact, for example:
  `Clock In tercatat 07:32` -> `Jam pulang berapa?`.
- Rejected corrections use correction-specific wording such as
  `Jam pulang yang benar berapa?`.
- Multiple remaining snapshot items are summarized only as a small remaining count.
- `Nanti` performs no attendance mutation and keeps the stable snapshot available
  until its normal expiry.
- If no snapshot item is still actionable, the context is cleared and the user gets
  a concise no-action message; there is no automatic Mobile/menu redirect.
- Invalid/mismatched context fails closed and is cleared.
- A legacy task/attendance evidence list with an active 15-minute selection context
  has precedence over bare Payroll digits, so old numbered evidence flows do not
  get reinterpreted as `Lengkapi/Nanti`.
- An active durable attendance-resolution draft still wins before all reminder
  navigation, preserving the existing correction workflow.
- P09 does not create a correction draft, write proposed clocks, persist evidence,
  submit a request, send reminders, or alter the legacy monthly BAST reminder.

Validation evidence:

- P08->P09 branch compare contains only the routing/runtime/DM-entry source files
  and focused unit/regression tests listed above.
- Tests lock command parsing, stable snapshot ordering, skip-already-resolved
  behavior, wrong-owner/invalid-cycle fail-closed, no-action result, rejected prompt,
  direct start action, guarded numeric fallback, `Nanti`, and legacy digit precedence.
- The tool container still cannot resolve `github.com`, so repository checkout and
  full `pytest + ruff + basedpyright` cannot be executed here. No passing full-suite
  result is claimed. PR/main CI remains the complete quality gate.

## Next card

**P10 — Time-first correction draft**

Scope remains locked:

- After P09 selects one stable/current attendance key, accept the missing explicit
  clock fact before evidence is uploaded.
- Reuse the existing attendance-resolution authority; do not mutate raw attendance.
- Persist only a durable draft tied to the selected attendance identity and owner.
- Ask only the field that is actually missing. One missing Clock Out must not ask
  Clock In again; one missing Clock In must not ask Clock Out again.
- For both missing, accept explicit worked-day clock pair or the existing absence
  choices without fabricating values.
- Revalidate ownership/current source before saving each draft transition.
- Do not submit to PMO yet merely because a clock was entered. Evidence requirement
  and active-draft media attachment are completed in P11, then final review/submit
  loop lands in P13.
- Keep Talent Mobile outside the normal happy path.

For a new session: read the master implementation plan first, then this checkpoint,
verify branch HEAD, and continue P10 without redesigning locked requirements.
