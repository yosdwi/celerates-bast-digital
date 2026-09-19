# Payroll Attendance — Current Execution Checkpoint

This is the rolling execution checkpoint for
`docs/payroll-attendance-implementation-plan.md`.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`  
Checkpoint date: 19 September 2026

## Execution standard

This project follows `docs/development-execution-standard.md`.

Key rule: **cards remain audit/commit boundaries, but execution and conversation
progress happen by end-to-end waves.** Do not pause after each card unless a
material product/architecture/data-integrity conflict makes safe continuation
ambiguous. Keep small/revertible commits and focused tests inside the wave, then
perform one integration review and one rolling checkpoint at the wave boundary.

Project-specific business/source-of-truth rules in the Payroll implementation plan
remain authoritative over the generic execution standard.

## Completed through P18

P00–P13 remain completed as recorded in the master implementation plan and prior
checkpoint history. P14 completed the Talent-side progressive same-gap shortcut.
The PMO Review Operations wave P15–P18 is now implemented and checkpointed.

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
- `d30d407207c31ac33645c8d2103ef7aabae780df` — stale-source regression coverage and P14 baseline for the next wave.

Delivered contract remains unchanged from the P14 checkpoint: only compatible
single Clock In / Clock Out gaps can offer `Sama`; current projection is re-read
before reuse; no evidence is copied; raw attendance remains immutable; and the
normal evidence/review/`Ajukan` lifecycle still applies.

## Wave 3 — PMO Review Operations (P15–P18)

Status: `DONE`

Baseline before this wave:

- `d30d407207c31ac33645c8d2103ef7aabae780df`

### P15 — Review queue API

Delivered:

- Added a dedicated Payroll review projection over existing pending
  `attendance_resolution_requests`; no second approval/review store was created.
- Added `GET /api/talentops/v1/payroll/review-queue` using the existing Payroll
  21–20 cycle selector and existing owner/admin/PMO authorization model.
- Queue facts include Talent identity, work date, resolution type, current raw
  clocks, proposed clocks/absence, evidence identity + metadata, submitted time,
  and current reviewability.
- Pending rows that became stale remain visible as operational exceptions but are
  returned with `reviewable=false` and an explicit reason such as
  `source_changed`, `request_not_current`, `source_unavailable`, or
  `evidence_not_found`.
- Evidence list reads metadata only. The existing attendance-resolution evidence
  endpoint remains the binary/content authority and is opened on demand from the
  PMO detail surface.

### P16 — Review queue UI

Delivered:

- Added `PayrollReviewQueuePanel` to the existing Payroll workspace instead of
  creating a second PMO application.
- Queue is grouped by missing Clock Out, missing Clock In, missing both, and
  absence.
- Reviewable rows can be selected individually or with a reviewable-only
  select-all action. Stale rows remain visible but disabled.
- Detail inspection shows actual vs proposed facts, submitted timestamp, evidence
  metadata/caption and a link to the existing evidence binary endpoint.
- Desktop and mobile/responsive presentation are isolated in
  `frontend/src/styles/payroll-review.css` so the earlier Payroll summary/detail
  behavior remains intact.

### P17 — Bulk approve service/API

Delivered:

- Added `POST /api/talentops/v1/payroll/review-queue/decide` with CSRF validation.
- Existing `AttendanceResolutionService.decide()` remains the only mutation
  authority; raw `attendance` is never updated by this flow.
- Request IDs are deduplicated and capped at 100 items per call.
- Every selected item is checked against the current queue/projection and then the
  existing decision authority revalidates the current raw row under lock before
  approval.
- One stale, already-resolved, source-changed or missing item does not fail other
  items. API returns explicit per-item `succeeded`, `skipped`, or `failed` results
  plus aggregate counts.

### P18 — Bulk UI + rejection reasons

Delivered:

- PMO can approve or reject selected reviewable requests from the Payroll page.
- Reject requires a reason; UI provides common structured reasons plus a custom
  reason path.
- Confirmation explicitly tells the operator that every item is revalidated and
  stale items can be skipped independently.
- Result feedback is partial-success aware rather than a single optimistic success
  toast.
- After a decision the UI re-fetches both Review Queue and Payroll overview from
  the backend, so the screen reflects effective authoritative state rather than a
  locally invented status.
- Reject uses the same existing correction lifecycle; the rejected projection can
  therefore return to the Talent action flow without introducing another state
  machine.

### Main implementation files

Backend:

- `src/digital_bast/application/payroll_review.py`
- `src/digital_bast/application/attendance_review.py`
- `src/digital_bast/web/payroll_contracts.py`
- `src/digital_bast/web/payroll_router.py`
- `tests/unit/application/test_payroll_review.py`
- `tests/unit/web/test_payroll_review_routes.py`

Frontend:

- `frontend/src/api/payroll.ts`
- `frontend/src/api/payroll.test.ts`
- `frontend/src/pages/PayrollReviewQueuePanel.tsx`
- `frontend/src/pages/PayrollReviewQueuePanel.test.tsx`
- `frontend/src/pages/PayrollPage.tsx`
- `frontend/src/pages/PayrollPage.test.tsx`
- `frontend/src/styles/payroll-review.css`
- `frontend/src/main.tsx`

### Focused hardening commits near wave close

- `9f3473c3bab2da0e33aaa7665b7f034bb49148c4` — factual compact actual/proposed display and existing evidence link.
- `53a6e089bb1ef45ffe0faf96174461716020e62d` — isolate existing Payroll page tests from new queue side effects.
- `59868d89404b6814a51f857d298ccb6c4e475ef9` — component coverage for stale selection, evidence, approve and reject interactions.
- `d531ace9d443638370193565d0812f20bce2e645` — wave-local Payroll review lint hardening.
- `08572864cde7aa63298e22cfaf4c4bc013705985` — Payroll review contract import/lint hardening.
- `a332686e1d3ba2c7a049e579222beb4f14be9d7f` — application test import/lint hardening.
- `a11c1cea43c8f236a18159efac7ebe3f426e1210` and `c782f252850a5e1d0fa9ff6d306a50dbaaaa7845` — route-test lint/security-test annotation hardening.

### Integration / regression audit

P14 baseline `d30d407...` → pre-checkpoint P18 head `c782f252...` is 27 commits
ahead and the file-level compare is limited to the Payroll review backend/frontend/tests
plus the rolling execution/development-standard docs. The wave does **not** add a
new migration, raw-attendance writer, CSV contract, BAST behavior, scheduler,
WhatsApp transport or separate approval database.

Validation truth from GitHub Actions validation PR #73:

- `uv run python -m compileall -q src tests`: **PASS**.
- `migration-smoke`: **PASS**, including migration gate, migration idempotency and
  smoke/shadow gate.
- `gitleaks`: **PASS**.
- Latest repository-wide Ruff gate: **FAIL** with 109 existing branch lint findings.
  After wave hardening, no P15–P18-specific Python file appears in that failure
  list. Remaining findings are in earlier Payroll cards and unrelated legacy/
  BAST/infrastructure code.
- Because repository-wide Ruff fails first, that CI job does not reach
  `basedpyright`, `pytest`, or `scripts/check-ops.sh`. A full green quality job is
  therefore **not claimed** for this wave.
- Focused backend and frontend regression tests were added, but frontend tests are
  not executed by the current repository CI workflow. This tool runtime also could
  not clone GitHub for a local npm run because outbound GitHub DNS was unavailable.
  Their presence is recorded; execution is not falsely claimed.
- The container job currently fails during runner setup while resolving
  `aquasecurity/trivy-action@0.30.0`, before checkout/build; this is separate from
  the P15–P18 application code.

PR #73 was created only to trigger repository CI. It is **not a release/merge
candidate**: this long-lived working branch contains more than 150 accumulated
commits and 353 changed files relative to current `main`. Close the draft PR after
validation; do not merge it as the delivery path.

Repository hygiene note: an accidental temporary branch named `tmp-invalid` was
created during CI-trigger experimentation. No code path depends on it; delete that
ref through normal GitHub branch cleanup when convenient. Do not use it for future
work.

## Next execution wave — Contacts & WhatsApp Mapping (P19–P22)

**Cards P19–P22 should be executed continuously as one wave.** Keep the existing
WhatsApp Web transport and current identity/source-of-truth contracts; do not turn
this into a transport migration.

### P19 — Group/member discovery

- Read current WhatsApp group/member information through the existing active
  `whatsapp-web-session` transport boundary.
- Define a truthful discovery result that can distinguish groups, participants,
  JIDs and availability/errors without fabricating contact identity.

### P20 — Identity/mapping API

- Map discovered WhatsApp identities to existing Talent/employee identities using
  explicit durable mapping rules.
- Keep ambiguous/unmapped identities visible as operational exceptions; never infer
  an employee binding from display name alone.

### P21 — Contacts & WhatsApp UI

- Provide a PMO/admin web surface to inspect existing groups/contacts and current
  Talent bindings, then explicitly bind/unbind where authorized.
- Optimize for operational clarity rather than a generic address-book product.

### P22 — Allowed closing group

- Persist/select the authorized Payroll closing group used by later PMO digest and
  operational notification cards.
- Group choice is configuration/identity context only; it must not change Payroll
  closing truth or attendance approval state.

### Wave acceptance

The P19–P22 wave is done when an authorized operator can:

```text
Existing WhatsApp session
  -> discover real group + participant identities
  -> inspect mapped / unmapped Talent identities
  -> explicitly correct bindings
  -> select the allowed Payroll closing group

without changing the active WA transport or inventing identity from names.
```

For a new session: read `docs/development-execution-standard.md`, then the master
Payroll implementation plan and this checkpoint, verify branch HEAD, and execute the
full P19–P22 wave without redesigning locked requirements.
