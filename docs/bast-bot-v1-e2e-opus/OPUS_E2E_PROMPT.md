# CLAUDE CODE OPUS — END-TO-END IMPLEMENTATION PROMPT

You are implementing **BAST Bot V1 end-to-end** in the existing repository:

`yosdwi/celerates-bast-digital`

Do the work directly in the current repository. You are allowed to inspect the entire codebase, trace runtime mappings, edit code, add tests, and integrate all V1 pieces in one execution.

Do NOT stop after planning. Implement, test, and finish the working V1 as far as the current repository/runtime allows.

---

# PRODUCT GOAL

Build a WhatsApp group bot for Digital BAST using Hermes Agent + WhatsApp Baileys/unofficial.

The bot must support manual group commands for:

1. Check BAST completion status for a date range.
2. Export attendance for a date range.
3. Generate BAST for a date range.
4. Check Docker Compose/system health status.

The same deterministic application logic must later/also be reusable by Prefect automation.

Do not over-engineer.

---

# CORE ARCHITECTURE

Use this simple model:

```text
WhatsApp Group
   ↓
Hermes Agent
   ↓
Digital BAST CLI / Application Services
   ↓
Existing DB / NocoDB / sources
```

For automation:

```text
Prefect
   ↓
same application services
```

Do NOT introduce:
- MCP
- Celery
- new message queue
- vector DB / RAG
- new dashboard
- new scheduler
- individual WhatsApp DM
- arbitrary shell execution
- Docker mutation from WhatsApp

Hermes is only:
- intent parser
- date parser
- command caller
- response formatter

Hermes must NOT determine business completion itself.

---

# DATE RANGE

Every manual business command accepts explicit inclusive date range:

```text
--start-date YYYY-MM-DD
--end-date YYYY-MM-DD
```

No hidden payroll calculation in the core command.

Examples:

Attendance:
```text
20 Jul 2026 - 20 Aug 2026
```

BAST:
```text
1 Aug 2026 - 31 Aug 2026
```

If user runs only until 18 Aug, generate only until 18 Aug.

---

# BUSINESS RULES

## 1. IoT Operations dependency

For IoT Operations:

```text
Schedule Shifting
   ↓
Attendance / Log 1 PAMA
   ↓
Timesheet
```

Important invariant:

> Timesheet may NEVER be complete if Log 1 PAMA / Attendance is incomplete.

---

## 2. Log 1 PAMA / Attendance

Log 1 PAMA uses Attendance data for selected range.

For every date:

### If Schedule = OFF / holiday
Attendance may be empty.

This is valid.

### If Schedule = working shift

Normal valid:
```text
attendance row exists
AND Clock In exists
AND Clock Out exists
```

Valid exception:
```text
attendance row exists
AND Clock In or Clock Out is missing
AND Evidence Attendance is NOT NULL / NOT EMPTY
```

This covers cuti / izin / sakit / training / similar exceptions.

We do NOT need to classify exception type in V1.

Incomplete:
```text
working shift
AND attendance row missing
```

OR:

```text
working shift
AND Clock In/Out incomplete
AND Evidence Attendance missing
```

Professional Indonesian messages, concise and actionable.

Examples:
```text
12 Agustus — Clock Out belum terisi dan Evidence Attendance belum tersedia.
14 Agustus — Data attendance belum tersedia.
```

---

## 3. Timesheet

Timesheet depends on valid Log 1 PAMA / Attendance.

### Working shift
- Log 1 PAMA for that date must be valid.
- Timesheet row must exist.

### OFF / holiday
- Attendance may be empty.
- Timesheet row must exist.
- Timesheet remarks must indicate OFF / holiday and must not be empty.

Examples:
```text
8 Agustus — Keterangan OFF pada Timesheet belum terisi.
8 Agustus — Timesheet untuk jadwal OFF belum tersedia.
```

If any date invalid:
```text
Timesheet = incomplete
```

---

## 4. Task List

For each employee within selected date range:

All Task List rows must have status:

```text
Closed
```

Normalize trim + case-insensitive.

Examples valid:
```text
Closed
closed
 CLOSED
```

If one or more are not Closed:
```text
Task List = incomplete
```

Return exact task/title details.

Example:
```text
Task "CCTV Gate 2" belum Closed.
```

If zero tasks exist:
- do NOT silently mark complete.
- return `needs_review`
- message:
```text
Belum ada Task List pada periode.
```

---

## 5. Evidence Task List

Evidence Task List is different from Evidence Attendance.

Rule:
```text
minimum 1 Task List Evidence per employee within selected range
```

Not one evidence per task.

If at least one exists:
```text
Evidence = complete
```

If none:
```text
Evidence = incomplete
```

Message:
```text
Evidence Task List belum tersedia.
```

---

# FIELD DISCOVERY RULE

Do not guess actual database/NocoDB/JSON field names.

Before implementing final adapters, inspect the repository and trace:

1. actual Attendance Evidence field/key
2. actual Task List Evidence field/key/relation
3. actual runtime producer/source of attendance rows
4. employee linkage
5. actual Task Status values

If the exact mapping is discoverable from code, use it.

If not discoverable:
- create a narrow adapter/config boundary,
- clearly document the unresolved field mapping,
- do NOT fabricate schema names,
- still complete all code that can be safely completed.

Do NOT redesign the data layer just because one mapping is unclear.

---

# EXISTING CODEBASE TO REUSE

Reuse current structure.

Important existing components include:
- `src/digital_bast/cli.py`
- `src/digital_bast/domain/models.py`
- `src/digital_bast/domain/timesheets.py`
- `src/digital_bast/domain/transforms.py`
- `src/digital_bast/infrastructure/production_sources.py`
- `src/digital_bast/infrastructure/nocodb_repository.py`
- `src/digital_bast/web/postgres_sql.py`
- `src/digital_bast/web/attendance_router.py`
- `src/digital_bast/web/report_router.py`
- `src/digital_bast/flows/deployments.py`
- `src/digital_bast/flows/pipelines.py`
- `compose.yaml`

Preserve existing CLI style:
- argparse
- `digital-bast` entrypoint
- JSON stdout where machine-readable output is needed

Do not replace CLI framework.

---

# REQUIRED CLI

Implement these commands.

## A. BAST completion status

```bash
digital-bast completion-status \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --format json
```

Optional:
```bash
--employee "Titin"
```

Output structure:

```json
{
  "start_date": "2026-08-01",
  "end_date": "2026-08-31",
  "state": "incomplete",
  "employees": [
    {
      "employee_id": "...",
      "name": "Titin",
      "timesheet": {
        "state": "incomplete",
        "issues": []
      },
      "task_list": {
        "state": "complete",
        "issues": []
      },
      "evidence": {
        "state": "complete",
        "issues": []
      },
      "log_1_pama": {
        "state": "incomplete",
        "issues": []
      }
    }
  ]
}
```

Business incompleteness is not a process error.
Command may return exit code 0 while state is incomplete.

---

## B. Attendance export

```bash
digital-bast export-attendance \
  --start-date 2026-07-20 \
  --end-date 2026-08-18 \
  --label "Attendance August 2026"
```

Reuse existing attendance export logic.

Do NOT automate browser clicks.

Preserve existing web route behavior.

---

## C. Generate BAST

```bash
digital-bast generate-bast \
  --start-date 2026-08-01 \
  --end-date 2026-08-31
```

Reuse current report/generation logic.

If a real PDF renderer already exists, use it.

If no actual PDF renderer exists:
- implement the cleanest minimal solution consistent with current dependency strategy,
- avoid over-engineering,
- prefer existing HTML/template path,
- add only a lightweight production-suitable dependency if actually required,
- document the choice.

Do NOT build a brand new reporting system.

---

## D. Docker Compose status

```bash
digital-bast system-status
```

This is host-side, read-only.

Use:

```bash
docker compose ps --all --format json
```

Use subprocess argument list.

NO:
- shell=True
- restart
- stop
- start
- kill
- exec
- rm
- compose up/down

Do not mount Docker socket into app containers.

Existing required services:
- postgres
- redis
- prefect-server
- prefect-services
- worker
- runner
- reverse-proxy

Web slot:
- at least one of `web-blue` or `web-green` must be running healthy.

Native health exists for some services.
For services without healthcheck, running state is enough.

Output example:

```json
{
  "overall": "healthy",
  "services": [
    {
      "service": "postgres",
      "state": "running",
      "health": "healthy"
    }
  ]
}
```

---

# WHATSAPP / HERMES

POC assumptions:
- Hermes Agent
- WhatsApp via Baileys / unofficial
- dedicated bot number
- one WhatsApp group initially
- no individual DM

The bot should respond only when explicitly invoked / mentioned.

Examples:

```text
@BAST Bot status 1 sampai 31 Agustus
@BAST Bot export attendance 20 Juli sampai 18 Agustus
@BAST Bot generate BAST 1 sampai 31 Juli
@BAST Bot system status
```

Hermes should:
1. parse Indonesian date phrase,
2. convert to ISO,
3. call allowlisted command,
4. format deterministic JSON result.

Do not allow arbitrary shell commands.

For system status, if user asks restart/fix container:
respond that V1 only supports status inspection.

---

# WHATSAPP RESPONSE STYLE

Professional Indonesian, concise, actionable.

Example:

```text
*Status BAST — 1–31 Agustus 2026*

1. Titin
Timesheet ❌ | Task List ✅ | Evidence ✅ | Log 1 PAMA ❌

2. Putra
Timesheet ✅ | Task List ❌ | Evidence ❌ | Log 1 PAMA ✅

*Perlu ditindaklanjuti*
• Titin — 12 Agu: Clock Out belum terisi dan Evidence Attendance belum tersedia.
• Putra — Task "CCTV Gate 2" belum Closed.
• Putra — Evidence Task List belum tersedia.
```

System status:

```text
*Status Digital BAST*

✅ PostgreSQL — Healthy
✅ Redis — Healthy
✅ Prefect Server — Healthy
✅ Worker — Running
✅ Runner — Running
✅ Web Blue — Healthy
✅ Reverse Proxy — Healthy

Overall: ✅ Sehat
```

---

# AUTOMATION / PREFECT

Do not replace Prefect.

After manual commands are working, wire automation as thin wrappers around the SAME application services.

Do not duplicate business rules.

Use existing Asia/Jakarta timezone conventions.

If exact schedules are not already approved in repository/product context, keep them configurable and document examples instead of hardcoding assumptions.

Manual command flexibility remains the primary V1 behavior.

---

# TESTING REQUIREMENTS

Add unit/integration tests for at least:

## Attendance / Log 1 PAMA
- work + Clock In + Clock Out = complete
- work + missing Clock Out + no evidence = incomplete
- work + missing Clock In/Out + evidence = valid exception
- work + no attendance row = incomplete
- OFF + no attendance row = valid

## Timesheet
- Log 1 PAMA incomplete => Timesheet cannot be complete
- OFF + row + remarks = valid
- OFF + row + blank remarks = incomplete
- missing Timesheet row = incomplete

## Task List
- all Closed = complete
- one non-Closed = incomplete
- status normalization
- zero tasks = needs_review

## Evidence
- at least one evidence = complete
- none = incomplete

## CLI
- valid range
- invalid range
- JSON parseable output
- existing commands still work

## Docker status
- all healthy
- postgres unhealthy => degraded
- only web-blue active => valid
- only web-green active => valid
- no web slot => degraded
- Docker unavailable => clear error
- subprocess mocked in tests

---

# QUALITY / SAFETY

Follow repository standards:
- Python 3.12
- Ruff
- basedpyright strict
- pytest
- existing project patterns

Avoid:
- unnecessary abstractions
- generic repositories
- broad refactor
- speculative framework changes
- hidden business logic in Hermes
- duplicate implementations

---

# END-TO-END EXECUTION INSTRUCTIONS

Do all of the following in this run:

1. Inspect the whole relevant codebase.
2. Check git status and avoid overwriting unrelated user changes.
3. Trace evidence/attendance/task mappings.
4. Implement completion engine.
5. Extend CLI with all required commands.
6. Refactor attendance export for reuse if necessary.
7. Implement BAST generation command using existing report flow.
8. Implement read-only Docker system status.
9. Add Hermes skill/config/integration files needed for group command flow.
10. Reuse/integrate Prefect only where clean and non-duplicative.
11. Add/adjust tests.
12. Run tests.
13. Run Ruff.
14. Run basedpyright.
15. Fix issues you introduced.
16. Provide concise final implementation report.

Do not stop merely because one optional runtime credential/service is unavailable.
Complete everything possible from the codebase and isolate runtime-only gaps cleanly.

---

# FINAL REPORT FORMAT

At the end report:

```text
Implemented:
- ...

Files changed:
- ...

Commands:
- ...

Tests:
- ...

Hermes setup:
- ...

Runtime setup still needed:
- ...

Known limitations:
- ...
```

If there is a true blocker, explain the exact blocker and the minimal human action needed.

Do not ask product-design questions unless absolutely impossible to proceed safely.
Use the business rules in this prompt as authoritative.
