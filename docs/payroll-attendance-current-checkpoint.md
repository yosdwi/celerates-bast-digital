# Payroll Attendance — Current Execution Checkpoint

This is the small rolling execution checkpoint for
`docs/payroll-attendance-implementation-plan.md`.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`  
Checkpoint date: 19 September 2026

## Completed through P10

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

### P10 — Time-first correction draft

Status: `DONE`

Commits:

- `839b858280671736b6f7875a0b840a879b13380e` — durable time-first draft state and proposal persistence.
- `9c29c556c6725ab432e36adcba59544092e8408b` — open the selected Payroll draft before evidence.
- `c5e85692e9f1127a2f87b6011bd881b88e25baca` — pure Payroll draft proposal/prompt helpers.
- `57ab89a04a9b6749e7cc6697feb691e1c0aa36d4` — store Payroll clock input without PMO submission.
- `26e9036f921598c86e44ab8f9255ed25b672eb45` — reminder-to-draft regression coverage.
- `3c98a63dbd033eb96c8259f280d642ac63ea12b5` — preserve legacy non-Payroll DM behavior.
- `a668e4e37d2e0ee2b08183a6f9526cb0af6e938e` — focused Payroll draft helper tests.
- `93d417db2f414fac08d72d04e1221dd6415da2a2` — end-to-end DM draft-state tests with PMO-submit guard.

Files:

- `src/digital_bast/bot/attendance_resolution_dm_state.py`
- `src/digital_bast/bot/dm_entry.py`
- `src/digital_bast/bot/dm_workflow.py`
- `src/digital_bast/bot/payroll_attendance_draft.py`
- `tests/unit/bot/test_dm_entry_payroll_reminder.py`
- `tests/unit/bot/test_dm_workflow.py`
- `tests/unit/bot/test_dm_workflow_payroll_draft.py`
- `tests/unit/bot/test_payroll_attendance_draft.py`

Delivered contract:

- P09 `Lengkapi` now opens a durable attendance-resolution draft for the exact
  revalidated attendance key before any evidence is uploaded.
- No new migration is required: P10 reuses the existing `bot_conversations`
  `pending_proposed_check_in`, `pending_proposed_check_out` and
  `pending_absence_type` columns introduced by the earlier attendance-resolution
  migration.
- A reply such as `17.40` on a missing Clock Out stores only the proposed Clock Out.
  Missing Clock In behaves symmetrically; a value already present in raw attendance
  is never fabricated or overwritten.
- For a day missing both punches, one clock value is not enough. The flow accepts
  an explicit Clock In + Clock Out pair or the existing explicit Cuti/Izin/Sakit
  classification.
- Every proposal write revalidates the conversation target, canonical owner,
  current raw source gap and absence of an already pending/approved request.
- Draft state carries work date, proposed clocks/absence and concrete evidence
  presence, while the raw attendance row remains immutable.
- Entering a clock value does **not** call `AttendanceResolutionService.submit()`
  and does not create a PMO request. The user sees truthful wording such as
  `informasi attendance sudah tersimpan`, not `Menunggu approval`.
- If no concrete attendance evidence row exists after the proposal is saved, the
  next prompt asks only for the screenshot/evidence for that selected date.
- If concrete evidence already exists, the bot does not ask for it again; the draft
  is still explicitly described as not yet submitted to PMO.
- `mark_evidence_ready()` preserves a time-first proposal when evidence later lands
  on the same attendance identity, while still supporting the legacy evidence-first
  path when no proposal draft existed.
- Legacy non-Payroll attendance-resolution DMs keep the previous evidence-first
  behavior and can still submit immediately through the existing resolution
  authority; P10 changes behavior only when the active draft belongs to a valid P07
  Payroll reminder context.
- Media arriving while the time-first Payroll draft is active is deliberately not
  persisted in P10. The response remains truthful and P11 owns active-draft media
  persistence rather than partially implementing it here.

Validation evidence:

- P09->P10 branch compare is limited to the four source files and four focused
  unit/regression test files listed above; no schema migration, scheduler, outbound,
  `AttendanceResolutionService`, raw attendance writer, or legacy reminder change is
  included.
- Focused tests lock exact-gap proposal selection, both-missing ambiguity, explicit
  absence, saved-clock wording, evidence/no-evidence branches, stale-source recovery,
  reminder start opening the draft, and the invariant that Payroll P10 must not call
  the PMO submit service merely because a clock was entered.
- Legacy DM tests are explicitly isolated from Payroll reminder context so the old
  evidence-first correction path remains regression-covered.
- The branch currently has no commit-status checks. A full repository
  `pytest + ruff + basedpyright` pass is not claimed from this connector-only
  environment; PR/main CI remains the complete quality gate.

## Next card

**P11 — Evidence in active attendance draft**

Scope remains locked:

- When media arrives while a Payroll time-first draft is active, persist it through
  the existing `AttendanceEvidenceService` against the exact selected attendance key
  and canonical Talent owner; do not re-run list selection or guess another date.
- Preserve the proposed clock/absence values already stored in the durable draft.
- Handle stored, duplicate, unsupported type, too-large, not-found and not-owned
  outcomes truthfully without losing the draft.
- After successful evidence persistence, refresh the same draft and show a concise
  summary with `Bukti: ✓`; still do not submit to PMO yet.
- Keep legacy task evidence and legacy attendance evidence flows unchanged.
- P11 supports the existing image formats only. PDF evidence remains the additive
  P12 card.

For a new session: read the master implementation plan first, then this checkpoint,
verify branch HEAD, and continue P11 without redesigning locked requirements.
