# Payroll Attendance — Current Execution Checkpoint

This is the small rolling execution checkpoint for
`docs/payroll-attendance-implementation-plan.md`.

Repository: `yosdwi/celerates-bast-digital`  
Branch: `chore/session-20260918-fixes`  
Checkpoint date: 19 September 2026

## Completed through P07

P00–P06 remain completed as recorded in the master implementation plan.

### P07 — Stable reminder context schema

Status: `DONE`

Commits:

- `29bc1e2fd263f78703b067ce43dcad915a4dd00b` — additive DB schema.
- `b1d817abca44f31bae522fec7d11cc3003623229` — typed durable context service.
- `e21f521c60d1ed5a57354d6ab8c483024ca5c8be` — initial context tests.
- `019626df38253df52c82ac91f068c8985d34b2e8` — strict JSON parsing hardening.
- `4be5fd809f72c0043affda50647461861a60b9d6` — final-service-aligned test fakes.

Files:

- `migrations/versions/20260919_0022_attendance_reminder_context.py`
- `src/digital_bast/bot/attendance_context.py`
- `tests/unit/bot/test_attendance_context.py`

Delivered contract:

- Stable reminder snapshot is separate from legacy `bot_conversations.updated_at`
  and existing `talent_context_*` navigation state.
- Snapshot stores `context_id`, schema `version`, canonical `employee_id`, immutable
  Payroll `cycle_id`, exact ordered attendance keys, and absolute `expires_at`.
- JSONB is used only to preserve ordered attendance identities. It does not store
  Payroll status/readiness/business decisions.
- User-visible numbering is 1-based and resolves only against the persisted
  snapshot. If item 1 changes elsewhere, reply `2` still resolves to the exact
  attendance identity originally sent as item 2.
- Empty, duplicate, oversized, malformed or corrupt key snapshots fail closed.
- Expired context loads as no active context.
- Saving/clearing attendance context does not mutate `talent_context_*`, pending
  task/image state, or the legacy conversation `updated_at` TTL.
- P07 adds no reminder dispatch, DM routing or attendance mutation behavior.

Migration chain:

`20260911_0021 -> 20260919_0022`

Validation evidence:

- Branch diff from P06 contains only the migration, context service and its tests.
- Unit tests cover stable ordering, invalid/duplicate identities, timezone-aware
  expiry, expired/corrupt fail-closed behavior, save isolation and clear isolation.
- Full repository `pytest + ruff + basedpyright` is not claimed in this tool
  environment because the runtime does not have the repository dependency set
  (`psycopg` is unavailable) and branch CI is not automatically triggered here.
  PR/main CI remains the complete quality gate.

## Next card

**P08 — Reminder message composer**

Scope remains locked:

- Compose one concise Payroll attendance reminder from current Closing Projection.
- Include only current `NEEDS_TALENT_ACTION` items.
- Persist the P07 stable snapshot before/with dispatch orchestration when P08 is
  wired; P08 must not recompute numbering after the message is sent.
- Message stays simple: gap summary plus `[Lengkapi] [Nanti]` with numeric/text
  fallback.
- Do not route replies yet; direct reminder-to-gap routing remains P09.
- Do not change legacy BAST monthly reminder semantics.

For a new session: read the master implementation plan first, then this checkpoint,
verify branch HEAD, and continue P08 without redesigning locked requirements.
