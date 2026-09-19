# Payroll Attendance — Current Execution Checkpoint

This is the rolling execution checkpoint for
`docs/payroll-attendance-implementation-plan.md`.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`  
Checkpoint date: 19 September 2026

## Completed through P14

P00–P13 remain completed as recorded in the master implementation plan and prior
checkpoint history. Phase C reminder/Talent correction flow is now completed through
P14.

### P14 — Progressive same-gap shortcut

Status: `DONE`

Key commits:

- `1e6d918af7fd29f64dfd698a069f184349f757c5` — derive a same-gap suggestion from the stable snapshot/current projection.
- `b3bc3a7e077ee36f0c29ec4d2e086bbaafd20a27` — `Sama / Berbeda` helper and revalidation flow.
- `6084d415286fd192be1db2cea71a4e75ebc87a3b` — offer the shortcut when continuing to an eligible next gap.
- `c849711a21c8093cf711d193b2c2a3b928cbd67a` — active Payroll draft reply integration.
- `4f3ceeb906d2a41c07290925e1d16ca9dd82c8f8` — routing/helper unit coverage.
- `ef2ec5ec654f5d3c4a4005153c97741c81de252a` — Talent entrypoint continuation regression coverage.
- `78bf814eaf3f9885eb3ebb89a431b0ae271b1300` — active-draft action precedence coverage.
- `d7eba950cbf23411567db3e793ccc62cc46c4760` — local strict-lint hardening.
- `0e7ec47cfd13e7bdf58bff5848c9a354b51a579a` — require truthful WAITING projection before reuse suggestion.
- `d30d407207c31ac33645c8d2103ef7aabae780df` — stale-source regression coverage.

Files:

- `src/digital_bast/bot/attendance_reminder_routing.py`
- `src/digital_bast/bot/payroll_attendance_repeat.py`
- `src/digital_bast/bot/dm_entry.py`
- `src/digital_bast/bot/dm_workflow.py`
- `tests/unit/bot/test_payroll_attendance_repeat.py`
- `tests/unit/bot/test_dm_entry_payroll_repeat.py`
- `tests/unit/bot/test_dm_workflow_payroll_repeat.py`

Delivered contract:

- P14 only offers the shortcut for a single missing Clock In or single missing Clock
  Out. Missing-both and absence cases remain explicit one-gap-at-a-time flows; the
  shortcut is deliberately not expanded into a bulk correction menu.
- A suggestion is derived only from an earlier key in the same immutable P07
  snapshot whose current projection is still `WAITING_SUBMITTED`, whose reason is
  `GAP_COVERED_BY_SUBMITTED_REQUEST`, whose request is still `pending`, and whose
  resolution type matches the current missing field.
- A stale pending request whose raw source has become complete cannot seed a
  `Sama` suggestion, even if its historical request row is still pending.
- After P13 `[Lanjut]`, an eligible next gap is opened as a normal durable draft but
  no proposed value is written yet. WhatsApp shows only `[Sama] [Berbeda]` with
  text/numeric fallback.
- `Sama` re-reads the current projection again before mutation. Only after the
  Talent explicitly chooses it is the prior explicit clock copied into the current
  draft. It does not copy evidence and does not submit a PMO request.
- The copied clock proceeds through the existing P10–P13 lifecycle: current
  attendance still needs its own evidence, review and explicit `Ajukan`.
- `Berbeda` performs no mutation and returns to the normal exact-gap clock question.
- If the suggestion disappears, the current key changes, or the source changes
  before `Sama` is processed, the shortcut fails closed/back to explicit input;
  no blind value copy occurs.
- Numeric fallback remains contextual: while the P14 draft has no proposal,
  `1/2` means `Sama/Berbeda`; once proposal + evidence are ready, P13 owns `1/2`
  again as `Ajukan/Ubah`.
- Raw client attendance is never mutated and stable snapshot ordering is preserved.

Validation evidence:

- P13→P14 branch compare is limited to seven Payroll reminder/draft source/test
  files plus this docs checkpoint; no migration, scheduler, outbound gateway, PMO
  review API/UI, or raw attendance write is introduced.
- Focused tests were added for same-gap eligibility, incompatible types, stale/raw
  source changes, action/text/numeric fallback, explicit `Sama` revalidation,
  `Berbeda` no-mutation behavior, continuation rendering and active-draft parser
  precedence.
- Full repository `pytest + ruff + basedpyright` is not claimed in this tool
  environment. Branch status checks remain separate; PR/main CI is still the full
  quality gate.

## Next card

**P15 — Review queue API**

Scope remains locked:

- Expose pending attendance-resolution requests for Payroll through a dedicated,
  read-only PMO review queue API.
- Reuse the existing `AttendanceResolutionService` / correction lifecycle as the
  authority. Do not create a second review/approval store.
- Return enough factual context for PMO review: Talent identity, work date,
  resolution type, raw vs proposed values, evidence metadata, submitted time and
  current-source validity/reviewability.
- Group/filter facts may be prepared for the web, but P15 does not approve/reject
  anything; mutation remains P17/P18.
- Preserve Payroll 21–20 cycle semantics and existing PMO/admin authorization.

For a new session: read the master implementation plan first, then this checkpoint,
verify branch HEAD, and continue P15 without redesigning locked requirements.
