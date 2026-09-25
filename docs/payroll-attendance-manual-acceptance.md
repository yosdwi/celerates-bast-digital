# Payroll Attendance — Manual Acceptance Checklist

Purpose: practical operator acceptance for the 21→20 Payroll attendance closing flow.
This is an operator/UAT checklist, not a replacement for automated tests.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`

## Preconditions

- [ ] Open the intended Payroll cycle and confirm the header shows the exact inclusive range. Example: **Payroll September 2026 = 21 Aug 2026–20 Sep 2026**.
- [ ] Confirm the operator is authenticated with the intended PMO/admin role.
- [ ] Confirm the closing policy state (`enabled` / `paused`) is intentional before any reminder test.
- [ ] Confirm the closing digest group JID is the configured/validated group, not a free-text or newly discovered group.
- [ ] Confirm the WhatsApp operational card shows factual bridge/session state before testing outbound behavior.
- [ ] Use a controlled Talent identity and test attendance rows. Do not alter production raw attendance to force a scenario.

## 1. Talent WhatsApp correction flow

### Missing Clock Out

- [ ] Prepare one current cycle attendance gap with Clock In present and Clock Out missing.
- [ ] Trigger/preview the Talent reminder.
- [ ] Confirm the reminder goes directly to the attendance task; it must not require `ketik menu` first.
- [ ] Reply using the deterministic option/numeric path and confirm it still works.
- [ ] Reply to a separate case with natural wording such as `kemarin pulang 17.40`.
- [ ] Confirm relative date resolution is anchored to the original WhatsApp message timestamp.
- [ ] Confirm the typed candidate matches an exact active gap before any mutation.
- [ ] Submit evidence when required.
- [ ] Confirm Talent wording says the information **has been submitted/stored**, not that Payroll is complete or approved.
- [ ] Confirm Payroll status becomes `WAITING_SUBMITTED` until PMO approval.

### Guardrails

- [ ] Send a date that is not an active attendance gap; confirm no attendance mutation occurs.
- [ ] Send a resolution type that does not match the gap; confirm no mutation occurs.
- [ ] For a `missing_both` case, send only one time; confirm the system does not guess the other time.
- [ ] Confirm evidence alone does not change a gap to `COMPLETE`.
- [ ] Confirm raw attendance timestamps remain unchanged throughout correction submission and approval.

## 2. PMO review queue

- [ ] Open Payroll Review Queue for the same selected cycle.
- [ ] Confirm the submitted item appears with Talent, work date, raw value, proposed value, evidence, and reviewability facts.
- [ ] Approve one current/reviewable item.
- [ ] Confirm every decision is revalidated against current source/projection immediately before mutation.
- [ ] Confirm approved correction feeds the existing effective attendance projection and the day becomes `COMPLETE` only when the projection is actually complete.
- [ ] Reject another item using the structured rejection path.
- [ ] Confirm the rejected item returns to `NEEDS_TALENT_ACTION` and becomes eligible for Talent follow-up again.
- [ ] For bulk approval, include at least one item that becomes stale before submit; confirm each item is evaluated independently and the result reports partial success/skip/failure truthfully.

## 3. Reminder automation

- [ ] Confirm default milestones are H-5, H-3, H-1 relative to closing day 20, and day 20 is the final assessment/digest.
- [ ] With policy disabled, run/evaluate the scheduler path and confirm no new reminder is dispatched.
- [ ] With policy enabled but paused, confirm no new campaign reminder is dispatched.
- [ ] Enable an intended test milestone and confirm only `NEEDS_TALENT_ACTION` recipients are considered.
- [ ] Confirm `WAITING_SUBMITTED` and `COMPLETE` are skipped.
- [ ] Confirm a successful logical milestone reminder is not sent a second time on the next scheduler evaluation.
- [ ] Confirm the delivery ledger reflects actual state (`RESERVED`, `SENDING`, `SENT`, `FAILED_RETRYABLE`, `FAILED_FINAL`, or `UNKNOWN`).

## 4. PMO closing digest

- [ ] Trigger/evaluate a closing milestone digest with the configured Payroll closing group.
- [ ] Confirm PMO receives one aggregate summary, not one WhatsApp message per Talent submission.
- [ ] Confirm counts are grounded in the selected Payroll cycle projection: complete, waiting review, needs Talent action, unverified/source facts, and reminder delivery facts.
- [ ] Confirm `UNRESPONDED` is counted only after a successful reminder delivery and no subsequent attendance response.
- [ ] Confirm technical source failure is not labeled as Talent failure/unresponsiveness.
- [ ] Force a group-send failure in a controlled test and confirm it is represented as a delivery fact rather than fabricated success.

## 5. Talent Follow-up

- [ ] Open Talent Follow-up on desktop and a narrow/mobile viewport.
- [ ] Confirm the follow-up list remains visible and actionable on mobile; it must not disappear with desktop tables.
- [ ] Preview a reminder and confirm long/multiline WhatsApp text wraps without horizontal overflow.
- [ ] For a normal actionable item, confirm manual send revalidates current eligibility immediately before dispatch.
- [ ] For a prior `UNKNOWN` delivery, confirm manual resend is blocked.
- [ ] For a retry still pending, confirm parallel/manual duplicate send is blocked.
- [ ] Confirm `WAITING_REVIEW` is presented as PMO work and does not offer a Talent reminder send.

## 6. WhatsApp recovery / failure handling

- [ ] Stop or make the bridge unavailable in a controlled environment; confirm Payroll read/review/export remain usable.
- [ ] Confirm outbound failure is recorded factually; do not mark the Talent as having received a reminder unless delivery succeeded.
- [ ] Exercise an ambiguous accepted-send outcome and confirm the durable result becomes `UNKNOWN`.
- [ ] Restart the gateway/runtime and confirm an `UNKNOWN` accepted request is **not** blindly resent.
- [ ] Restart after a known `SENT` request and confirm the durable receipt can be reused without a second WhatsApp send.
- [ ] Reuse a request ID with a different destination/payload and confirm it is rejected as a conflict.
- [ ] Confirm transient reconnect is bounded/serialized.
- [ ] Confirm logout/auth-revocation/operator-required states do not enter an automatic pairing loop.
- [ ] Confirm LocalAuth data at `/data/auth-whatsapp-web-js` is preserved during normal reconnect/recovery.

## 7. Payroll export and history

- [ ] Select a Payroll cycle and confirm the export panel shows the exact cycle label and date range before confirmation.
- [ ] Export Developer attendance using an authorized PMO/admin session.
- [ ] Confirm POST export rejects a missing/invalid CSRF token.
- [ ] Confirm the downloaded file comes from the existing legacy attendance exporter; do not accept changes to delimiter, column order, filename/date semantics, or approved-correction projection as part of Payroll export.
- [ ] Confirm the latest approved correction is reflected in export while raw attendance remains unchanged.
- [ ] If outstanding cases remain, confirm export is still allowed and the UI does not imply those cases are complete.
- [ ] Confirm export history shows metadata only: export id, cycle/range, actor, report/role, filename, result, factual row count, timestamp.
- [ ] Confirm no duplicate CSV blob is stored in Payroll export history.

## 8. Final operator sign-off

Record acceptance evidence:

- Payroll cycle tested:
- Environment:
- Operator:
- Talent test identity:
- Review approve/reject evidence:
- Reminder milestone tested:
- Digest destination tested:
- WhatsApp recovery scenario tested:
- Export filename / row count:
- Known deviations:
- Decision: `ACCEPT` / `ACCEPT WITH KNOWN LIMITATION` / `REJECT`

A manual `ACCEPT` does not override failed automated production gates in
`docs/payroll-attendance-production-gate.md`.
