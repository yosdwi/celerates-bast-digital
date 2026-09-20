# Payroll Attendance — Production Gate

This document is the final P44 go-live gate for the Payroll Attendance Closing /
WhatsApp Attendance Correction flow.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`  
Gate date: 20 September 2026

## Current decision

**HOLD — implementation is complete, but production readiness is not yet proven by
all required execution evidence.**

This status is deliberate. The source now contains the intended P00–P44 behavior,
but this document does not convert missing validation into assumed success.

## 1. Automated validation evidence

Validation was exercised through draft, do-not-merge PR #75.

Latest code-validation run before this production-gate document:

- GitHub Actions CI `#523`
- run id: `35500941799`
- validated branch code head: `bcc4626c11f63dccc437b83408a0de688780c641`

Observed facts:

| Gate | Evidence | Status |
| --- | --- | --- |
| Secrets / gitleaks | CI #523 `secrets` job | **PASS** |
| Python compile | `uv run python -m compileall -q src tests` | **PASS** |
| Migration upgrade | migration-smoke | **PASS** |
| Migration idempotency | second `alembic upgrade head` | **PASS** |
| Smoke / shadow | migration-smoke | **PASS** |
| P38–P44 Ruff neutrality | final Ruff output contains no files introduced/changed by P38–P44 | **PASS for this wave** |
| Repository-wide Ruff | `uv run ruff check .` | **FAIL — 142 findings** |
| basedpyright | skipped because Ruff exits first in the quality job | **NOT RUN** |
| Full pytest | skipped because Ruff exits first in the quality job | **NOT RUN** |
| `scripts/check-ops.sh` | skipped because Ruff exits first in the quality job | **NOT RUN** |
| Frontend Vitest | not executed by `.github/workflows/ci.yml` | **NOT RUN** |
| Frontend typecheck | not executed by `.github/workflows/ci.yml` | **NOT RUN** |
| `whatsapp-web-session` `node --test` | not executed by repository CI | **NOT RUN in this gate** |
| Container/image scan | job failed during runner setup before checkout/build | **NO PRODUCT IMAGE EVIDENCE** |
| Live external WhatsApp delivery | intentionally not fabricated from unavailable provider state | **NOT RUN** |

The 142 repository-wide Ruff findings are not a claim that this wave is Ruff-green.
They remain a global quality limitation. The important wave boundary is that the
P38–P44 files no longer appear in the Ruff failure output after the focused
lint-neutral correction. Historical debt outside this wave was not cleaned up.

The container failure is also not treated as application evidence: the job stopped
at setup before repository checkout/build, consistent with the known CI/tooling
problem around the Trivy action.

## 2. Source-of-truth safety gates

The release must preserve all of the following. A failed item is a stop condition.

### Payroll truth and corrections

- Payroll cycle remains day **21 through day 20 inclusive**.
- Raw attendance remains immutable.
- Talent correction submission remains a proposal, never an approval.
- PMO approval/rejection remains the only correction decision boundary.
- Bulk decisions revalidate every item independently against the latest projection.
- Reject returns the item to Talent action.
- Only these business statuses exist:
  - `NEEDS_TALENT_ACTION`
  - `WAITING_SUBMITTED`
  - `COMPLETE`
- Evidence may support a correction but never means Payroll-ready by itself.
- Natural-language interpretation may produce a typed candidate only; deterministic
  work-date/type/current-gap validation remains authoritative.

### Payroll export

- Payroll export must continue through the existing
  `operations.py::export_attendance_report(...)` path and existing legacy
  `attendance_legacy(...)` projection.
- No Payroll-specific CSV schema, delimiter, column ordering, filename/date contract,
  or second attendance truth may be introduced.
- Export history remains metadata-only; the P38 table must not become duplicate CSV
  storage.
- Export uses the latest authoritative approved-correction projection at execution
  time.

## 3. Scheduler and reminder safety

Before enabling production reminders:

- Confirm Payroll closing policy is intentionally enabled.
- With policy disabled, no new closing reminder or digest may be dispatched.
- With policy paused, no new campaign reminder may be dispatched.
- Default reminder milestones remain H-5, H-3 and H-1 relative to day 20.
- Day 20 remains final assessment/digest.
- Only current `NEEDS_TALENT_ACTION` items are actionable for Talent reminder.
- `WAITING_SUBMITTED` and `COMPLETE` must not receive an attendance-action reminder.
- A successful logical milestone delivery must not be sent twice on later scheduler
  evaluation.
- Manual reminder must revalidate current eligibility immediately before dispatch.

`UNRESPONDED` remains a derived operational fact only when a successful reminder was
sent and no subsequent attendance response exists. Source/transport failure must not
be converted into Talent fault.

## 4. Durable WhatsApp delivery gate

The existing P31–P35 reliability boundary remains mandatory:

- Delivery ledger states are factual:
  `RESERVED`, `SENDING`, `SENT`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `UNKNOWN`.
- A gateway request is durably accepted before provider send.
- Known `SENT` receipt survives process restart and can be returned without a second
  provider send.
- An accepted request with ambiguous outcome becomes durable `UNKNOWN`.
- `UNKNOWN` must **never** trigger blind automatic or manual resend.
- Pending retry must block a parallel/manual duplicate send.
- Reusing the same request id with a different destination/payload is a conflict.
- PMO closing group receives aggregate digest, not every Talent submission.
- A failed group digest must remain a failure fact; it must not be recorded as sent.

This is conservative no-blind-resend behavior, not provider-level exactly-once
delivery.

## 5. LocalAuth and runtime ownership

Current Compose authority for the active `whatsapp-web-session` transport is:

- `BOT_DATA_DIR=/data`
- `BOT_AUTH_DIR=/data/auth-whatsapp-web-js`
- LocalAuth lives on the persistent `bot-bridge-data` data volume.
- The whatsapp-web.js auth directory is intentionally separate from whatsmeow auth.
- Routine recovery must not delete/reset LocalAuth.
- Only the active runtime may hold the session-owner lease before Chromium/session
  recovery-sensitive work.
- Transient reconnect is bounded and serialized.
- Logout/auth-revoked/operator-required states must not enter an automatic pairing
  loop.
- `whatsapp-web-session` follows its dedicated deployment path
  (`scripts/deploy-whatsapp-web-session.sh`), not normal web blue/green replacement.

Before release, verify the intended host/container is the single current owner and
that `/data/auth-whatsapp-web-js` is mounted, writable and preserved.

## 6. Rollback gate

Rollback should reduce outbound risk first, not try to repair state by replaying
messages.

1. Pause/disable the Payroll closing scheduler/policy before application rollback if
   outbound reminder behavior is in question.
2. Roll back the application image/code using the normal deployment mechanism.
3. Migration `0027` is additive. Leaving `payroll_export_history` present while
   older application code runs is the safest default rollback; it does not create a
   second Payroll truth.
4. Only run the `0027` downgrade deliberately. Its rollback removes export-history
   metadata, so preserve/back up that metadata first when it matters operationally.
5. Never resolve a durable `UNKNOWN` by resetting the ledger or blindly resending.
6. Never delete `/data/auth-whatsapp-web-js` as a routine rollback step.
7. If the WhatsApp runtime itself is rolled back/redeployed, preserve both LocalAuth
   and durable gateway receipt state on the shared persistent volume.

## 7. Required observability during enablement

Operators must be able to observe the following without inferring hidden state:

- selected Payroll cycle and evaluated-through date,
- counts for `NEEDS_TALENT_ACTION`, `WAITING_SUBMITTED`, `COMPLETE`, and unverified
  source facts,
- Review Queue and stale/revalidation results,
- Follow-up reason and latest reminder delivery state,
- `SENT` / retryable / final / `UNKNOWN` delivery counts,
- group digest result,
- WhatsApp messaging-ready vs process-alive state,
- recovery reason/budget/cooldown and operator-action-required state,
- LocalAuth owner/storage safety facts,
- export metadata history including cycle, actor, filename, status and factual row
  count.

The existing System & Sync WhatsApp operational card plus Payroll Review Queue,
Follow-up and Export History are the intended operator surfaces. Do not add a second
operational truth just for monitoring.

## 8. Manual acceptance requirement

Complete `docs/payroll-attendance-manual-acceptance.md` in the intended environment
before enabling real closing traffic.

At minimum, acceptance must exercise:

- deterministic and natural Talent correction paths,
- PMO approve and reject,
- reminder disabled/enabled behavior,
- milestone deduplication,
- PMO aggregate digest,
- `UNKNOWN` / restart / duplicate-request safety,
- mobile Follow-up usability,
- export + history using a real selected Payroll cycle.

## 9. Conditions to clear HOLD

A release decision may move from `HOLD` only after the release owner has factual
results for the currently missing gates:

1. targeted/full backend test execution sufficient to cover the final branch code;
2. frontend Vitest and typecheck execution;
3. active `whatsapp-web-session` Node test execution;
4. meaningful container build/scanner execution, or an explicit tooling waiver that
   does not mislabel setup failure as a successful image test;
5. manual acceptance checklist completed in the intended environment;
6. LocalAuth ownership/storage and WhatsApp bridge readiness confirmed on the
   intended runtime;
7. repository-wide Ruff debt explicitly accepted/deferred or remediated by the
   release owner. The P38–P44 wave itself must remain free of new Ruff findings.

Until those facts exist, **do not label this branch production-ready**. The branch is
an implementation-complete release candidate awaiting final execution evidence and
release decision.
