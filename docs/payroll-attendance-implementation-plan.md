# Payroll Attendance Workspace — Implementation Plan

Status: **IMPLEMENTATION PLAN / execution checkpoint**  
Last design lock: **19 September 2026**  
Repository: `yosdwi/celerates-bast-digital`  
Working branch: `chore/session-20260918-fixes`  
Audit / implementation baseline before this document: `bd57e7713fcf7503d8d969eca31a3fef1016192e`

> This file is the canonical handoff for implementation. A new session should read this file first, inspect the current branch HEAD, find the first incomplete commit card, and continue from there. Do not re-design the product unless an implementation finding invalidates a locked assumption.

---

## 1. Product outcome

Build one **Payroll** workspace inside the existing TalentOps web application for attendance closing.

The product is deliberately simple:

- **Talent:** WhatsApp reminder -> fill only the missing attendance information -> attach evidence -> submit.
- **PMO:** Payroll web -> see summary -> review submissions -> bulk approve normal cases -> open only exceptions.
- **PMO WhatsApp:** summary / incident digest only. Never one chat notification per Talent submission.
- **System:** decides who needs action, schedules reminders, correlates responses, tracks delivery, and re-evaluates readiness.
- **AI:** optional interpretation / query helper only. Attendance facts and mutations remain deterministic.

This scope does **not** calculate salary, tax, deductions, or bank transfers.

---

## 2. Locked payroll cycle

Cycle is inclusive and labeled by its ending month:

- Payroll September 2026 = `2026-08-21 .. 2026-09-20`.
- Payroll October 2026 = `2026-09-21 .. 2026-10-20`.
- Payroll January 2027 = `2026-12-21 .. 2027-01-20`.

Day 21 opens the next cycle. Previous cycles remain accessible for outstanding review/export.

The existing BAST calendar-period behavior must remain unchanged. Payroll gets its own cycle helper and contract.

`evaluated_through` is separate from `period_end`: a future day or an ongoing shift is never treated as complete merely because the payroll period contains that date.

---

## 3. Locked attendance statuses

Only three business statuses are shown as primary statuses:

1. `NEEDS_TALENT_ACTION`
   - Talent still needs to provide explicit information/evidence.
   - Rejected submissions that need correction return here.

2. `WAITING_SUBMITTED`
   - Required Talent input is already submitted and waiting for PMO review.
   - Do not remind Talent for this item.
   - Do not call it payroll-ready yet.

3. `COMPLETE`
   - Effective attendance is complete using current attendance facts and approved correction projection.
   - Raw attendance remains immutable.

Technical states such as unbound WhatsApp, send failed, stale source, recovery, draft, or rejected reason are **metadata/reasons**, not new top-level business statuses.

---

## 4. Architecture principle

Do not build a new microservice, event bus, workflow engine, or payroll truth database.

The new core is an application-layer read projection:

```text
Attendance / roster / schedule / evidence / correction requests
                         |
                         v
              AttendanceClosingService
                         |
          +--------------+---------------+
          |              |               |
          v              v               v
      Payroll Web    Talent Reminder   PMO summary/query
          |              |               |
          +--------------+---------------+
                         |
                         v
                 existing review/export
```

Planned modules:

- `src/digital_bast/application/attendance_closing_policy.py` — pure cycle/milestone/evaluation helpers.
- `src/digital_bast/application/attendance_closing.py` — canonical read projection.
- `src/digital_bast/application/attendance_bulk.py` — only when durable multi-date orchestration is required.
- `src/digital_bast/web/payroll_router.py` — Payroll API.
- `src/digital_bast/web/payroll_contracts.py` — Payroll API contracts.
- `frontend/src/pages/PayrollPage.tsx` — top-level Payroll UI.
- `frontend/src/api/payroll.ts` — Payroll API client.

Existing correction, evidence, identity, approval, scheduler, WhatsApp transport, CSV export, session and CSRF mechanisms are reused.

---

## 5. Talent UX — WhatsApp first

### 5.1 Primary entry is the reminder

Do not force Talent through a menu or Mobile page.

Example reminder:

```text
Halo Andi, ada 2 attendance Payroll September yang perlu dilengkapi:

4 Sep — Clock Out belum ada
7 Sep — Clock In belum ada

[Lengkapi] [Nanti]
```

Text-number fallback remains available if native interactive controls are unavailable.

### 5.2 One problem at a time

After `Lengkapi`, system selects the first current actionable gap.

```text
4 Sep
Clock In tercatat 07:32.
Clock Out belum ada.

Jam pulang berapa?
```

Talent may answer `17.40` or a natural sentence. Backend stores only explicit user-provided facts.

If evidence is required:

```text
Oke, jam pulang 17:40.
Sekarang kirim screenshot/bukti attendance untuk 4 Sep.
```

Evidence is uploaded through existing attendance evidence service and attached to the selected attendance identity.

Then:

```text
4 Sep
Masuk: 07:32
Pulang: 17:40
Bukti: ✓

[Ajukan] [Ubah]
```

Submit continues through existing `AttendanceResolutionService`.

### 5.3 After submit

Never claim complete while waiting for PMO.

```text
4 Sep sudah diajukan ✓

Masih ada 1 attendance:
7 Sep — Clock In belum ada

[Lanjut] [Selesai dulu]
```

When no current Talent action remains:

```text
Semua informasi attendance yang perlu kamu lengkapi sudah diajukan ✓
Tidak ada action lain untuk saat ini.
```

Do not return the user to a menu unless they explicitly request it.

### 5.4 Progressive shortcuts only

Do not present a large menu up front.

If several gaps have the same missing field, the system may offer one useful shortcut:

```text
4, 7, dan 9 Sep sama-sama belum ada Clock Out.
Jam pulangnya sama?

[Sama] [Berbeda]
```

Only show the shortcut when it removes work. Otherwise process one gap at a time.

### 5.5 Talent Mobile position

Talent Mobile is **not in the happy path**.

It remains an optional visual companion for unusually large/complex batches or explicit user choice. A normal single/multi-gap closing flow must be completable entirely in WhatsApp.

---

## 6. PMO UX — summary and review queue

PMO does not receive one WhatsApp message per submission.

Default Payroll web view answers three questions immediately:

1. How many are complete?
2. How many still require Talent action?
3. How many are waiting for PMO review?

Example:

```text
Payroll September · 21 Agu – 20 Sep
Dievaluasi sampai 19 Sep 23:59

92 Complete     10 Perlu Talent     18 Menunggu Review
```

Then show two operational panels:

```text
REVIEW QUEUE                              18
11 Clock Out
 4 Clock In
 3 Absence
[Review submissions]

TALENT FOLLOW-UP                          10
 6 belum merespons
 3 draft belum selesai
 1 perlu perbaikan
[Preview reminder] [Kirim sekarang]
```

Full Talent table remains below for search/drill-down.

### 6.1 Review queue

Normal cases are bulk-reviewable:

```text
[ ] Andi   4 Sep   Clock Out 17:40   1 bukti
[ ] Budi   5 Sep   Clock Out 17:35   1 bukti
[ ] Citra  7 Sep   Clock Out 17:42   1 bukti

[Setujui 3]
```

Before bulk approve, revalidate each request/current source. Partial success is allowed and reported honestly.

### 6.2 Exception review

Opening one row shows existing actual values, proposed values, evidence, submission time and review actions in a drawer/inline detail. No navigation to another page is required.

### 6.3 Reject flow

PMO chooses a concise structured reason (plus optional note). Rejected item returns to `NEEDS_TALENT_ACTION`. System follows up with Talent; PMO does not manually chat the Talent.

---

## 7. PMO WhatsApp behavior

PMO WhatsApp is summary/incident only.

Expected periodic digest after a closing reminder run:

```text
Payroll September — H-3

120 Talent dievaluasi
92 Complete
18 Menunggu review
10 Perlu Talent action

Reminder hari ini:
8 berhasil dikirim
2 belum memiliki WA aktif

18 pengajuan menunggu review.
Buka Payroll Workspace: <url>
```

No per-submission PMO message.

Allowed PMO outbound categories:

- H-5/H-3/H-1 closing summary.
- Final closing summary.
- Important delivery/session incident.
- Optional post-recovery summary.

---

## 8. Reminder policy

Default proposal, configurable in the web control plane:

- closing day: `20`.
- Talent reminders: `H-5`, `H-3`, `H-1`.
- reminder time: `09:00 Asia/Jakarta`.
- final assessment / shift grace: configurable.
- manual preview/send: supported.
- campaign pause/resume: supported.

The existing 15-minute Prefect cadence is retained. Scheduler evaluates policy and current projection.

Reminder invariants:

- only `NEEDS_TALENT_ACTION` is reminded.
- `WAITING_SUBMITTED` is skipped.
- `COMPLETE` is skipped.
- a successful logical milestone reminder is not resent blindly.
- reminder payload is based on the current missing action, not historical gaps.
- if evidence already exists, do not ask for it again.
- if the action changed before initial dispatch, rebuild/cancel before sending.

---

## 9. Stable WhatsApp context

A reminder/list snapshot stores actual `attendance_key` identities in the exact order sent. Digits never refer to a dynamically recomputed list.

If item 1 becomes complete elsewhere, replying `2` still resolves to the attendance item that was number 2 in the message.

Context is revalidated for ownership and current state before every mutation.

Gateway menu shortcut state must not silently reinterpret attendance digits before Python receives them.

---

## 10. Evidence

Reuse existing attendance evidence storage, ownership checks and SHA duplicate handling.

Initial supported formats for closing:

- JPEG
- PNG
- WebP
- PDF after the additive DB/content-type constraint change is implemented and tested.

Do not treat arbitrary WhatsApp Document messages as valid PDF based on extension only.

Evidence remains supporting information. Evidence alone does not make a missing attendance clock complete.

---

## 11. Payroll web structure

Top-level navigation adds **Payroll**. Existing pages remain available.

Route: `/admin/talentops/payroll`.

Payroll is mobile-friendly and follows current TalentOps visual patterns. Indonesian labels should be short and operational.

Recommended internal views, without creating many top-level app menu items:

- `Ringkasan` — default status + work queues.
- `Review` — pending submissions/bulk approve.
- `Kontak & WhatsApp` — technical mapping/control.
- `Pengaturan` — reminder policy/destination/session controls.

On narrow screens these become compact segmented navigation or drawers; core summary and review remain usable without horizontal desktop-only tables.

Payroll must load independently from Command Center/BAST report so a BAST report failure does not block attendance closing operations.

---

## 12. Contacts & WhatsApp mapping

This is an operational control surface, not a second identity database.

### 12.1 WhatsApp discovery

Use the active `whatsapp-web-session` runtime to expose authenticated discovery data:

- joined group JID.
- group subject/display name.
- group participants/member JIDs available from the runtime.
- own account identity / transport readiness.

Discovery does not automatically authorize a group for inbound or outbound use.

### 12.2 Mapping screen

`Payroll > Kontak & WhatsApp` shows three practical sections:

**Talent mapping**

```text
Talent / NRP        Role       WhatsApp              Mapping
Andi / 12345        Developer  62812...@c.us         Terhubung
Budi / 12346        Developer  —                     Belum dipetakan
Citra / 12347       IoT        19293...@lid          Perlu verifikasi
```

**PMO / PIC mapping**

```text
Scope / Role        PIC         WhatsApp              Active
Developer           Fitria      ...@c.us              Yes
IoT                  Lenggo      ...@c.us              Yes
```

**Groups**

```text
Group                     Members   Use as
Payroll Operation          14        [Closing digest]
Celerates Internal         87        [Not allowed]
```

Selecting a group stores stable group JID. Renaming a group does not break routing.

### 12.3 Matching rules

Automatic matching may reuse existing verified JID bindings. It must **not** guess identity from display name/group member name alone.

Group participants can use `@c.us`, `@lid`, or other provider identities depending on WhatsApp behavior. A participant that cannot be unambiguously correlated to an existing Talent/PMO identity is displayed as `Belum dipetakan` and manually bound by an authorized admin.

Manual binding selects an existing Talent NRP or workflow operator. It stores a reference to the canonical identity, not another free-text phonebook record.

### 12.4 Allowed groups

A discovered group has lifecycle:

```text
discovered -> selected by admin -> validated -> configured/allowed
```

Only configured groups may receive scheduled closing digests or invoke allowed group workflows. Arbitrary `@g.us` input is rejected.

---

## 13. Settings UI

Do not build a visual workflow designer.

Keep a typed form with preview.

Required settings:

```text
Payroll cycle
- closing day
- evaluation/final assessment time
- shift grace

Talent reminder
- enabled
- H-5 / H-3 / H-1
- reminder hour
- target roles/audience

Delivery
- quiet hours
- pacing
- bounded retry/backoff
- campaign pause/resume

PMO
- PIC mapping
- closing digest group

WhatsApp
- readiness/recovery status
- reconnect preserving session
- pairing only when required
```

Settings have version, actor/time audit, desired/applied version and preview with real dates/estimated recipients.

Secrets, bridge tokens, auth filesystem paths and arbitrary commands are never editable from browser forms.

---

## 14. Delivery reliability

Existing `talentops_followups` becomes the authoritative logical-delivery ledger.

Required logical states should distinguish at least:

```text
RESERVED
SENDING
SENT
FAILED_RETRYABLE
FAILED_FINAL
UNKNOWN
```

`UNKNOWN` is not blindly retried.

Reserve a logical delivery atomically before outbound. The key includes scope, cycle, milestone and canonical recipient.

The JS gateway may persist bounded request/receipt information for provider-side recovery, but it is not a second business truth for reminder eligibility.

Exactly-once delivery is not promised.

---

## 15. WhatsApp session reliability

Keep current `whatsapp-web.js` + `LocalAuth` + persistent volume architecture.

Add bounded in-process supervision, not a new microservice:

- actual client state probe.
- browser/page liveness.
- messaging readiness separate from HTTP liveness.
- bounded controlled reinitialize using the same auth profile.
- persistent recovery budget/cooldown.
- single-owner guard before Chromium stale-lock cleanup.
- stop on true logout/revocation/operator-required state.

When WhatsApp is unavailable, Payroll read/review/export must continue working. Reminder dispatch pauses and remains visible as pending/paused.

---

## 16. Export

Payroll web calls the existing attendance export path and preserves the existing legacy CSV contract.

Do not redesign CSV schema, delimiter, CRLF, date format, role mapping or approved-correction projection as part of this work.

Export remains allowed even when outstanding cases remain, with an honest outstanding summary shown before/after export.

---

## 17. Small-commit execution protocol

Every implementation commit must be small, reviewable and leave the branch in a coherent state.

After each commit, update **Section 18** in this document with:

- status.
- resulting commit SHA.
- actual files changed.
- targeted tests run and result.
- discovered implementation notes.
- next card.

A new chat/session should use this protocol:

1. Fetch `chore/session-20260918-fixes`.
2. Read this document.
3. Compare current HEAD with the latest `DONE` SHA in Section 18.
4. Inspect uncommitted/parallel changes before editing.
5. Continue the first `TODO` item whose dependencies are `DONE`.
6. Run the card's targeted tests.
7. Commit only that card.
8. Update this document/checkpoint in the same card or immediately following docs-only checkpoint commit if necessary.

Do not bundle unrelated cleanup.

---

## 18. Commit plan / execution ledger

Legend: `TODO`, `IN PROGRESS`, `DONE`, `BLOCKED`.

### Phase A — deterministic foundation

#### P00 — Master plan checkpoint

Status: `DONE`  
Commit: `43d59f9637f50e28afeec7ae786229f9a5390a64`  
Files: `docs/payroll-attendance-implementation-plan.md`.  
Test: docs-only; no runtime test required.  
Result: canonical product/workflow/implementation plan committed.

#### P01 — Payroll cycle helper

Status: `DONE`  
Commits: `6ea282a48c05e086ce1193a4c683a93f6b2b33e6`, `3ca8e9f5adb4b222ae95bde0ea276f29b5f097fa`.  
Files: `src/digital_bast/application/attendance_closing_policy.py`, `tests/unit/application/test_attendance_closing_policy.py`.  
Scope delivered: 21–20 cycles, label by ending month, H-5/H-3/H-1, February/year boundaries, `evaluated_through` helper contract.  
Notes: no DB/UI changes; existing BAST calendar behavior remains independent.

#### P02 — Closing projection model

Status: `DONE`  
Commits: `038a2398ae39acd5bf47f0a74b2b3981b889b647`, `d509a53d02ae22755d4280c1ac25da15f12ccc04`, `7bbbb30f6746e3c13ad997fe3067935d5e646188`, `263618fb44b634d0b69b7308137975e13177f2d4`, `22c8bd20b62ec898f57e6b6ae050777b99fd4df7`.  
Files: `src/digital_bast/application/attendance_closing.py`, `tests/unit/application/test_attendance_closing.py`.  
Targeted test: `PYTHONPATH=. pytest -q` against the isolated P02 projection fixture -> `12 passed`.  
Scope delivered: deterministic per-day/per-Talent `NEEDS_TALENT_ACTION`, `WAITING_SUBMITTED`, `COMPLETE`; `evaluated_through` filtering; evidence-only cannot complete; partial coverage stays actionable; rejected correction returns actionable; OFF is valid only with an available source; missing/unavailable/empty source fails closed; unresolved action has precedence over waiting rows.  
Implementation note: P02 consumes normalized correction/schedule/source facts and deliberately does not mutate or duplicate the existing correction lifecycle. Source-specific reader/API wiring is deferred to P03.  
Validation note: source imports were aligned with strict type-only import rules. Full repository CI is not claimed here because this branch has no open PR and the workflow runs on `main`/PR gates.

#### P03 — Payroll read API

Status: `DONE`  
Commits: `9566fdda8472e28e8a1779c0bd1a84a11d78cd34`, `60e250a63490d25f8e959e688fe96d1a044c02ff`, `6726a2fa7a38bb321f35a5125653447ee1aa6cce`, `dd71fcfc147954f2799b0fbf519775b4d838eddc`, `6cf6de6396400d6c46b2a70a424f70acb70a65ac`, `5a69dbef93717f244868cc4950470278f862fda9`, `94ebbedc42ab4ba5ac91353fc75868b6ed104568`, `ef489e04a4614d1ceac9efdd0263cd2fb4d73d1b`, `ca6b11119fc75cf14abe3854993a9281e13ea38f`, `9318f3513f93d3d9ce06ee941bb51c9eaf1de33d`, `386c552862b3dd3bb3333cac75aa20c81bcd9e7b`, `0f891ca53dd866aac569635009ddac34a0b82e38`, `2e2f07a38d975a604d4934165096ed3cefdfa725`, `985489a6d663703ee75ed2134dc03abb51020cdc`, `aee5cd19dde7b9b8c294ef270adbc40f8d8252e0`, `9dd36d998549f03f5654e202754fbfdead1dac3c`.  
Files: `src/digital_bast/application/attendance_closing.py`, `src/digital_bast/application/payroll_read.py`, `src/digital_bast/infrastructure/payroll_attendance.py`, `src/digital_bast/web/payroll_contracts.py`, `src/digital_bast/web/payroll_router.py`, `src/digital_bast/web/dependencies.py`, `src/digital_bast/web/app.py`, `src/digital_bast/web/production.py`, `tests/unit/application/test_attendance_closing.py`, `tests/unit/application/test_payroll_read.py`, `tests/unit/web/test_payroll_routes.py`.  
Scope delivered: current/history cycle API, read-only Payroll overview summary, per-Talent rows, day detail, bulk attendance/correction/evidence reader, production DI, and API registration independent from Command Center/BAST report loading.  
Source semantics: canonical employee ID remains text; missing source has no fabricated attendance ID; approved correction wins over pending/rejected history to match legacy export; pending produces WAITING only when it covers the current raw gap; raw complete supersedes historical request state; `evidence_note` and uploaded attendance evidence both count as supporting evidence.  
OFF/source rule: Developer holiday/weekend follows existing resolver; IoT missing schedule + missing timesheet is treated as unverified rather than silently OFF; source-unavailable rows are fail-closed and explicitly `talent_action_required=false`, so they are not eligible reminder work.  
Evaluation rule: P03 uses a conservative next-day `06:00 Asia/Jakarta` read boundary until configurable final-assessment/shift-grace settings land in P23.  
Targeted validation: sandbox contract runtime tests -> application service `2 passed`; FastAPI router scenario suite `1 passed` covering current 21–20 cycle, overview without BAST report backend, Talent detail, 422 partial cycle selector, and 404 unknown Talent. Repository-local full `pytest/ruff/basedpyright` was not runnable in the tool container because external DNS/package checkout is unavailable. CI configuration confirms full quality gate runs on PR or push to `main`, so full CI is intentionally not claimed at this branch-only checkpoint.  
No migration or write path was added in P03.

### Phase B — Payroll UI shell

#### P04 — Payroll route independent bootstrap

Status: `DONE`  
Commits: `4f05ab3d66f0bb1fbf2fc6311a4d49c66c01f2ae`, `c9f0cd911e234dd1c1a27cd7a37b22779263483a`, `57ed058e03c023a9dfe6c463ce153cc1cbb0387b`, `727811558378d003786022a9e5d354eeecddaf7c`, `4184425f56bd20ad51b68a79474419b84509e1dc`, `d5357515d073c17c7cad7b43203a1e348fd4ee84`.  
Files: `frontend/src/api/payroll.ts`, `frontend/src/api/payroll.test.ts`, `frontend/src/app/App.tsx`, `frontend/src/app/App.test.tsx`, `frontend/src/components/WorkspaceFrame.tsx`.  
Scope delivered: typed Payroll API client, `/admin/talentops/payroll` route, top-level Payroll navigation entry, direct session + Payroll overview bootstrap without mandatory `getCommandCenter()`, independent Payroll error/loading state, and coherent SPA navigation back to existing monthly pages.  
Direct-refresh note: existing FastAPI `talentops_page_router` already has `/admin/talentops/{_path:path}` wildcard, so no backend page-route change is required for direct `/admin/talentops/payroll` refresh.  
Regression lock: frontend test explicitly asserts direct Payroll bootstrap calls `getPayrollOverview(2026, 9)` while `getCommandCenter()` is not called; API client tests lock cycle/overview/detail URLs including encoded employee IDs.  
Validation note: repository-local `npm test` / `npm run typecheck` could not execute in the tool container because external DNS prevents GitHub/npm checkout. No passing frontend runner result is claimed. Full frontend build/typecheck remains part of the container/PR CI gate.  
UI boundary: P04 intentionally renders only a read-only Payroll shell proving route/data independence. Operational summary, review/follow-up cards, filters and Talent list are P05.

#### P05 — Payroll mobile-friendly summary

Status: `TODO`  
Files: new `PayrollPage.tsx` + current style system/tests.  
Scope: cycle header, evaluated-through, 3 business counts, Review Queue card, Talent Follow-up card, searchable Talent table/list.

#### P06 — Payroll day detail drawer

Status: `TODO`  
Scope: actual/proposed/evidence/status/reason detail, read-only first. Mobile-friendly.

### Phase C — reminder-first Talent flow

#### P07 — Stable reminder context schema

Status: `TODO`  
Scope: additive `bot_conversations` context/snapshot fields + repository/service tests. Store attendance keys, cycle/context identity and expiry. Do not yet change sending behavior.

#### P08 — Reminder message composer

Status: `TODO`  
Scope: compose concise reminder from Closing Projection. Only current action. Maximal simplicity: `[Lengkapi] [Nanti]` + text fallback.

#### P09 — Reminder -> current gap routing

Status: `TODO`  
Scope: `dm_entry.py` / workflow routing reads stable context and immediately opens first actionable gap. No Mobile redirect in happy path.

#### P10 — Time-first correction draft

Status: `TODO`  
Scope: allow draft from selected date before evidence; collect only missing explicit fields. Reuse existing resolution service.

#### P11 — Evidence in active attendance draft

Status: `TODO`  
Scope: incoming media while draft is active is actually persisted and attached; no lost attachment; image formats first.

#### P12 — PDF attendance evidence

Status: `TODO`  
Scope: additive DB constraint/content validation + review/download support + tests.

#### P13 — Submit -> next gap loop

Status: `TODO`  
Scope: review summary, submit once, return WAITING, offer `[Lanjut] [Selesai dulu]`; finish without menu.

#### P14 — Progressive same-gap shortcut

Status: `TODO`  
Scope: only when multiple actionable dates share a missing field, offer `Sama/Berbeda`. Do not introduce a large bulk menu.

### Phase D — PMO review operations

#### P15 — Review queue API

Status: `TODO`  
Scope: query pending attendance requests grouped for Payroll, preserving existing approval authority.

#### P16 — Review queue UI

Status: `TODO`  
Scope: compact rows grouped by type, selection, open exception detail.

#### P17 — Bulk approve service/API

Status: `TODO`  
Scope: revalidate each item; use existing decide service; partial success; no raw attendance mutation.

#### P18 — Bulk approve UI + rejection reasons

Status: `TODO`  
Scope: confirmation summary, approve selected, structured reject reason, truthful partial result.

### Phase E — Contacts & WhatsApp mapping

#### P19 — WhatsApp group/member discovery endpoint

Status: `TODO`  
Scope: extend active `whatsapp-web-session` status/control contract to return groups and available participant identities through authenticated internal endpoint. No arbitrary group send yet.

#### P20 — Identity/mapping API

Status: `TODO`  
Scope: merge discovered participants with existing Talent/PMO identity bindings; classify `Terhubung / Belum dipetakan / Perlu verifikasi`; no display-name auto-authority.

#### P21 — Contacts & WhatsApp Payroll UI

Status: `TODO`  
Scope: Talent mapping, PMO/PIC mapping, group list/member drill-down, manual bind/unbind using canonical existing entities.

#### P22 — Allowed closing group destination

Status: `TODO`  
Scope: persisted configured group JID + server-side allowlist validation; direct JID behavior unchanged.

### Phase F — settings and reminder automation

#### P23 — Closing settings migration/control model

Status: `TODO`  
Scope: additive fields for enabled, closing day, milestone mode/offsets, final assessment/grace, pause, version/audit. Preserve legacy reminder-day semantics.

#### P24 — Reminder settings UI + preview

Status: `TODO`  
Scope: typed compact form, real date preview, audience estimate, desired/applied version.

#### P25 — Durable logical delivery reservation

Status: `TODO`  
Scope: atomic reserve/claim and delivery states in existing follow-up ledger. Failure-injection unit tests.

#### P26 — Scheduled Talent reminder cutover

Status: `TODO`  
Scope: existing Prefect cadence uses closing policy + closing projection. Disable duplicate closing reminder path for same audience. Skip waiting/complete/unbound correctly.

#### P27 — Correlated response tracking

Status: `TODO`  
Scope: response timestamp/kind tied to reminder/context. Only attendance action counts as response.

### Phase G — PMO digest

#### P28 — Closing digest projection

Status: `TODO`  
Scope: complete/waiting/needs-action + actual successful reminder send counts + unresponded using correlation.

#### P29 — Group digest outbound

Status: `TODO`  
Scope: one configured group digest per scope/cycle/milestone. No per-Talent PMO message.

#### P30 — Payroll Follow-up panel live actions

Status: `TODO`  
Scope: preview reminder, manual send, delivery/skipped reasons in web.

### Phase H — WhatsApp operational reliability

#### P31 — Durable gateway request receipt

Status: `TODO`  
Scope: bounded durable request/receipt persistence for gateway recovery; request-id conflict handling remains strict.

#### P32 — Session supervisor core

Status: `TODO`  
Scope: readiness probe, transient recovery ladder, persistent budget/cooldown, no routine logout/reset.

#### P33 — Single-owner/auth safety

Status: `TODO`  
Scope: explicit owner guard before Chromium Singleton cleanup; disk/inode/auth-store safety.

#### P34 — Extended WhatsApp status API

Status: `TODO`  
Scope: alive vs ready, recovery state/reason, last probe/ack, operator-action required, applied policy version.

#### P35 — Payroll WhatsApp operations UI

Status: `TODO`  
Scope: compact `Terhubung / Sedang pulih / Perlu tindakan`; pause/resume/reconnect; admin-only pairing when required.

### Phase I — intelligence and export integration

#### P36 — Natural Talent attendance interpretation

Status: `TODO`  
Scope: context-aware date/missing-clock extraction; deterministic fallback always works; message timestamp passed for relative dates.

#### P37 — PMO closing queries

Status: `TODO`  
Scope: closing status/outstanding/unresponded + role filters. Backend supplies facts; LLM only interprets/summarizes.

#### P38 — Payroll export action/history

Status: `TODO`  
Scope: call existing legacy attendance export, explicit cycle/role, history metadata only. No CSV contract change.

### Phase J — final verification

#### P39 — Cross-surface integration tests

Status: `TODO`  
Scope: closing projection consistency across web/reminder/review/export fixtures.

#### P40 — WhatsApp integration/failure tests

Status: `TODO`  
Scope: gateway -> worker digit/context precedence, media, retry, restart, unknown delivery, group allowlist, recovery.

#### P41 — Frontend responsive regression

Status: `TODO`  
Scope: Payroll desktop/mobile, review selection, mapping/settings drawers, old pages unchanged.

#### P42 — Full local E2E scenario

Status: `TODO`  
Use fake clock, fake outbound and local fixtures. Cover H-5 -> Talent correction/evidence -> PMO review -> approve/reject -> next reminder -> H-1 digest -> export.

#### P43 — Manual functional acceptance checklist

Status: `TODO`  
Prepare a short manual checklist for user validation against staging/test WhatsApp. Include exact expected messages and web states.

#### P44 — Soak / production enablement gate

Status: `TODO`  
Scope: test account observation, recovery injection, queue behavior, then explicitly enable proactive closing reminders. No automation is production-enabled merely because code was deployed.

---

## 19. End-to-end acceptance scenario

Use fake clock and fake outbound first.

1. Payroll September = 21 Aug–20 Sep.
2. Talent A has 4 Sep missing-out and 7 Sep missing-in.
3. Talent B attendance complete but task/BAST blocker exists: no payroll attendance reminder.
4. Talent C has only pending attendance correction: no Talent reminder.
5. H-5 sends one concise reminder only to A.
6. A chooses `Lengkapi`; bot asks only 4 Sep clock-out.
7. A answers `17.40`, sends screenshot evidence, reviews and submits.
8. 4 Sep becomes WAITING; 7 Sep remains NEEDS ACTION.
9. PMO Payroll summary changes and Review Queue shows 4 Sep without receiving an individual WA alert.
10. PMO approves 4 Sep from Payroll. Projection becomes COMPLETE for that day; raw attendance remains unchanged; existing CSV sees approved correction.
11. A completes 7 Sep. H-3 sends nothing when no Talent action remains, even if review is still pending.
12. PMO bulk-approves several normal requests; one stale/changed request is reported separately without failing the others.
13. PMO H-3 group digest contains counts and review workload, not per-Talent messages.
14. Network interruption pauses sends; Payroll web still works; recovery rechecks current action before continuing.
15. Final export uses existing CSV format and explicit 21–20 cycle.

---

## 20. Manual functional test checklist to prepare at the end

The final user-facing test sheet should cover at least:

- cycle 21–20 and evaluated-through behavior.
- reminder H-5/H-3/H-1.
- no reminder for complete/waiting Talent.
- one-gap clock-out flow.
- one-gap clock-in flow.
- evidence upload and duplicate evidence.
- PDF after P12.
- submit -> waiting wording.
- next-gap continuation.
- same-field shortcut.
- rejection -> Talent re-action.
- PMO summary counts.
- review queue and exception detail.
- bulk approve partial success.
- no PMO per-submission WhatsApp spam.
- group discovery/member listing.
- manual Talent/PMO mapping.
- group allowlist rejection.
- settings preview and applied version.
- WhatsApp offline/recovery/pairing behavior.
- existing legacy pages regression.
- legacy CSV byte/schema behavior.

---

## 21. Things that must not happen

- Do not create a stored `payroll_ready` truth flag.
- Do not auto-approve Talent corrections.
- Do not mutate raw attendance to simulate correction.
- Do not require Talent Mobile for the normal closing path.
- Do not send PMO one WA message per Talent submission.
- Do not infer identity from WhatsApp display name alone.
- Do not allow arbitrary group JID from browser/user input.
- Do not reinterpret legacy calendar reminder arrays as closing offsets silently.
- Do not replace `whatsapp-web.js`/LocalAuth as part of this implementation.
- Do not promise anti-ban, exactly-once delivery or zero re-pairing.
- Do not change the existing payroll CSV contract.
- Do not delete existing TalentOps tabs during this implementation.

---

## 22. Current checkpoint

Implementation is complete through **P04 — Payroll route independent bootstrap**.

Current implementation HEAD before this docs-only checkpoint: `d5357515d073c17c7cad7b43203a1e348fd4ee84`.

P04 adds the typed frontend Payroll API client, a discoverable `/admin/talentops/payroll` SPA route, and a route-aware bootstrap that loads session + Payroll overview without calling Command Center. Existing FastAPI wildcard routing already supports direct refresh of the client route.

Regression tests were added for independent Payroll bootstrap and API URL contracts. Repository-local `npm test` and `npm run typecheck` could not run in the tool container because external DNS prevents GitHub/npm checkout, so no frontend runner result is claimed at this checkpoint.

The next implementation card is **P05 — Payroll mobile-friendly summary**. It should replace the temporary read-only shell with the real operational summary, Review Queue/Talent Follow-up cards, filters/search and mobile-friendly Talent list while continuing to consume the P03/P04 read-only contracts.
