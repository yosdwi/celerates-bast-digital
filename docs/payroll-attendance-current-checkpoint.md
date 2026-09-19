# Payroll Attendance — Current Execution Checkpoint

This is the rolling execution checkpoint for
`docs/payroll-attendance-implementation-plan.md`.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`  
Checkpoint date: 19 September 2026

## Completed through P11

P00–P10 remain completed as recorded in the master implementation plan and prior
checkpoint history. The latest completed card is P11 below.

### P11 — Evidence in active attendance draft

Status: `DONE`

Commits:

- `8607999c0df192acdf450e84b74803a17489b24c` — direct Payroll draft evidence helper.
- `1cf70edb7d039b65fda8e0fc9d06535d709711ed` — helper unit coverage.
- `029fcd5e4cebb6270782929ba7ea5e0ac692de33` — DM media routing integration.
- `7069a25b6c0ae66b2331022febe4d0d6b946799b` — DM routing regression tests.
- `6640aef3cc0b85c371fe51a29337ed86977bedb3` — lint-safe helper formatting.
- `206b68b3c86470ec157a4f5b405bf522fa24bdb8` — reminder expiry fixture correction.
- `6c59cf5052a3c7191f1019d7cfa38fcb77f48d93` — strict type-only import hardening.
- `3f1b39822b0e0d6481ab03d0bc4473889d4b8cef` — stale-source recovery cleanup.
- `a173841be91d8a7ce686eaae1cebbf09c4b5ca54` — stale-draft evidence regression coverage.

Files:

- `src/digital_bast/bot/payroll_attendance_evidence.py`
- `src/digital_bast/bot/dm_workflow.py`
- `tests/unit/bot/test_payroll_attendance_evidence.py`
- `tests/unit/bot/test_dm_workflow_payroll_evidence.py`

Delivered contract:

- Media sent while a valid Payroll attendance draft is active bypasses legacy
  candidate selection and binds directly to the draft's exact `attendance_key`.
- The currently bound WhatsApp identity is revalidated before any Payroll evidence
  mutation. A changed identity clears the stale draft and does not upload media.
- Existing `AttendanceEvidenceService.upload()` remains the storage authority;
  P11 does not add a second evidence table or storage path.
- A successful image upload refreshes the existing durable draft via
  `mark_evidence_ready()`; the P10 proposed Clock In/Clock Out/absence value is
  preserved and the reply shows `Bukti: ✓`.
- Duplicate media is treated truthfully as already stored and refreshes the same
  draft instead of creating a duplicate business action.
- Unsupported/too-large/not-owned/not-found media does not mark the draft evidence
  ready and does not claim success.
- If the evidence row is stored but attendance source state changes before the draft
  refresh, the evidence remains durable, only the stale draft is cleared, and the
  stable reminder context remains available for `lengkapi` recovery.
- P11 does not submit an attendance resolution request to PMO. Submission remains a
  separate explicit step planned for P13.
- Legacy evidence-first Task/Attendance flows still use `cli.bot_evidence()` when no
  active Payroll draft exists.
- P11 supports the existing image types (PNG/JPEG/WebP). PDF evidence is explicitly
  deferred to P12.

Validation evidence:

- P10→P11 branch compare contains only 19 changed lines in `dm_workflow.py`, one new
  Payroll evidence helper, and focused unit/regression tests.
- Tests cover exact-key attachment, proposed-clock preservation, duplicate media,
  unsupported media, stale-source cleanup, Payroll-vs-legacy routing, and identity
  mismatch fail-closed behavior.
- Full repository `pytest + ruff + basedpyright` is not claimed in this tool
  environment because the execution container still cannot resolve `github.com`
  for repository checkout/dependency execution. PR/main CI remains the complete
  quality gate.

## Next card

**P12 — PDF attendance evidence**

Scope remains locked:

- Extend the same `AttendanceEvidenceService` evidence contract to accept PDF in
  addition to PNG/JPEG/WebP; do not introduce a second evidence store.
- Enforce explicit PDF MIME/signature validation and the existing upload size guard.
- Store PDF content type/bytes/hash with the same ownership and duplicate checks.
- Active Payroll draft media routing from P11 must work unchanged for PDF documents.
- Existing image evidence behavior must remain unchanged.
- Do not perform OCR or infer attendance facts from PDF content.
- Do not submit the draft to PMO merely because evidence now exists; P13 owns the
  review/submit/next-gap loop.

For a new session: read the master implementation plan first, then this checkpoint,
verify branch HEAD, and continue P12 without redesigning locked requirements.
