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

## Completed through P30

P00–P14 delivered the canonical 21–20 Payroll cycle/projection, Talent Payroll
workspace, stable reminder context, deterministic WhatsApp correction flow,
evidence/PDF handling, explicit submit/review wording, and progressive same-gap
shortcut without mutating raw attendance.

P15–P18 delivered the PMO Payroll review queue, evidence inspection, per-item
revalidation, bulk approve/reject with partial success, and rejection back into
the existing Talent correction lifecycle.

P19–P22 delivered Contacts & WhatsApp Mapping:

- real group/member discovery through the active `whatsapp-web-session` runtime,
- Talent↔WhatsApp mapping using existing `wa_identity`,
- Contacts & WhatsApp operational UI,
- one stable configured Payroll closing-group JID,
- no provider migration, fuzzy identity inference, or arbitrary group outbound.

P23–P27 delivered Reminder Automation Foundations:

- independent Payroll closing policy/settings,
- typed preview/control UI,
- durable logical Talent reminder delivery lifecycle,
- existing-Prefect scheduled Payroll reminder cutover,
- attendance-action-only response correlation,
- no generic conversation timestamp used as response evidence.

---

## Wave 6 — PMO Closing Digest & Follow-up (P28–P30)

Status: `DONE`

Baseline before this wave:

- `81809b7e9cf352ee8977e9fa80a092d74a57383b`

Pre-checkpoint implementation head:

- `5aff66c6d11a11b1b9ae6e07bdf2ff3e37638fdf`

Comparison from the P27 checkpoint baseline to the P30 pre-checkpoint head:

- 35 commits ahead,
- 0 commits behind,
- 22 changed files,
- scope limited to Payroll digest projection, configured-group digest delivery,
  PMO follow-up API/UI, additive group-delivery persistence, existing reminder
  delivery reads/manual send, WhatsApp outbound bridge boundaries, runtime wiring,
  and focused tests.

No raw attendance authority, legacy attendance CSV contract, BAST monthly/calendar
semantics, or active WhatsApp provider was replaced by this wave.

### P28 — Closing digest projection

Status: `DONE`

Delivered:

- Added `PayrollDigestService` as a read-side projection over the canonical Payroll
  Closing Projection plus durable P25/P27 reminder delivery facts.
- Kept the locked three primary Payroll business statuses unchanged. Delivery,
  technical-unverified and response facts remain operational dimensions only.
- Follow-up reasons include:
  - delivery `UNKNOWN`,
  - retryable delivery failure,
  - final delivery failure,
  - genuinely `UNRESPONDED`,
  - current actionable Talent never successfully reminded,
  - submitted/waiting review,
  - technical source-unverified.
- `UNRESPONDED` requires all of the following:
  - Talent is still currently actionable,
  - at least one successful `SENT` Payroll reminder exists,
  - the latest relevant successful reminder has no correlated attendance response.
- Generic chat activity does not contribute to the unresponded calculation.
- Digest summary exposes current cycle business counts plus actual successful send,
  unresponded, not-reminded, failed and `UNKNOWN` delivery dimensions.

Primary files:

- `src/digital_bast/application/payroll_digest.py`
- `src/digital_bast/application/payroll_reminder_delivery.py`
- `src/digital_bast/infrastructure/payroll_reminder_delivery.py`
- `tests/unit/application/test_payroll_digest.py`

### P29 — Configured group digest outbound

Status: `DONE`

Delivered:

- Added additive migration
  `20260920_0026_payroll_group_digest_delivery.py`.
- Group digest delivery has its own durable destination ledger; it does not create
  synthetic Talent or operator rows in `talentops_followups`.
- Uses the single configured P22 Payroll closing-group JID.
- Sends one PMO digest per scope/cycle/milestone using stable logical idempotency.
- Uses H-N closing milestones plus `FINAL` on the cycle end date.
- Group digest contains aggregate closing/reminder/review workload. It does not send
  one PMO WhatsApp message per Talent correction submission.
- Delivery lifecycle preserves the same conservative semantics used by Talent
  reminders:
  - `RESERVED`,
  - `SENDING`,
  - `SENT`,
  - `FAILED_RETRYABLE`,
  - `FAILED_FINAL`,
  - `UNKNOWN`.
- A pre-existing `SENDING` delivery found after interruption is converted to
  `UNKNOWN` and is not blindly resent.
- Direct-message bridge contract remains restricted to direct JIDs. Group outbound
  uses a dedicated authenticated `/group-messages` boundary accepting only `@g.us`.
- Bridge request IDs are deterministic bounded SHA-256 identifiers while the
  readable logical idempotency key remains durable in the database.
- Existing WhatsApp runtime remains `whatsapp-web-session` / `whatsapp-web.js`.

Primary files:

- `migrations/versions/20260920_0026_payroll_group_digest_delivery.py`
- `src/digital_bast/application/payroll_group_digest.py`
- `src/digital_bast/infrastructure/payroll_group_digest.py`
- `src/digital_bast/infrastructure/whatsapp_outbound.py`
- `src/digital_bast/payroll_runtime.py`
- `src/digital_bast/flows/notifications.py`
- `whatsapp-web-session/server.js`
- `tests/unit/application/test_payroll_group_digest.py`
- `tests/unit/infrastructure/test_whatsapp_outbound.py`

### P30 — Payroll Follow-up panel live actions

Status: `DONE`

Delivered:

- Added PMO-facing Payroll digest/follow-up API and compact web panel.
- PMO can distinguish:
  - current Talent attendance action required,
  - submitted/waiting review,
  - source-unverified technical cases,
  - reminder delivery retry/final failures,
  - `UNKNOWN` delivery,
  - successfully reminded but genuinely unresponded Talent.
- Added reminder preview using current canonical cycle/policy/projection.
- Added explicit manual reminder action with CSRF + PMO/admin authorization.
- Manual send re-reads current Payroll projection at action time; an old preview
  cannot send to a Talent that has since become WAITING/COMPLETE/non-actionable.
- Manual send is fail-closed for ambiguous/in-progress delivery states:
  - `UNKNOWN` -> blocked,
  - `RESERVED` / `SENDING` -> blocked as in progress,
  - `FAILED_RETRYABLE` -> blocked while durable retry remains pending.
- Request UUID is preserved as logical manual-action identity and converted to a
  bounded deterministic bridge request ID for transport.
- No second PMO task/workflow system was introduced.

Primary files:

- `src/digital_bast/application/payroll_reminders.py`
- `src/digital_bast/web/payroll_contracts.py`
- `src/digital_bast/web/payroll_followup_router.py`
- `src/digital_bast/web/app.py`
- `frontend/src/api/payroll.ts`
- `frontend/src/pages/PayrollFollowUpPanel.tsx`
- `frontend/src/pages/PayrollPage.tsx`
- `tests/unit/web/test_payroll_followup_routes.py`

### Validation truth

Validation PR #73 CI run `#514` / `35477238998` on pre-checkpoint head
`5aff66c6d11a11b1b9ae6e07bdf2ff3e37638fdf`:

- `gitleaks`: **PASS**.
- `uv sync --all-groups`: **PASS**.
- `uv run python -m compileall -q src tests`: **PASS**.
- `migration-smoke`: **PASS**.
  - container initialization: PASS,
  - migration gate: PASS,
  - migration idempotency gate: PASS,
  - smoke/shadow gate: PASS.
- repository-wide `uv run ruff check .`: **FAIL** with 108 findings.
- Before P28–P30 lint cleanup, the same validation branch reported 147 findings.
  After the focused cleanup, **none of the P28–P30 changed files appears in the
  current Ruff failure list**. The remaining 108 findings are pre-existing branch
  debt from earlier Payroll cards and unrelated legacy/BAST/infrastructure code.
- Because repository-wide Ruff fails first, the quality job does **not** reach
  `basedpyright`, full `pytest`, or `scripts/check-ops.sh`; a full green quality job
  is therefore not claimed.
- The container job still fails during job setup before checkout/build due to the
  external `aquasecurity/trivy-action@0.30.0` resolution problem. It does not
  execute or invalidate P28–P30 application code.
- Frontend behavior is implemented, but this repository CI does not run a frontend
  npm test/typecheck suite; a frontend green suite is not claimed.

PR #73 is used only as a CI validation trigger for the long-lived working branch.
It is **not** a merge/release candidate and must not be merged into `main`.

### Wave acceptance result

The current closing operations flow is now:

```text
21–20 Payroll Closing Projection
  -> durable Talent reminder receipts + correlated attendance responses
  -> PMO Closing Digest projection
  -> configured group aggregate digest at closing milestones/final
  -> Payroll Follow-up panel
       -> current reason / delivery fact
       -> preview current reminder
       -> explicit safe manual reminder
       -> revalidate actionability before send
```

while preserving raw attendance immutability, existing correction approval truth,
legacy CSV behavior, direct/group destination boundaries, and conservative
`UNKNOWN` delivery handling.

---

## Next execution wave — WhatsApp Operational Reliability (P31–P35)

Execute P31–P35 continuously as one integration wave unless an implementation
finding creates a genuine auth/session ownership conflict.

### P31 — Durable gateway request receipt

Status: `TODO`

Add bounded durable request/receipt persistence around the active WhatsApp gateway
so an accepted request can be reconciled after gateway/process recovery. Preserve
strict request-id conflict handling and do not claim exactly-once delivery.

### P32 — Session supervisor core

Status: `TODO`

Add readiness probing and a conservative transient-recovery ladder with durable
budget/cooldown. Routine recovery must not log out, reset or destroy LocalAuth.

### P33 — Single-owner/auth safety

Status: `TODO`

Enforce one active session owner before any Chromium Singleton cleanup. Add
filesystem/disk/inode/auth-store safety checks so recovery cannot casually corrupt
or erase the WhatsApp auth authority.

### P34 — Extended WhatsApp status API

Status: `TODO`

Expose alive vs messaging-ready plus recovery state/reason, last probe/ack,
operator-action-required state and applied recovery policy/version through the
existing authenticated operational contract.

### P35 — Payroll WhatsApp operations UI

Status: `TODO`

Add a compact operational surface using understandable states such as
`Terhubung / Sedang pulih / Perlu tindakan`, with safe pause/resume/reconnect
controls and admin-only pairing only when genuinely required.

### Continuation instructions

For a new session:

1. Read `docs/development-execution-standard.md`.
2. Read `docs/payroll-attendance-implementation-plan.md`.
3. Read this rolling checkpoint.
4. Verify branch HEAD and inspect any commits after this checkpoint before editing.
5. Continue with P31–P35 without replacing `whatsapp-web.js`/LocalAuth, weakening
   direct/group destination validation, or introducing destructive routine auth
   reset behavior.
