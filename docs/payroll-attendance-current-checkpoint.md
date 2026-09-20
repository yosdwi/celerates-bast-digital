# Payroll Attendance — Current Execution Checkpoint

This is the rolling execution checkpoint for
`docs/payroll-attendance-implementation-plan.md`.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`  
Checkpoint date: 20 September 2026

## Execution status

**P00–P44 implementation: COMPLETE.**  
**Production gate: HOLD pending missing execution evidence.**

Implementation-complete does not mean production-ready. The release gate and the
remaining validation truth are recorded in
`docs/payroll-attendance-production-gate.md`.

This project continues to follow `docs/development-execution-standard.md`: cards are
audit/commit boundaries, source-of-truth correctness takes precedence over speed,
changes remain small/revertible, and unrelated historical debt is not silently
reworked.

## Wave baseline and branch safety

The Intelligence + Export / final hardening execution resumed from:

- requested baseline: `19a0b4d2cec8f6dd7f74da50bd63ec71f7aa7390`
- branch: `chore/session-20260918-fixes`

The branch HEAD was verified before editing and again before commit boundaries. No
parallel commit was overwritten. Final diff audit from `19a0b4d2...` before the
checkpoint showed the branch **ahead only, behind 0**, with changes limited to the
expected P38/P39/P41/P43 scope.

The previous rolling checkpoint was stale: it stopped at P35 and still marked P36
and P37 as TODO even though the source at `19a0b4d2...` already contained their
implementation and focused tests. Source/commit state was therefore used as the
authority rather than reverting working P36/P37 code to match stale documentation.

---

## P36 — Natural Talent attendance interpretation

Status: `DONE` before this wave resumed.

Locked behavior remains:

- original WhatsApp message timestamp is passed into attendance interpretation;
- relative dates such as `kemarin` / `hari ini`, explicit dates, ISO and DMY are
  anchored to the inbound message timestamp;
- deterministic existing button/text/numeric parser has higher precedence;
- NLP/LLM produces only a typed candidate;
- candidate must match the exact active gap and pass work-date, resolution-type and
  latest-projection revalidation;
- wrong date/type means no mutation;
- `missing_both` is never guessed from one time value;
- natural language is not a second business-state machine.

## P37 — PMO Payroll closing queries

Status: `DONE` before this wave resumed.

PMO query answers are grounded in deterministic Payroll closing facts:

- 21→20 selected cycle,
- summary status,
- waiting review,
- actionable/outstanding items,
- reminder delivery facts,
- `UNRESPONDED`,
- delivery `UNKNOWN`,
- role filtering.

AI may phrase the answer from the factual digest. If AI is unavailable, the factual
digest remains the answer authority.

---

## P38 — Payroll Export Action + History

Status: `DONE`

Primary commits:

- `b32e6b69f4adb5d5fb1e6d0353480f3645141552` — Payroll export wrapper, metadata
  history store and migration `0027`;
- `39c71140adc4e3e186144d0700e73f1ceaa15f7e` — authorized PMO/admin API + CSRF;
- `e28e11c3b0334046cd939c92ff64db5f92ace186` — Payroll export/history UI;
- `a021aa52ae502c81eb3b8f3aecc20503ed98ecc7` — focused P38 tests;
- `bcc4626c11f63dccc437b83408a0de688780c641` — narrow lint-neutral correction for
  final-wave files with no business-semantic change.

Delivered:

- selected Payroll cycle is translated using the canonical inclusive 21→20 rule;
- export remains a wrapper over
  `operations.py::export_attendance_report(...)` → existing
  `attendance_legacy(...)` CSV generation;
- legacy CSV schema, delimiter, column order, filename/date semantics and correction
  projection are unchanged;
- PMO/admin POST export follows existing session/CSRF authorization;
- history is metadata-only: export id, cycle/range, actor, report/role/employee
  filter, timestamp, filename, result and factual row count;
- history does not store a duplicate CSV blob;
- export continues to see the latest approved correction projection and does not
  create a second Payroll truth;
- web surface provides explicit cycle/range confirmation, download and compact
  history.

## P39 — Cross-surface integration

Status: `DONE`

Commit:

- `70ea9663fe18bfe7eaefd25ca3a2b4c60bf61eed`

Focused integration coverage now connects:

```text
Talent correction submission
  -> PMO Review Queue
  -> approve / reject
  -> closing projection
  -> existing legacy attendance export truth
```

The integration coverage locks that approval does not mutate raw attendance and
that rejection returns the item to `NEEDS_TALENT_ACTION`.

## P40 — WhatsApp integration/failure hardening

Status: `DONE — existing coverage audited; no duplicate code/test churn added.`

Existing P31–P35 coverage already verifies the requested failure boundaries:

- bridge unavailable / retryable delivery;
- ambiguous accepted delivery becomes durable `UNKNOWN`;
- `UNKNOWN` is not blindly resent;
- durable `SENT` and `UNKNOWN` behavior across restart;
- duplicate request-id conflict;
- bounded/serialized reconnect;
- group digest failure and logical deduplication;
- manual reminder duplicate safety;
- manual resend blocked when prior delivery is `UNKNOWN` or retry is pending.

`whatsapp-web-session` has an executable `node --test` suite, but the repository PR
CI does not invoke it; this checkpoint therefore does not claim a fresh Node-green
run.

## P41 — Frontend responsive audit

Status: `DONE`

Commit:

- `03c8572c724f6e2a970c0e24b22118e97e21db92`

Audited the real Payroll/TalentOps surfaces rather than redesigning them.

Existing responsive behavior was already present for Talent mobile, Review Queue,
Contacts & WhatsApp, export/history and the surrounding Settings/System surfaces.
One concrete functional break was found in Talent Follow-up:

- the list rendered only inside global `.desktop-table-wrap`;
- global CSS hides that wrapper at `<=760px`;
- therefore the entire Follow-up list disappeared on mobile.

Fix:

- Follow-up uses a dedicated wrapper and becomes stacked cards on narrow viewports;
- reminder preview text wraps instead of forcing horizontal overflow;
- focused frontend test locks that the list is no longer inside the desktop-only
  wrapper.

No unrelated visual redesign was performed.

## P42 — Local/integration validation

Status: `DONE as an evidence audit; release validation remains incomplete.`

Draft validation-only PR:

- PR #75 — `[validation only] Payroll attendance closing final gate`
- do-not-merge; used only to execute repository CI.

Latest code-validation evidence before this checkpoint:

- CI run `#523`
- run id `35500941799`
- validated branch code head: `bcc4626c11f63dccc437b83408a0de688780c641`

Observed:

- gitleaks / secrets: **PASS**;
- Python compileall: **PASS**;
- migration `0027`: **PASS**;
- migration idempotency / second upgrade: **PASS**;
- smoke/shadow: **PASS**;
- repository-wide Ruff: **FAIL with 142 findings**;
- after the focused lint-neutral fix, none of the P38–P44 wave files appears in the
  Ruff failure output;
- remaining Ruff findings belong to earlier Payroll cards and unrelated historical
  repository debt and were intentionally not cleaned in this wave;
- because Ruff exits first, CI does not reach basedpyright, full pytest or
  `scripts/check-ops.sh`;
- PR CI does not execute frontend Vitest/typecheck or the active
  `whatsapp-web-session` Node suite;
- container job fails during runner setup before checkout/build, so no image result
  is inferred from that failure;
- a direct local checkout was attempted for additional frontend/Node execution, but
  the available runtime could not resolve `github.com`, so those tests are not
  claimed as executed;
- no unavailable external WhatsApp provider state was fabricated.

Global Ruff is therefore not green. The final-wave requirement met here is narrower:
**P38–P44 introduced no remaining Ruff finding in their changed Python files.**

## P43 — Manual acceptance checklist

Status: `DONE`

Commit:

- `b3fafba74a2b66fc12dde70e969cf8c9b3758f9d`

Operator checklist:

- `docs/payroll-attendance-manual-acceptance.md`

It covers Talent correction, deterministic/NLP guardrails, PMO approve/reject/bulk
revalidation, reminder policy, aggregate digest, Follow-up, WA recovery and durable
`UNKNOWN`, LocalAuth preservation, export/history and operator sign-off.

## P44 — Soak / production gate

Status: `DONE as gate definition; gate decision remains HOLD.`

Gate document:

- `docs/payroll-attendance-production-gate.md`

The gate explicitly covers:

- migration + idempotency evidence;
- scheduler disabled/paused/enabled safety;
- no double reminder;
- durable `SENT` / `UNKNOWN` receipt behavior;
- manual resend safety;
- aggregate PMO group delivery;
- `BOT_AUTH_DIR=/data/auth-whatsapp-web-js` LocalAuth ownership on persistent
  `bot-bridge-data` storage;
- bounded reconnect and operator-required auth states;
- additive migration rollback strategy;
- observability surfaces and delivery-ledger states;
- known CI/tooling limitations;
- evidence still required before production enablement.

The production decision is intentionally **HOLD**, not `READY`.

---

## Locked authorities after P44

These remain unchanged:

1. Payroll cycle = day 21 through day 20 inclusive.
2. Raw attendance is immutable.
3. Approved correction projection is the effective attendance authority.
4. Evidence supports correction; it is never approval/readiness.
5. Only `NEEDS_TALENT_ACTION`, `WAITING_SUBMITTED`, `COMPLETE` are business
   closing statuses.
6. Talent is WhatsApp-first; PMO is web-first.
7. PMO group receives aggregate closing digest, not every Talent submission.
8. Reminder milestones default H-5/H-3/H-1; day 20 final assessment/digest.
9. `UNRESPONDED` requires successful reminder + no later attendance response.
10. Technical source/transport failure is not Talent fault.
11. `UNKNOWN` must never blind retry.
12. Existing `whatsapp-web-session` / whatsapp-web.js transport remains active.
13. LocalAuth remains `/data/auth-whatsapp-web-js` on persistent data storage.
14. Existing legacy attendance CSV exporter remains canonical.
15. No workflow engine, event bus, second Payroll truth database or automatic
    approval was introduced.
16. Existing BAST monthly behavior remains outside this Payroll-closing change.

## Release handoff

The branch is now an **implementation-complete release candidate**, not a declared
production-ready build.

Before enabling real Payroll closing traffic, the release owner should use
`docs/payroll-attendance-production-gate.md` and complete
`docs/payroll-attendance-manual-acceptance.md` in the intended environment.

The remaining decision is a release/validation decision, not another feature-design
wave. Do not reopen P00–P44 or clean unrelated repository debt unless new evidence
shows a real correctness blocker.
