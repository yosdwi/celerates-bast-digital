# Payroll Attendance — Current Execution Checkpoint

This is the rolling execution checkpoint for
`docs/payroll-attendance-implementation-plan.md`.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`  
Checkpoint date: 19 September 2026

## Execution standard

This project follows `docs/development-execution-standard.md`.

Cards remain audit/commit boundaries, but implementation proceeds by end-to-end
waves. Keep changes small and reversible, preserve source-of-truth boundaries, and
checkpoint only after integration/validation review. The canonical Payroll plan
remains authoritative; this file records the latest execution state.

## Completed through P22

P00–P14 remain completed as recorded in the canonical implementation plan and
prior checkpoint history. P15–P18 delivered the PMO Payroll review queue, evidence
inspection, per-item revalidation, bulk approve/reject with partial success, and
rejection back into the existing Talent correction lifecycle.

The Contacts & WhatsApp Mapping wave P19–P22 is now implemented and checkpointed.

---

## Wave 4 — Contacts & WhatsApp Mapping (P19–P22)

Status: `DONE`

Baseline before this wave:

- `63b210f83e7987af2d3815b13cfb28b1c376dd33`

Pre-checkpoint implementation head:

- `0703ddd9c8c94414bc8bb523fdf65e99a675dcab`

The compare from the P18 baseline to the pre-checkpoint head is 20 commits ahead,
0 behind, and limited to the WhatsApp discovery/directory/mapping/settings UI,
additive closing-group migration, and focused tests. No attendance truth, CSV, BAST,
review authority, scheduler, or transport migration was introduced by this wave.

### P19 — Group/member discovery

Delivered:

- Reused the active `whatsapp-web-session` / `whatsapp-web.js` runtime instead of
  introducing another WhatsApp provider or discovery service.
- Added authenticated read-only bridge endpoint:
  `GET /internal/v1/groups` using the existing `x-bridge-token` boundary.
- Discovery returns real joined group facts available from the runtime:
  - group JID,
  - subject,
  - member count,
  - participant JID,
  - admin/super-admin flags,
  - contact display name, number, and `is_my_contact` only when the current session
    can actually resolve those fields.
- Participant identities are preserved as provider identities such as `@c.us` or
  `@lid`; the system never infers an employee from a display name.
- If contact metadata is unavailable, raw JID remains visible rather than being
  guessed or hidden.
- Discovery does not authorize a group for sending, does not change pairing, and
  does not alter the existing direct-message outbound contract.

Typed gateway additions in
`src/digital_bast/infrastructure/whatsapp_outbound.py`:

- `WhatsAppGroupParticipant`
- `WhatsAppGroup`
- `WhatsAppGroupDirectory`
- `BotBridgeWhatsAppOutboundGateway.get_groups()`

The gateway fails closed to `ready=false / connection=unavailable` on bridge or
response failure.

### P20 — Identity/mapping API

Delivered:

- Reused existing `wa_identity` as the sole durable Talent↔WhatsApp authority.
  No second Talent phonebook/mapping table was created.
- Kept PMO/operator WhatsApp identity separate in the existing
  `wa_operator_identity`; this wave does not conflate Talent and operator identity.
- Added `src/digital_bast/infrastructure/whatsapp_directory.py` and
  `src/digital_bast/web/whatsapp_directory_router.py`.
- Added API under `/api/talentops/v1/whatsapp-directory` to expose live discovery
  joined with canonical active Talent rows and existing durable mappings.
- Exact JID matching is the only automatic correlation rule.
- Admin mapping mutation accepts only direct `@c.us` / `@lid` identities.
- Mapping is fail-closed:
  - an employee already bound to a different JID is not silently changed,
  - a JID already bound to another employee is not silently reassigned,
  - operator must explicitly unlink before deliberate reassignment.
- CSRF and owner/admin authorization are required for mutations.
- PMO can inspect mapping state but cannot mutate it.

Primary bind outcomes remain explicit:

- `bound`
- `unchanged`
- `invalid_jid`
- `employee_not_found`
- `employee_already_bound`
- `jid_already_bound`

### P21 — Contacts & WhatsApp UI

Delivered:

- Added an operational **Contacts & WhatsApp** control surface in existing
  TalentOps Settings rather than creating another application/address book.
- Main component:
  `frontend/src/components/WhatsAppDirectorySettings.tsx`.
- UI can:
  - refresh the current WhatsApp discovery snapshot,
  - show bridge/session readiness,
  - inspect discovered groups and participant identities,
  - show real contact display metadata when available,
  - show raw provider JID when metadata is unavailable,
  - distinguish mapped and unmapped Talent identities,
  - explicitly bind/unbind a Talent where authorized,
  - select the configured Payroll closing group.
- The UI does not perform display-name fuzzy matching or automatic reassignment.
- Supporting API types/client and isolated responsive styling were added without
  changing existing Payroll summary/review behavior.

### P22 — Allowed Payroll closing group

Delivered:

- Added migration `20260919_0023_payroll_closing_group` on top of `0022`.
- Extended existing `workflow_notification_settings` with one additive field:
  `payroll_closing_group_jid`.
- Added a DB constraint requiring a valid WhatsApp group JID form ending in
  `@g.us` when configured.
- Group selection is stored by stable JID, so a group rename does not become the
  routing authority.
- When the bridge is ready, a newly selected group must exist in the current live
  discovery snapshot; arbitrary ready-state `@g.us` input is rejected.
- If WhatsApp is temporarily unavailable, a syntactically valid configured group
  can remain/still be stored but is returned as `verified=false`; no false runtime
  verification is invented.
- Closing-group configuration is context only. It does not change Payroll closing
  status, attendance approval state, or any raw attendance data.
- Scheduled/group outbound is deliberately **not** enabled here; PMO group digest
  sending remains a later card.

### Main implementation files

Bridge/backend:

- `whatsapp-web-session/server.js`
- `src/digital_bast/infrastructure/whatsapp_outbound.py`
- `src/digital_bast/infrastructure/whatsapp_directory.py`
- `src/digital_bast/web/whatsapp_directory_router.py`
- `src/digital_bast/web/app.py`
- `migrations/versions/20260919_0023_payroll_closing_group.py`
- `tests/unit/infrastructure/test_whatsapp_outbound.py`
- `tests/unit/web/test_whatsapp_directory_routes.py`

Frontend:

- `frontend/src/components/WhatsAppDirectorySettings.tsx`
- `frontend/src/components/WhatsAppDirectorySettings.test.tsx`
- `frontend/src/pages/SettingsPage.tsx`
- `frontend/src/styles/whatsapp-directory.css`
- `frontend/src/main.tsx`
- existing TalentOps API client/types extended for directory/mapping/group contracts.

### Focused hardening commits near wave close

- `5ab8321cd4ca4e9980ffa466f9a3b1b9dc9a4211` — enrich real discovered contact metadata.
- `4ff901b72b737b169c0c0c297a8fe2a85e23a0dc` — expose contact metadata through the typed web contract.
- `1350f516aab44f5912f329c0a9f7e821775c0772` — group-directory gateway regression coverage.
- `3abcb330700d72be17fbc2ab312a3bf4f9924852` — Contacts & WhatsApp UI action coverage.
- `e8ca7e049475ccf3b82b2da5d9944f300886cce9` — directory infrastructure lint hardening.
- `6053502a08591fa8cdef0b75fd5de827dee3c711` — group-directory gateway lint hardening.
- `202d9f5666af9b1e26578c6b6486878f1b6ebebc` — directory router lint hardening.
- `0703ddd9c8c94414bc8bb523fdf65e99a675dcab` — route-test lint cleanup.

### Validation truth

Latest validation PR #73 CI run `#493` / `35451732109` on pre-checkpoint head
`0703ddd9...`:

- `uv sync --all-groups`: **PASS**.
- `uv run python -m compileall -q src tests`: **PASS**.
- `migration-smoke`: **PASS**.
  - migration gate: PASS,
  - migration idempotency gate: PASS,
  - smoke/shadow gate: PASS.
- `gitleaks`: **PASS**.
- repository-wide `uv run ruff check .`: **FAIL**, reporting 109 findings from
  earlier Payroll cards and unrelated legacy/BAST/infrastructure code.
- After the P19–P22 lint cleanup, none of these current-wave Python files appears
  in the Ruff failure list:
  - `src/digital_bast/infrastructure/whatsapp_directory.py`
  - `src/digital_bast/infrastructure/whatsapp_outbound.py`
  - `src/digital_bast/web/whatsapp_directory_router.py`
  - `tests/unit/web/test_whatsapp_directory_routes.py`
- Because repository-wide Ruff fails first, the quality job does **not** reach
  `basedpyright`, `pytest`, or `scripts/check-ops.sh`; a full green quality job is
  therefore not claimed.
- Frontend component tests were added, but the current repository CI workflow does
  not run the frontend npm test/typecheck suite. Their execution is not claimed.
- Container job failure is infrastructure/setup-only: GitHub Actions cannot resolve
  `aquasecurity/trivy-action@0.30.0`; the job fails before checkout/build and does
  not execute application code.

PR #73 exists only as a CI validation trigger for the long-lived working branch.
It is **not** a merge/release candidate and must not be merged into `main`.

### Wave acceptance result

The implemented contract now supports:

```text
Existing WhatsApp session
  -> discover real joined groups + participant provider identities
  -> expose real contact metadata when available
  -> inspect mapped / unmapped Talent identities
  -> explicitly bind / unbind against existing wa_identity
  -> select one stable Payroll closing-group JID
```

without changing the active WA transport, guessing identity from names, sending a
closing-group message, or changing Payroll/attendance truth.

---

## Next execution wave — Reminder Automation Foundations (P23–P27)

Execute P23–P27 continuously as one integration wave unless an implementation
finding creates a genuine source-of-truth conflict.

### P23 — Closing settings migration/control model

Status: `TODO`

Add typed, additive closing configuration for enabled state, closing day,
milestone mode/offsets, final assessment/shift grace, pause state, and version/audit.
Preserve legacy reminder-day semantics during migration/cutover.

### P24 — Reminder settings UI + preview

Status: `TODO`

Add a compact typed form with real Payroll cycle/milestone date preview, estimated
audience, and desired/applied version visibility. Do not create a workflow designer.

### P25 — Durable logical delivery reservation

Status: `TODO`

Use the existing follow-up ledger as the authoritative logical-delivery state.
Add atomic reserve/claim and delivery lifecycle such as RESERVED/SENDING/SENT/
FAILED_RETRYABLE/FAILED_FINAL/UNKNOWN, with failure-injection coverage. `UNKNOWN`
must never be blindly resent.

### P26 — Scheduled Talent reminder cutover

Status: `TODO`

Keep the existing Prefect cadence, but evaluate the new closing policy against the
canonical Closing Projection. Only current `NEEDS_TALENT_ACTION` recipients are
eligible; WAITING/COMPLETE/unbound cases must be skipped truthfully. Disable the
duplicate legacy closing-reminder path for the same audience when cutover occurs.

### P27 — Correlated response tracking

Status: `TODO`

Record response timestamp/kind against the specific reminder/context. Only a
subsequent attendance interaction counts as a response; generic conversation
`updated_at` is not sufficient for `unresponded` logic.

### Continuation instructions

For a new session:

1. Read `docs/development-execution-standard.md`.
2. Read `docs/payroll-attendance-implementation-plan.md`.
3. Read this rolling checkpoint.
4. Verify branch HEAD and inspect any commits after this checkpoint before editing.
5. Continue with the full P23–P27 wave without redesigning the locked Payroll or
   WhatsApp source-of-truth boundaries.
