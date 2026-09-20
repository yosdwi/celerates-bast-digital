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

## Completed through P35

P00–P14 delivered the canonical 21–20 Payroll cycle/projection, Talent Payroll
workspace, stable reminder context, deterministic WhatsApp correction flow,
evidence/PDF handling, explicit submit/review wording, next-gap continuation, and
progressive same-gap shortcut without mutating raw attendance.

P15–P18 delivered the PMO Payroll review queue, evidence inspection, per-item
revalidation, bulk approve/reject with truthful partial success, and rejection back
into the existing Talent correction lifecycle.

P19–P22 delivered Contacts & WhatsApp Mapping using the active
`whatsapp-web-session` / `whatsapp-web.js` runtime, canonical identity bindings,
group/member discovery, mapping UI, and one configured Payroll closing-group JID.

P23–P27 delivered independent Payroll closing settings, durable logical reminder
delivery, scheduled reminder cutover through existing Prefect cadence, and
attendance-action-only response correlation.

P28–P30 delivered the PMO Closing Digest projection, one aggregate configured-group
digest per closing milestone/final, and live Payroll Follow-up actions with preview,
manual send, current-projection revalidation, and conservative delivery handling.

---

## Wave 7 — WhatsApp Operational Reliability (P31–P35)

Status: `DONE`

Baseline before this wave:

- P30 checkpoint: `ffe849c…`

Validated implementation head before this checkpoint:

- `d559e9fb10cf11deb6c55f40be3d5b833a6e3472`

The wave is additive around the existing WhatsApp transport. It does not replace
`whatsapp-web.js`, LocalAuth, Payroll business truth, raw attendance authority,
legacy CSV, the approval lifecycle, or the existing direct/group destination
boundaries.

### P31 — Durable gateway request receipt

Status: `DONE`

Delivered:

- Added bounded durable gateway receipt persistence in
  `whatsapp-web-session/gateway-receipts.js` using the existing persistent `/data`
  volume. No new database, queue, service or message bus was introduced.
- Durable receipt data stores request identity, payload fingerprint and delivery
  outcome. It does not persist the full chat body as a new conversation store.
- Strict request-id conflict remains enforced: the same request id with a different
  destination/message fingerprint is rejected.
- A logical request is durably marked `accepted` before invoking WhatsApp send.
- On process restart, any persisted `accepted` request is reconciled to durable
  `unknown` rather than being sent again blindly.
- A sent receipt survives restart and can be replayed to the caller without a
  second WhatsApp send.
- Ambiguous post-acceptance failures become `delivery_outcome_unknown`.
- Concurrent accepted requests are persisted together so one in-flight request
  cannot overwrite another during crash reconciliation.
- Retention is bounded; the default receipt cap is 2048 records.
- Python outbound preserves the gateway error code instead of flattening all 503s
  to generic `whatsapp_not_connected`.
- Talent reminder and PMO group-digest state machines promote
  `delivery_outcome_unknown` to durable `PayrollDeliveryState.UNKNOWN` and do not
  reclassify it as retryable.
- A focused scheduled-Talent test verifies first ambiguous send -> `UNKNOWN`, next
  scheduler evaluation -> still `UNKNOWN`, and no second outbound invocation.

Primary files:

- `whatsapp-web-session/gateway-receipts.js`
- `whatsapp-web-session/gateway-receipts.test.js`
- `whatsapp-web-session/server.js`
- `src/digital_bast/infrastructure/whatsapp_outbound.py`
- `src/digital_bast/application/payroll_reminders.py`
- `src/digital_bast/application/payroll_group_digest.py`
- `tests/unit/application/test_payroll_reminders_gateway_unknown.py`
- `tests/unit/application/test_payroll_group_digest.py`

Important boundary:

This is conservative at-most-no-blind-resend handling, not a claim of provider-level
exactly-once delivery. An ambiguous accepted request is surfaced as `UNKNOWN` for
operator/reconciliation handling.

### P32 — Session supervisor core

Status: `DONE`

Delivered:

- Added `whatsapp-web-session/session-supervisor.js`.
- Supervisor distinguishes messaging readiness from process liveness.
- Automatic recovery applies only to transient `disconnected` / `failed` states.
- Recovery includes a grace period, durable attempt history, bounded attempt budget,
  recovery window and cooldown.
- Supervisor state survives gateway process restart.
- Operator controls support pause, resume and explicit reconnect.
- Explicit reconnect acknowledges quickly while the actual recovery remains
  serialized in the supervisor; HTTP callers do not wait for a full Chromium /
  WhatsApp reconnection cycle.
- A single recovery attempt is allowed in flight.
- Permanent `LOGOUT`, auth failure or an existing operator-action latch is never
  auto-repaired through a pairing loop.
- `Bridge.restartTransient()` may destroy/reinitialize the transient client runtime,
  but does not call `logout()` and does not delete/reset LocalAuth.

Primary files:

- `whatsapp-web-session/session-supervisor.js`
- `whatsapp-web-session/session-supervisor.test.js`
- `whatsapp-web-session/bridge.js`
- `whatsapp-web-session/server.js`

### P33 — Single-owner/auth safety

Status: `DONE`

Delivered:

- Added `whatsapp-web-session/session-safety.js`.
- Active runtime must acquire an explicit owner lease in shared `/data` before
  touching Chromium singleton lock files or starting recovery-sensitive work.
- Owner state includes a heartbeat and stale-owner takeover rules.
- Storage/auth safety checks cover writable state, symlink/path safety, free disk
  threshold and free inode threshold.
- Chromium `SingletonLock`, `SingletonSocket` and `SingletonCookie` cleanup is now
  guarded by both session ownership and healthy storage/auth checks.
- Startup no longer treats all Chromium singleton files as safe-to-delete merely
  because Compose is expected to have one container.
- Shutdown releases the owner guard.
- No routine path removes the LocalAuth credential directory.

Primary files:

- `whatsapp-web-session/session-safety.js`
- `whatsapp-web-session/session-safety.test.js`
- `whatsapp-web-session/server.js`

### P34 — Extended WhatsApp status API

Status: `DONE`

Delivered:

- Preserved the existing WhatsApp status contract for backward compatibility.
- Added an authenticated operational status surface exposing factual runtime state:
  - alive vs messaging-ready,
  - connection + connection change time,
  - recovery state/reason and pause state,
  - last probe / last ready / last acknowledged send,
  - recovery budget/cooldown and policy version,
  - operator-action-required state and reason,
  - owner acquisition/conflict facts,
  - storage health/reasons and free capacity facts,
  - durable receipt-store health plus SENT / UNKNOWN / in-flight counts.
- Added authenticated internal recovery controls for pause/resume/reconnect/pair.
- Added additive TalentOps API under
  `/api/talentops/v1/system/whatsapp/operations`.
- Web controls reuse existing authenticated session / workflow operator authority and
  CSRF protection.
- Pairing control is admin-only and accepted only while the bridge actually reports
  operator action / pairing as required.

Primary files:

- `whatsapp-web-session/server.js`
- `src/digital_bast/infrastructure/whatsapp_outbound.py`
- `src/digital_bast/web/whatsapp_ops_router.py`
- `src/digital_bast/web/app.py`
- `tests/unit/infrastructure/test_whatsapp_outbound.py`
- `tests/unit/web/test_whatsapp_ops_router.py`

### P35 — Payroll WhatsApp operations UI

Status: `DONE`

Delivered:

- Reused the existing `System & Sync` page rather than creating a second operator
  console.
- WhatsApp card now presents compact operational states including:
  - `Terhubung`,
  - `Sedang pulih`,
  - `Perlu tindakan`.
- UI exposes factual recovery reason/state, owner/storage safety, durable receipt
  counts including `UNKNOWN`, and recovery budget/cooldown context.
- Safe controls are available for pause/resume/reconnect according to current state.
- Controlled pairing is exposed only to admin sessions and only when pairing is
  genuinely required.
- Existing QR / pairing-code flow remains available when relevant.

Primary files:

- `frontend/src/api/whatsapp-operations.ts`
- `frontend/src/api/talentops.ts`
- `frontend/src/api/types.ts`
- `frontend/src/pages/SystemSyncPage.tsx`
- `frontend/src/pages/SystemSyncPage.test.tsx`

### Validation truth

Validation PR #74 is a draft CI trigger only; it is not a merge/release candidate.

Final validation run for the wave:

- GitHub Actions CI run `#519` / `35481460442`
- validated head: `d559e9fb10cf11deb6c55f40be3d5b833a6e3472`

Observed results:

- `secrets` / gitleaks: **PASS**.
- `uv sync --all-groups`: **PASS**.
- `uv run python -m compileall -q src tests`: **PASS**.
- `migration-smoke`: **PASS FULL**.
  - container initialization: PASS,
  - migration gate: PASS,
  - migration idempotency gate: PASS,
  - smoke/shadow gate: PASS.
- repository-wide `uv run ruff check .`: **FAIL with exactly 108 findings**.
  - Initial P31–P35 validation reported 113 findings.
  - Five wave-local findings were fixed narrowly.
  - Run #519 returned exactly to the pre-wave branch baseline of 108 findings.
  - None of the P31–P35 changed files appears in the final Ruff failure list.
  - The remaining 108 findings are pre-existing branch debt from earlier Payroll
    cards plus unrelated legacy/BAST/infrastructure code.
- Because repository-wide Ruff fails first, the quality job does **not** reach
  `basedpyright`, full `pytest`, or `scripts/check-ops.sh`. A full green Python
  quality job is therefore **not claimed**.
- The repository CI workflow does **not** execute a Node / frontend npm test or
  typecheck suite. Node and frontend focused tests were authored, but a CI-green
  Node/frontend suite is **not claimed**.
- `container` job: **FAIL during job setup before checkout/build** because GitHub
  Actions cannot resolve `aquasecurity/trivy-action@0.30.0` (`unable to find
  version 0.30.0`). The product image is never built in that job, so this result
  does not constitute a P31–P35 container-code failure.

Run #516 independently produced the same container setup failure and also passed
migration gate + migration idempotency + smoke/shadow, corroborating the #519
migration result.

### Wave acceptance result

The WhatsApp reliability path is now:

```text
Payroll logical delivery reservation
  -> stable bounded gateway request id
  -> durable gateway ACCEPTED receipt
  -> WhatsApp send
       -> SENT: durable receipt + provider id
       -> ambiguous after acceptance: UNKNOWN, never blind-retry
  -> Payroll logical ledger reflects SENT / retryable / final / UNKNOWN truth

WhatsApp session runtime
  -> acquire single-owner lease
  -> verify auth/storage safety
  -> guarded Chromium stale-lock cleanup
  -> start LocalAuth client
  -> readiness supervisor
       -> transient disconnect only: bounded recover
       -> budget exhausted: cooldown
       -> permanent logout/auth failure: operator action required
  -> System & Sync operational status + safe controls
```

while preserving LocalAuth as credential authority, existing WhatsApp transport,
raw attendance immutability, correction/approval truth, legacy CSV behavior, and
conservative fail-closed semantics.

---

## Next execution wave — Intelligence & Export Integration (P36–P38)

There are **9 cards remaining: P36–P44**.

Execute P36–P38 as the next integration wave, then P39–P44 for final verification,
acceptance and production enablement.

### P36 — Natural Talent attendance interpretation

Status: `TODO`

Add context-aware date / missing-clock extraction for Talent WhatsApp input while
keeping the deterministic button/text/numeric state machine as the authority and
fallback. Pass the actual inbound message timestamp so relative-date wording is
resolved against message time, not server guesswork.

### P37 — PMO closing queries

Status: `TODO`

Expose closing status, outstanding work, genuinely unresponded Talent and role
filters as backend-supplied facts. LLM may interpret/summarize those facts but may
not invent closing truth, reminder delivery outcomes or approval state.

### P38 — Payroll export action/history

Status: `TODO`

Wire Payroll export to the existing legacy attendance export implementation with an
explicit 21–20 cycle and role selection. Store/export history metadata only. Do not
change CSV schema, delimiter, date format, filename contract, correction projection
or raw attendance authority.

### Continuation instructions

For a new session:

1. Read `docs/development-execution-standard.md`.
2. Read `docs/payroll-attendance-implementation-plan.md`.
3. Read this rolling checkpoint.
4. Verify branch HEAD and inspect commits after this checkpoint before editing.
5. Continue with P36–P38 without weakening deterministic WhatsApp routing, moving
   business truth into the LLM, or changing the legacy attendance CSV contract.
