# Payroll Attendance — Current Execution Checkpoint

This is the rolling execution checkpoint for
`docs/payroll-attendance-implementation-plan.md`.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`  
Checkpoint date: 19 September 2026

## Completed through P12

P00–P11 remain completed as recorded in the master implementation plan and prior
checkpoint history. The latest completed card is P12 below.

### P12 — PDF attendance evidence

Status: `DONE`

Commits:

- `b3ba566f1765bdd842a6d6d1418801275d5d4115` — attendance-only PDF signature support.
- `acfda2954f961ea71435ebf159c4f21cce8b797d` — Payroll evidence prompt/doc alignment.
- `d5b936dbb6e5f22072bc4677fb211774210a0810` — active-draft PDF flow regression update.
- `6dce3456c80a0e6a3aa3945a8a04b67bfb58f06a` — PDF signature/isolation tests.
- `35ba57a113c1cbb0c680b50a1174f96f37597de8` — size/type guard coverage.

Files:

- `src/digital_bast/bot/attendance_evidence.py`
- `src/digital_bast/bot/payroll_attendance_evidence.py`
- `tests/unit/bot/test_attendance_evidence_pdf.py`
- `tests/unit/bot/test_payroll_attendance_evidence.py`

Delivered contract:

- Attendance evidence now accepts PNG, JPEG, WebP and PDF.
- PDF detection is signature-based (`%PDF-`) rather than filename/caption based.
  A file named `.pdf` without a valid PDF signature is rejected.
- Valid PDF attendance evidence is stored through the same
  `AttendanceEvidenceService` path with `content_type = application/pdf`, the same
  SHA-256 duplicate handling, ownership checks and existing evidence table.
- The existing 5 MB evidence size guard remains in force and runs before database
  access.
- Shared Task & Evidence `sniff_content_type()` remains image-only; P12 does not
  silently enable PDF for task evidence.
- P11 active Payroll draft routing is unchanged: a PDF document binds to the exact
  active attendance key, refreshes `Bukti: ✓`, preserves the P10 proposed clock,
  and does not create a PMO request.
- No OCR, PDF parsing, clock inference or attendance fact extraction is introduced.
- No migration or second evidence storage path is added.

Validation evidence:

- P11→P12 branch compare is limited to the attendance evidence authority, Payroll
  evidence wording and focused tests; `dm_workflow.py` is unchanged in P12.
- Tests lock supported signatures, fake-PDF rejection, Task evidence isolation,
  existing size guard, Payroll PDF pass-through and unchanged unsupported-media
  behavior.
- Full repository `pytest + ruff + basedpyright` is not claimed in this tool
  environment; PR/main CI remains the complete quality gate.

## Next card

**P13 — Review / submit / next-gap loop**

Scope remains locked:

- A complete Payroll draft means the explicit proposed attendance fact is present
  and required evidence is present; this still is not a PMO request until Talent
  confirms submission.
- Render a concise review such as date, proposed Clock In/Out or absence, and
  `Bukti: ✓`, then expose only `Ajukan` and `Ubah` decisions (with text/numeric
  fallback where transport requires it).
- `Ajukan` must revalidate bound identity, exact attendance key/current source,
  evidence and proposal before calling the existing `AttendanceResolutionService`.
- Successful submit transitions the date to `WAITING_SUBMITTED`; never tell Talent
  it is payroll-ready or approved.
- Clear only the submitted durable draft, then re-read the stable P07 reminder
  snapshot/current projection and continue to the next still-actionable key.
- If another gap remains, prompt that gap directly; if none remains, return the
  concise done message and stop without opening Mobile/menu.
- `Ubah` keeps the same exact attendance identity and lets Talent replace the
  explicit proposed value; it must not create a second request.
- Existing legacy evidence-first correction submission behavior must remain intact.

For a new session: read the master implementation plan first, then this checkpoint,
verify branch HEAD, and continue P13 without redesigning locked requirements.
