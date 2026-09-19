# Payroll Attendance — Current Execution Checkpoint

This is the rolling execution checkpoint for
`docs/payroll-attendance-implementation-plan.md`.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`  
Checkpoint date: 19 September 2026

## Completed through P13

P00–P12 remain completed as recorded in the master implementation plan and prior
checkpoint history. The latest completed card is P13 below.

### P13 — Review / submit / next-gap loop

Status: `DONE`

Key commits:

- `a77e6e75ae7684e65eb92ae2ccda2a150745b9fe` — explicit Payroll draft review actions.
- `687a59f826dbc0f6b0b908d465cf5287f5589dac` — submit/continuation orchestration foundation.
- `10baaa3da604216813936212c8d23b143bef4e9b` — strict protocol/type hardening.
- `77c529957952b27421b5f1e18ea981a6f04502ba` — submit-loop unit coverage foundation.
- `7631d8955bfa399182220e797594b922d363aacb` — active Payroll draft DM integration.
- `5cbe839b7d1f211887e45d2007de3293543be3db` — review action routing tests.
- `9bea842a3a2c7e87691e775d69c50d6fa97efde8` — truthful source-change completion wording.
- `2e3e422b83d7fd949d5028959727d7df851ab03d` — canonical `[Lanjut] [Selesai dulu]` continuation choice.
- `bdf0ad2835b76a7cfff90b6acc4fbc99bf73b879` — `lanjut/selesai dulu` text fallbacks.
- `f6a6b9287792cad2c98a0cb1ea038bb2534e30ee` — context-safe stop wording in Talent entrypoint.
- `eb01e867b06b45b228ed5658273e0b06a20905da` — continuation helper style hardening.
- `5a2b8ae05287d8ed994648f28f19cac3b30036d9` — continue/stop submit tests aligned with canonical flow.
- `6da2d2f80fc469fc1013700974364fa9a3f1c8be` — reminder parser continuation regression coverage.
- `6975b293ede7f10a8eec4ddd3f757d746fa6e924` — DM continuation/stop regression coverage.

Additional corrective/regression commits inside the same P13 card:

- `9979e2aebc87ec6c9fa30425e14d32352891a744`
- `a110fca0d17c2278aa087f83ebdbf3d32169c7e2`
- `5d782defc91d1fc50db9a17336c7f6ce1c2b6105`
- `8908719e27eaef4c93556039f08cc11f2d8c6b64`
- `0a482e7523bcc3195ff7a3daff3fb6ee45e4b0f0`
- `46ef198594606aae715e12ce0f2de48b84bec271`

Files:

- `src/digital_bast/bot/payroll_attendance_draft.py`
- `src/digital_bast/bot/payroll_attendance_submit.py`
- `src/digital_bast/bot/dm_workflow.py`
- `src/digital_bast/bot/attendance_reminder_routing.py`
- `src/digital_bast/bot/dm_entry.py`
- `tests/unit/bot/test_payroll_attendance_submit.py`
- `tests/unit/bot/test_dm_workflow_payroll_submit.py`
- `tests/unit/bot/test_payroll_attendance_draft.py`
- `tests/unit/bot/test_payroll_attendance_evidence.py`
- `tests/unit/bot/test_dm_workflow_payroll_draft.py`
- `tests/unit/bot/test_attendance_reminder_routing.py`
- `tests/unit/bot/test_dm_entry_payroll_reminder.py`

Delivered contract:

- A Payroll draft only becomes reviewable when both an explicit proposal and
  evidence exist. Evidence alone never submits or completes a correction.
- Review displays the exact durable proposal plus `Bukti: ✓` and only two
  decisions: `Ajukan` and `Ubah`. Stable action IDs plus `1/2` and text fallback
  remain available for WhatsApp transports without buttons.
- `Ubah` re-opens the same exact attendance key, revalidates current source state,
  clears/replaces only proposed correction values and keeps already stored evidence.
- `Ajukan` uses the existing `AttendanceResolutionService.submit()` authority and
  passes values stored in the durable draft; submit text is never reparsed into
  attendance facts.
- Successful creation is reported only as `sudah diajukan` / `menunggu review PMO`.
  It is never described as approved or payroll-ready.
- `ALREADY_OPEN` is treated idempotently as an already submitted request; it does
  not create another business action.
- `EVIDENCE_REQUIRED` leaves the draft open and asks for evidence again.
- Source change before submit clears the stale draft and never claims a request was
  created. Ownership mismatch clears draft + reminder context and fails closed.
- After a successful submit, the P07 snapshot is re-read through P09 current
  projection routing. The submitted/pending date naturally leaves the actionable
  set; no snapshot index is manually popped or renumbered.
- If more Talent action exists, the user gets exactly `[Lanjut] [Selesai dulu]`.
  The submit handler does not auto-open the next gap.
- `Lanjut` (or the existing start action ID / guarded numeric fallback) revalidates
  context/projection again in `dm_entry` and only then opens the next still-actionable
  gap.
- `Selesai dulu` performs no additional attendance mutation, does not open Mobile or
  menu, and leaves the stable reminder context available until normal expiry.
- If no Talent action remains, the reminder context is cleared and the reply says
  there is no additional Talent action while already submitted requests remain
  pending PMO review.
- Legacy non-Payroll attendance-resolution drafts still use their existing
  evidence-first submission behavior.

Validation evidence:

- P12→P13 branch compare is limited to Payroll draft/submit/reminder DM routing and
  focused unit/regression tests; no scheduler, outbound gateway, PMO review API/UI,
  raw attendance mutation or migration is included.
- Focused tests lock review rendering, action IDs/text/numeric fallback, durable
  proposal submission, explicit continue/stop choice, final-gap completion,
  truthful source-change behavior, evidence-required recovery, same-key edit,
  DM action precedence, `lanjut`, `selesai dulu`, stable-context retention and
  legacy digit precedence.
- Full repository `pytest + ruff + basedpyright` is not claimed in this tool
  environment because repository-local execution remains unavailable here. Branch
  status checks are verified separately; PR/main CI remains the complete quality
  gate.

## Next card

**P14 — Progressive same-gap shortcut**

Scope remains locked:

- Only offer a progressive shortcut when multiple still-actionable snapshot dates
  share the same missing attendance field/type.
- Ask a small `Sama / Berbeda` decision after one explicit value has been captured;
  do not show a large bulk mapping/menu or silently copy values.
- `Sama` may prefill the same explicit clock/absence fact only for compatible gaps,
  but each exact attendance identity must still retain its own evidence requirement
  and its own explicit submit/review lifecycle.
- `Berbeda` keeps the normal one-gap-at-a-time P09–P13 flow.
- Revalidate every target against current source/projection before any draft value is
  persisted. Skip dates that became waiting/complete/unverified.
- Preserve stable P07 ordering and never change the immutable source attendance.

For a new session: read the master implementation plan first, then this checkpoint,
verify branch HEAD, and continue P14 without redesigning locked requirements.
