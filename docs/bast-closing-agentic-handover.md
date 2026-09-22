# BAST Closing Campaign — Agentic Validation Handover

**Repository:** `yosdwi/celerates-bast-digital`  
**Working branch:** `chore/session-20260918-fixes`  
**Validation PR:** #77 `[validation only] BAST closing campaign completion`  
**Do not merge or deploy automatically.**

## 0. Implementation completion snapshot

**Feature implementation code HEAD before this handover-document update:** `3ed4b44e548cca4c3d641b90e37beffe71b1289c`.

The requested BAST Closing feature scope is **implementation-complete** at that code HEAD. There is no known remaining product-feature coding item in scope. The next agent must perform validation, audit, and narrowly scoped corrective fixes only.

Latest CI evidence collected from validation-only PR #77 / CI run #565 on code HEAD `3ed4b44e...`:

- `uv run python -m compileall -q src tests` — **PASS**.
- Gitleaks / secrets job — **PASS**.
- Migration smoke job reached and passed:
  - migration gate — **PASS**;
  - migration idempotency gate — **PASS**;
  - smoke and shadow gate — **PASS**.
- Global Ruff — **FAIL**, with **112 repository-wide findings**. After the final wave-local cleanup, the Ruff output no longer reports the newly added BAST Closing modules nor the shared files `domain/completion.py`, `infrastructure/completion_source.py`, or `web/app.py` touched by this wave. Treat the remaining Ruff set as pre-existing/shared-branch debt unless a fresh diff proves otherwise; do not mass-fix it as part of this handover.
- `basedpyright` and full `pytest` — **not executed by CI**, because the quality job stops after global Ruff failure. Do not claim these as passed.
- Container job — **FAIL before checkout/execution** because GitHub Actions could not resolve `aquasecurity/trivy-action@0.30.0`. This is a CI dependency/action-resolution failure, not evidence of a BAST runtime failure.

The handoff agent must therefore finish **validation completeness**, not feature implementation. It should run focused BAST tests/type checks/builds (or isolate the baseline Ruff debt cleanly), correct only real regressions, and return explicit deploy-ready/not-deploy-ready evidence.

This handover is **validation / audit / corrective-fix only**. The product and feature implementation decisions below are locked. Do not redesign the flow unless a verified contradiction in the existing source-of-truth requires a narrowly scoped corrective change.

## 1. Preflight

Before any write:

1. Fetch `chore/session-20260918-fixes` and record its exact current HEAD.
2. Do not create a new branch unless explicitly requested by the user.
3. This is a shared branch. If HEAD advanced after this document was written, inspect every newer commit before editing.
4. Read this file plus the touched BAST Closing modules listed below before making changes.
5. PR #77 is validation-only. Never merge it as part of this handover.

## 2. Locked business rules

### Campaign

- BAST Closing is a calendar-month campaign.
- Initial Talent reminder: day 25.
- Follow-ups: EOM-3 and EOM-1.
- Final closing assessment / PMO digest: EOM.
- Resolve dates from the real calendar; never hardcode 25/27/29/30.
- Deduplicate date collisions (for example February day 25 may equal EOM-3).
- BAST and Payroll are independent campaigns but share the existing Prefect `pmo-notifications` heartbeat.
- BAST campaign defaults **OFF** after migration. No deployment may start blasting by default.

### Task List

- Task status is factual source data (Redmine/source authority).
- BAST chatbot/web **must never close or mutate task status**.
- If a Task is Open/In Progress/etc, BAST may show it and direct the Talent to the source, but cannot offer a Close action.
- Non-Closed Task remains a BAST blocker.

### Evidence

- Not every Task requires evidence.
- Requirement is explicit and deterministic via `bast_evidence_rules`, keyed by existing `TaskCategory`.
- Unknown/unconfigured category defaults to `evidence_required = false`.
- AI must never decide whether evidence is required.
- Only Closed + configured-required tasks can become Evidence blockers/candidates.
- The configured rule applies consistently to readiness, legacy WhatsApp Evidence, and Talent Mobile staging/submission.

### Attendance

- Do not create a second attendance truth or workflow engine for BAST.
- BAST surfaces factual Attendance blockers and routes Talent into existing correction authority/surface.
- Pending PMO attendance corrections are not re-blasted as if the Talent still did nothing.
- Raw attendance remains immutable in the approval flow.

### Talent WhatsApp

- Talent reminder is compact and direct-to-problem: Task / Attendance / Timesheet / Evidence.
- No `ketik menu` dependency.
- Numbered fallback is supported through durable BAST reminder context.
- Natural domain phrases are accepted; natural Attendance-like text resolves to the BAST Attendance domain when present.
- Natural Attendance text such as `25 September pulang 17.31` seeds the existing canonical Attendance correction context; BAST does not own a second attendance mutation engine.
- Every reply is revalidated against current BAST snapshot before presenting current work.
- Task reply is read-only and explicitly points back to source authority.
- Evidence surface must only show configured-required tasks.

### PMO

- PMO remains web-first.
- PMO WhatsApp group receives one aggregate BAST summary, not one message per Talent action/submission.
- Summary contains Complete / Need Talent Action / Waiting PMO / Source Review and factual blocker counts.
- PMO group destination is selected from the existing live WhatsApp Directory discovery; saved-but-currently-undiscovered JID remains visible as fallback.

### Manual blast / delivery safety

- Web Configuration includes Preview before manual Talent blast.
- Manual Talent blast and scheduled Talent blast use the same engine and idempotency behavior.
- Manual send on a scheduled date consumes that scheduled slot, including a send before the configured scheduled hour, so the later heartbeat must deduplicate it.
- PMO summary has Preview + Manual Send as well.
- Manual PMO summary on a scheduled date consumes the same scheduled digest slot.
- Ad-hoc PMO summaries outside a scheduled date use unique delivery milestones and may be sent repeatedly.
- Delivery `UNKNOWN` is never blindly retried.

### BAST export

- Printing rule and readiness rule are separate.
- BAST output must print a canonical **Task List — All Status** section including Open / In Progress / Closed / other factual statuses for the selected role/month.
- Existing legacy detail/SLA sections remain untouched because they carry separate calculations.
- Non-Closed tasks being printed does **not** make them complete.

## 3. Implemented feature map

### Migrations

- `migrations/versions/20260922_0028_bast_closing_campaign.py`
  - `bast_closing_settings`
  - `bast_evidence_rules`
  - default campaign OFF
- `migrations/versions/20260922_0029_bast_reminder_context.py`
  - durable ordered domain context per WhatsApp JID for BAST reminder replies

### Campaign / snapshot / scheduling

- `src/digital_bast/application/bast_closing.py`
  - BAST settings, evidence rules, calendar schedule, collision-safe follow-up dates
- `src/digital_bast/application/bast_snapshot.py`
  - factual per-Talent closing projection
  - separates Talent-actionable, Waiting PMO, source-review, complete
- `src/digital_bast/application/talent_reminders.py`
  - scheduled Talent reminders
  - manual preview/send
  - same-slot idempotency
  - durable reply context after successful delivery
- `src/digital_bast/bast_runtime.py`
  - production wiring
- `src/digital_bast/flows/notifications.py`
  - existing Prefect heartbeat runs Payroll and BAST independently

### Evidence requirement enforcement

- `src/digital_bast/domain/completion.py`
- `src/digital_bast/infrastructure/completion_source.py`
- `src/digital_bast/infrastructure/local_completion_source.py`
- `src/digital_bast/infrastructure/bast_evidence_rules.py`
- `src/digital_bast/bot/requirement_aware_evidence.py`
- `src/digital_bast/operations.py`

The low-level legacy Evidence service still knows the old Closed-task mechanics, but production factories wrap it with `RequirementAwareEvidenceService` / `RequirementAwareTaskEvidenceSubmissionService`. Validation must verify no production caller bypasses those factories for Talent evidence flows.

### BAST reply context / natural Attendance handoff

- `src/digital_bast/bot/bast_reminder_context.py`
- `src/digital_bast/bot/bast_reminder_reply.py`
- `src/digital_bast/bot/bast_attendance_draft.py`
- `src/digital_bast/bot/dm_message_entry.py`

Routing precedence is intentionally:

1. already-open Payroll attendance draft;
2. active BAST reminder context;
3. Payroll reminder bootstrap;
4. legacy DM entry.

This prevents an older Payroll reminder context from stealing the bare numeric reply to a newer BAST reminder, while still letting an already-open Payroll correction finish safely. Natural BAST Attendance replies use the existing Attendance resolution state/context after exact-date revalidation.

### PMO BAST digest

- `src/digital_bast/application/bast_group_digest.py`
- `src/digital_bast/bast_runtime.py`
- `src/digital_bast/flows/notifications.py`
- `src/digital_bast/web/bast_closing_router.py`

BAST intentionally reuses the proven `payroll_group_digest_deliveries` lifecycle/store with a separate `cycle_id` namespace (`bast:YYYY-MM`) and BAST-specific idempotency keys. Migration 0026 does not constrain cycle or milestone format. Scheduled milestones deduplicate; ad-hoc manual milestones include a UUID so repeated manual summaries do not violate the existing `(scope_key, cycle_id, milestone)` unique index.

### Web Configuration / manual triggers

- `src/digital_bast/web/bast_closing_router.py`
- `src/digital_bast/web/app.py`
- `frontend/src/api/bastClosing.ts`
- `frontend/src/components/BastClosingSettings.tsx`
- `frontend/src/pages/SettingsPage.tsx`

Configuration surface contains:

- Campaign ON/OFF (Admin write)
- Initial reminder day
- send hour / WIB
- EOM-relative schedule preview
- Evidence Rules per TaskCategory
- Talent reminder toggle
- PMO summary toggle
- PMO group selected from discovered WhatsApp groups
- Preview + Manual Talent Blast
- Preview + Manual PMO Summary

PMO/operator access can preview/send where existing `can_generate_bast` permits; Admin owns campaign/evidence configuration mutations.

### All-status BAST export

- `src/digital_bast/web/bast_all_status_tasks.py`
- `src/digital_bast/operations.py`
- `src/digital_bast/application/bast_generation_jobs.py` already generates through `operations.generate_bast()`

A canonical all-status section is injected into both document/editor representations before PDF rendering. Existing legacy detail/SLA sections remain for backwards-compatible calculations.

## 4. Required validation — do not skip

### Source / migration

- Confirm exact branch HEAD before work.
- Migration smoke for 0028/0029 already passed in CI #565, but re-run if validation work changes migration/runtime wiring.
- Verify clean DB upgrade and idempotent application startup after any corrective changes.
- Do not downgrade production as part of normal validation.

### Python quality

Run at minimum:

- Python compile / import check for changed modules.
- Focused Ruff against the BAST-wave file set or an equivalent baseline-diff lint check.
- basedpyright/type check if available.
- focused BAST tests plus relevant Payroll regression tests.
- full Python suite only after distinguishing global pre-existing lint debt from wave-local failures.

Current CI global Ruff baseline is red (112 findings) and therefore blocks later quality steps. Do not mass-edit unrelated files. Classify findings into:

1. wave-local BAST regression — fix;
2. historical/unrelated baseline — report only.

### Frontend

Run:

- frontend TypeScript/build;
- frontend unit tests;
- Settings page/component tests for BAST controls.

Validate the PMO group selector works with live-directory success and with discovery unavailable/saved JID fallback.

### Required behavioral cases

1. **Schedule collision**
   - Feb EOM collision produces unique reminder dates.
2. **Campaign default**
   - no BAST Talent/PMO send while campaign disabled.
3. **Evidence not required**
   - Closed task with rule=false has no evidence blocker and is absent from upload candidates.
4. **Evidence required**
   - Closed task with rule=true + no evidence is a blocker/candidate.
   - after evidence submission it clears from missing-evidence readiness.
5. **Non-Closed Task**
   - remains Task blocker.
   - never gets chatbot/web Close mutation.
6. **Reminder reply context**
   - numbered reply maps to the domain actually shown in the latest BAST reminder.
   - stale/changed domain revalidates and does not mutate stale facts.
   - a current BAST reminder wins over an old Payroll reminder for bare-number/domain replies.
   - an already-open Payroll draft still wins and can finish normally.
   - natural Attendance reply such as `25 September pulang 17.31` seeds the canonical Attendance draft/context rather than creating a BAST-specific mutation path.
7. **Waiting PMO**
   - pending Attendance correction does not get re-blasted as Talent action.
8. **Source review**
   - technical/source unavailable status is not blamed on Talent.
9. **Manual Talent blast**
   - Preview matches current snapshot.
   - manual send on due date consumes scheduled slot and later scheduler is duplicate-safe.
   - ad-hoc day does not consume the next scheduled day.
10. **PMO aggregate digest**
    - only one aggregate group message.
    - scheduled and same-day manual share scheduled idempotency.
    - repeated ad-hoc manual sends outside scheduled date are independent and do not collide on the group-delivery unique index.
    - UNKNOWN delivery never blind retries.
11. **All-status BAST export**
    - canonical Task List contains at least Open + In Progress + Closed fixtures together.
    - readiness still treats Open/In Progress as blockers.
    - Developer and IoT/Shifting role output both include the all-status section.
12. **Payroll regression**
    - existing Payroll H-5/H-3/H-1 correction flow, exact date routing, approval and digest behavior remain unchanged.

## 5. Audit points worth extra attention

These are not invitations to redesign. Validate and only correct if a real issue exists:

- `bast_all_status_tasks.py` does a second read after the legacy assembler transaction. Verify whether snapshot consistency is acceptable for the production generation path; if not, fix narrowly without changing the all-status requirement.
- `payroll_group_digest_deliveries` is reused intentionally for BAST group lifecycle. Ensure no hidden consumer assumes every row has a Payroll-format cycle ID.
- Production evidence paths must use the requirement-aware factories from `operations.py`; find any direct production `EvidenceService(...)` or `TaskEvidenceSubmissionService(...)` construction that bypasses them and correct only those paths.
- BAST Attendance free text must route into existing attendance correction authority/surface, not create a new BAST attendance mutation engine.

## 6. Deployment gate

Feature code being present does **not** authorize deployment.

Before enabling BAST in production:

1. Migrations 0028/0029 must be applied successfully.
2. Validation above must be complete.
3. BAST campaign must remain OFF until PMO/Admin explicitly enables it from Settings.
4. Preview Talent Blast must be reviewed.
5. PMO group must be selected/verified.
6. Evidence rules must be reviewed; unknown/default remains Not Required.
7. Do not merge PR #77 as part of validation.

## 7. Agentic completion report required

Return a concise handback containing:

- exact final HEAD;
- commits added by validation/corrective work;
- migration result;
- compile/lint/type/test/frontend results with exact commands/evidence;
- any historical baseline failures clearly separated from BAST-wave failures;
- whether all behavioral cases above passed;
- residual findings, if any;
- explicit `deploy-ready` or `not deploy-ready` conclusion based on evidence only.

Do not claim a check passed unless it actually ran.
