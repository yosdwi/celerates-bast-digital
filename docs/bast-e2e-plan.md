# BAST E2E: target architecture and implementation plan

Status: planning output, 2026-08-19. Written for the implementation session that follows.
Scope: Task List sync → Closed-task evidence → talent upload → WhatsApp resume → natural-language
interface → V1-compatible BAST document.

---

## 1. Audit findings

### 1.1 What already works and must not be disturbed

Attendance export is end-to-end today and is the reference for how the rest should be built:

- `scripts/load_pama_attendance.py` reads raw punches from SQL Server (`jiepsqco423`,
  `db_attendance` + `db_pamamobile`), reads the IoT shift roster from the exported roster CSV,
  applies `domain.timesheets.day_status`, and upserts flat rows into `durable_records`
  (`entity_kind = 'attendance'`, `source = 'pama-direct'`).
- `web/postgres_backend.py::attendance_legacy` + `web/csv_export.py::legacy_attendance_csv`
  produce the exact legacy CSV (semicolon, `DD/MM/YYYY`, 20 columns).
- `operations.export_attendance_report` writes the file, `cli.bot-reply` emits a JSON file marker,
  `bot-bridge/server.js` sends it to WhatsApp as a document.

Verified: 1071 rows for 1 Jul – 1 Sep 2026 (10 Developer + 7 IoT Operation × 63 days), byte-identical
in format to the reference export, overlapping rows matching the historical file.

**Do not refactor this path.** New work extends around it.

### 1.2 The single architectural blocker

`flows/production.py::create_run_context()` hard-requires NocoDB:

```python
if nocodb_database_dsn is None or nocodb_base_id is None:
    raise ProductionOperationUnavailableError(...)
repository = NocoDBDomainRepository(...)
employees = NocoDBPostgresEmployeeSource(...)
```

Everything downstream (`PipelineService`, all operations, `completion_status`, `generate_bast`)
is already written against **protocols**, not against NocoDB:

- `application/ports.py::DomainRepository` — `get` / `upsert` / `list_month`
- `infrastructure/production_sources.py::EmployeeSource` — `load()`

`infrastructure/repositories.py::PostgresDomainRepository` already implements `DomainRepository`
against `durable_records`. `infrastructure/local_completion_source.py::LocalEmployeeSource`
(added 2026-08-18) already implements `EmployeeSource` against `employee_data.json`.

So removing NocoDB from the read/write path is a **wiring change**, not a rewrite.

### 1.3 Sources that are reachable without the down VPS

| Data | Source | Status |
| --- | --- | --- |
| Attendance punches | SQL Server `db_attendance` | reachable, in use |
| Employee roster (NRP, name, role) | `employee_data.json` (built from `tbl_user`) | in repo |
| Developer Task List | SQL Server `DB_SATUPAMA_CIS.dbo.cis_jiep_tbl_redmine_bigdata_all_wi_digi` | reachable, verified |
| IoT tickets (SLA inputs) | Google Sheets "Master Support Ticket MS" | wired in `GoogleIoTTaskSource` |
| National holidays | `holidays` package (`country_holidays("ID")`) | in deps |
| IoT shift roster | exported roster CSV | in repo |
| **Task evidence images** | **NocoDB attachments only** | **unreachable — replaced by this plan** |
| **IoT SLA view** `vw_sla_iot_operations` | Postgres on the down VPS | **recomputed in code, see 3.8** |

`infrastructure/sqlserver.py` already contains `ATTENDANCE_QUERY` and `REDMINE_QUERY` — the same
SQL as V1 — plus `SqlServerSource`. `domain/transforms.py` already has `transform_redmine_task`
and `transform_iot_task`. Redmine import is unimplemented only at the *operation wiring* level
(`_OPERATION_GAPS[Operation.REDMINE_IMPORT]`), and is currently switched off through
`DIGITAL_BAST_DISABLED_OPERATIONS`.

### 1.4 What V1's BAST document actually is

V1's "BAST PDF" is `templates/all_report_template.html` — *"LAMPIRAN BERITA ACARA SERAH TERIMA"* —
assembled in `fastapi_server.py::generate_all_report` from independently rendered HTML sections,
then exported to PDF **client-side** in `report_editor.html` using jsPDF + per-page rasterisation.
`weasyprint` is listed in V1 `requirements.txt` but is never imported; there is no server-side
PDF renderer in V1.

Document structure:

1. Page header — PAMA logo left, Celerates logo right, title `LAMPIRAN BERITA ACARA SERAH TERIMA`
   with `{TYPE} REPORT - {month}/{year}`.
2. **Timesheet** — one A4 page per employee (`timesheet_report_template.html`).
3. **Task List** — role-dependent:
   - Developer: `Detail Aktivitas Kualitas Kode` (2.1), `Detail Aktivitas Waktu Rilis Fitur` (2.2),
     `Detail Aktivitas Dukungan Support` (2.3), paginated at **10 items per page**, average
     `Pencapaian` printed on the last page only.
   - IoT Operation: `Detail Problem Pihak Kedua`, `Detail Aktivitas Pihak Kedua`,
     `Detail Respon Resolution Time` (paginated at **50 items per page**).
4. **Evidence Aktivitas** (section 3) — `evidence/evidence_aktivitas.html`, numbered items with one
   image each.
5. **PAMA Attendance Report** (section 4) — `attendance_report_template.html`.
6. Footer + a `DOMContentLoaded` script that rewrites list numbering to `section.item`.

The section templates are plain Jinja2 with self-contained inline CSS and simple dict contexts:

| Template | Context |
| --- | --- |
| `timesheet_report_template.html` | `reports[]` with `nama, employee_id, start_date, end_date, total_*_hours, timesheet_rows[]`; each row keyed `Date, Activity, Project Name, Work Description, Start Time, End Time, Break Hours, Total Hours, Over Time Hours, Regular Hours, Is Holiday, Remarks` |
| `attendance_report_template.html` | `periode, dicetak, logo_url, reports[]` with `nrp, nama, attendance_rows[]` (`nrp, nama, tanggal_kehadiran, jam_kehadiran` where `jam_kehadiran` is `(time, status)` pairs) |
| `evidence/evidence_aktivitas.html` | `evidence_data[]` with `number, title, image_path, description`; `type`, `month` |
| `tasklistdeveloper/*.html` | `kualitas_kode_data` / `waktu_rilis_data` / `dukungan_support_data` — `no, task_list, requestor, pic, status, start_date, end_date, pencapaian`; plus `summary_pencapaian`, `month` |
| `tasklistiotoperation/detail_problem_pihak_kedua.html` | `problem_data[]` — `object, formula, keterangan` (**fully static content**, hardcoded in V1) |
| `tasklistiotoperation/detail_aktivitas_pihak_kedua.html` | `aktivitas_data[]` — `no, detail_aktivitas, tanggal_request, tanggal_penyelesaian, lead_time, requestor_pic, engineer_manage` |
| `tasklistiotoperation/detail_respon_resolution_time.html` | `respon_data[]` — `problem, tanggal_problem, waktu_problem, tanggal_respon, tanggal_penyelesaian, waktu_penyelesaian, pic_pama, engineer, waktu_respon_menit, aktual_waktu_1..4, performance_respon_1..2, performance_penyelesaian_1..2`; plus `summary_percentage`, `month` |

Because these templates are pure presentation over plain dicts, **the correct port is a verbatim
file copy plus a deterministic context builder.** Do not re-author the HTML/CSS.

### 1.5 Two V1 behaviours to preserve deliberately

1. **Only `Status = Closed` reaches the BAST.** Every V1 tasklist query filters
   `~and(Status,eq,Closed)`. Evidence is likewise only ever attached to those rows. This is the
   business rule the new evidence flow must mirror.
2. **`Pelaksanaan Pekerjaan` is silently missing from V1 output.**
   `_get_developer_tasklist_html_sections` calls `_generate_dev_pelaksanaan_page(...)`, which is
   **never defined anywhere in the V1 codebase**. The resulting `NameError` is swallowed by the
   surrounding `except Exception: pass`, so the section never renders even though
   `templates/tasklistdeveloper/pelaksanaan_pekerjaan.html` exists.
   → **Decided (2026-08-19): follow V1 — omit the section.** Do not implement it, and do not "fix"
   the omission. `pelaksanaan_pekerjaan.html` is copied over for completeness but stays unused.

### 1.6 V2 web layer

`web/app.py` already mounts auth / page / report / attendance routers, and `report_router.py`
already exposes the V1 route shapes (`/report/all` → `/admin/progressive-generator` →
`/admin/report-editor`). But `templates/report.html`, `report_editor.html` and `progressive.html`
are **3-line stubs**, and `PostgresWebBackend._report()` returns a generic `ReportView` of
`label · value` strings. The V1-compatible document does not exist in V2 today.

Sessions are Redis-backed (`RedisSessionStore`); the owner authenticator is NocoDB-backed. Both are
admin-facing and currently unavailable, which is why the talent-facing evidence flow (§3.3) must not
depend on either — it runs entirely over WhatsApp DM.

---

## 2. Target architecture

One process boundary is added (a talent upload surface inside the existing FastAPI app). No new
service, no new datastore, no new runtime dependency.

```
  SQL Server (Redmine)          Google Sheets (IoT)        SQL Server (attendance)
          │                             │                            │
          ▼                             ▼                            ▼
  RedmineTaskImportOperation    IoTTaskImportOperation      load_pama_attendance.py
          └──────────────┬──────────────┘                            │
                         ▼                                           │
                  PipelineService                                    │
              (merge_pipeline_record)                                │
                         └──────────────┬────────────────────────────┘
                                        ▼
                        PostgreSQL: durable_records
                   (holiday | attendance | task | schedule | timesheet)
                                        │
              ┌─────────────────────────┼──────────────────────────┐
              ▼                         ▼                          ▼
      task_evidence            BastCompletionSource          BastAssembler
   (talent uploads)            (status / resume)        (V1 templates verbatim)
              ▲                         │                          │
              │                         ▼                          ▼
      WhatsApp DM to bot         WhatsApp group          bast_artifacts (HTML)
      (bound JID, upload)      (resume / generate)        → /admin/report-editor
                                                          → headless jsPDF → PDF
```

### 2.1 Principles

1. **PostgreSQL is the only state.** `durable_records` stays the record spine; the new tables carry
   evidence blobs, WhatsApp identity binding, conversation state and generated documents.
2. **Deterministic core, thin edges.** LLM and WhatsApp are input adapters only. Every business
   decision lives in `domain/` and is reachable from the CLI without either.
3. **Reuse protocols, not rewrites.** New sources implement `DomainRepository` / `EmployeeSource` /
   `ProductionOperation`; `PipelineService` is untouched.
4. **The BAST is a build artifact.** Generation is a pure function of a consistent snapshot; the
   snapshot's fingerprint is stored so staleness is decidable rather than guessed.

### 2.2 New database objects (single Alembic migration)

```sql
CREATE TABLE task_evidence (
    id            uuid PRIMARY KEY,
    task_source   text NOT NULL,
    task_key      text NOT NULL,
    employee_id   text NOT NULL,
    work_date     date NOT NULL,
    caption       text NOT NULL DEFAULT '',
    content_type  text NOT NULL CHECK (content_type IN ('image/png','image/jpeg','image/webp')),
    byte_size     integer NOT NULL CHECK (byte_size > 0 AND byte_size <= 5242880),
    sha256        text NOT NULL,
    image         bytea NOT NULL,
    uploaded_at   timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (task_source, task_key)
        REFERENCES durable_records (source, external_id) ON DELETE CASCADE
);
CREATE INDEX ix_task_evidence_task ON task_evidence (task_source, task_key);
CREATE INDEX ix_task_evidence_employee_date ON task_evidence (employee_id, work_date);
CREATE UNIQUE INDEX ux_task_evidence_dedupe ON task_evidence (task_source, task_key, sha256);

CREATE TABLE wa_identity (
    wa_jid       text PRIMARY KEY,
    employee_id  text NOT NULL UNIQUE,
    bound_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE activation_codes (
    employee_id      text PRIMARY KEY,
    code_hash        text NOT NULL,            -- bcrypt, same pattern as nocodb_postgres_auth
    issued_at        timestamptz NOT NULL DEFAULT now(),
    used_at          timestamptz,
    failed_attempts  integer NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until     timestamptz
);

-- Multi-turn state for "upload untuk nomor berapa?"; rows older than 15 minutes are ignored.
CREATE TABLE bot_conversations (
    wa_jid               text PRIMARY KEY,
    pending_task_source  text,
    pending_task_key     text,
    updated_at           timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (pending_task_source, pending_task_key)
        REFERENCES durable_records (source, external_id) ON DELETE CASCADE
);

CREATE TABLE bast_artifacts (
    id            uuid PRIMARY KEY,
    report_type   text NOT NULL CHECK (report_type IN ('iotoperation','developer')),
    year          integer NOT NULL,
    month         integer NOT NULL CHECK (month BETWEEN 1 AND 12),
    fingerprint   text NOT NULL,
    document      text NOT NULL,
    generated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_bast_artifacts_scope ON bast_artifacts (report_type, year, month, generated_at DESC);
```

The composite foreign key is the reason evidence cannot outlive or precede its task: `durable_records`
has `PRIMARY KEY (source, external_id)`, and domain records are written with `source = 'domain'`.

`employee_data.json` stays the roster source of truth: it is small, git-tracked, and already drives
the working attendance export. Promote it to a table only if it starts changing per-week.

---

## 3. How each flow works

### 3.1 How the Task List arrives and changes

A new `RedmineTaskImportOperation` (mirroring the existing `IoTTaskImportOperation`) is wired into
`create_run_context`:

1. `SqlServerSource.redmine(period)` runs the existing `REDMINE_QUERY` for the month window.
2. Rows are mapped to `RedmineTaskInput` and put through the existing `transform_redmine_task`,
   which already derives `TaskCategory.RELEASE` for tracker `DIGI-SI` and `CODE_QUALITY` otherwise,
   and validates achievement bounds.
3. NRP → `EmployeeId` mapping comes from `LocalEmployeeSource` (`employee_data.json`), skipping
   rows whose NRP is not in the roster — same behaviour as V1's `nrp_to_id` filter.
4. `PipelineService.upsert` merges through `domain/rules.py::merge_pipeline_record`:
   - unseen key → insert, `changed = True`
   - existing row with `origin = MANUAL` → **locked, never overwritten**
   - identical payload → `unchanged`
   - different payload → overwrite, `durable_records.version` increments and `updated_at` moves

Status transitions therefore arrive as ordinary payload changes. The `version`/`updated_at` bump is
what later makes a generated BAST stale (3.6). Re-running the import is idempotent.

Observed statuses in the source: `New / Not Started`, `In Progress`, `Feedback`, `Closed`.

### 3.2 How Closed tasks and evidence relate

Rule (matching V1): **a task requires evidence if and only if its status casefolds to `closed`.**

- Not-closed tasks are excluded from the BAST entirely and are never asked for evidence; they are
  reported separately in the resume as *"belum Closed"*.
- Closed tasks with no row in `task_evidence` are *"Closed tanpa evidence"* — the actionable queue.
- Evidence for a task that later reverts from Closed is retained (it is still true that a file was
  uploaded); it simply stops being counted until the task is Closed again.

The check functions in `domain/completion.py` already encode most of this shape (`_task_list`
flags non-Closed tasks; `_evidence` currently only counts). Extend `EmployeeFacts` with a
per-task evidence count instead of a single scalar so the resume can name specific tasks.

### 3.3 How talent uploads evidence

**Group is monitoring. Private DM to the bot is action.** Talent never leaves WhatsApp: no portal,
no browser, no link, no login page, no frontend to maintain.

Two earlier drafts were rejected before this one, and the reasons matter:

- *Personal magic links* — a personal URL is easy to lose, cannot be pinned, and resolving "who is
  this" needs a phone-to-employee mapping that does not exist (`tbl_user.telp_1` is populated for
  only **4 of 10** developers, verified 2026-08-19).
- *One permanent web portal with name + PIN* — solves the lost-URL problem but still pushes talent
  out of WhatsApp into a browser, and still needs a login surface, a session cookie, a public URL
  and its own brute-force defence.
- *Uploading evidence in the group* — turns a 17-person group into a transaction log. Rejected on
  noise alone.

```
  GROUP (monitoring only)                    PRIVATE DM (action)
  ┌───────────────────────────┐
  │ Evidence BAST Agustus     │              Yoses → bot: "evidence saya"
  │ 13/17 talent lengkap      │                        │
  │ Kurang: Yoses (2),        │              unknown JID → one-time activation
  │         Titin (1)         │              (Employee ID + activation code)
  └───────────────────────────┘                        │
              ▲                               bind wa_jid → employee, once
              │                                        │
              │                              "Evidence kamu — Agustus 2026
       next resume reflects                    Closed 5 · lengkap 3/5
       what was uploaded                       Belum: 1. CCTV Gate 2
                                                      2. Firmware Validation
                                               Upload untuk nomor berapa?"
                                                        │
                                               Yoses: "1"  /  "yang cctv dulu"
                                                        │
                                               Yoses sends JPG(s)
                                                        │
                                               task_evidence (Postgres)
```

**One-time binding.** The bot does not need a pre-collected phone list. On the first DM from an
unknown JID it asks for an Employee ID plus a one-time activation code; on success it stores
`wa_jid → employee_id` and never asks again. Activation codes are generated once for the whole
roster (`digital-bast issue-activation-codes`, prints 17 codes), are bcrypt-hashed at rest, expire
on first use, and are rate-limited (5 attempts per employee per 15 minutes). Employee ID alone is
**not** sufficient proof — it is printed on the BAST itself and known to the whole team.

**Command surface is scoped by channel**, which is the security boundary that replaces the group
allowlist once DMs are open:

| Channel | Allowed |
| --- | --- |
| Allowlisted group | resume / status / export / generate — unchanged |
| DM, bound JID | evidence listing and upload **only** |
| DM, unbound JID | activation attempt only, rate-limited, nothing else |

Reporting and generation stay out of DM entirely. A stranger who messages the bot can do exactly one
thing: fail an activation.

**Conversation state.** Picking a task then sending a file is inherently multi-turn — the first
stateful interaction in this system. Keep it minimal: one row per JID in `bot_conversations` holding
the pending task, expiring after 15 minutes. Three inputs resolve a target task, in order:

1. an image whose caption names a task → matched against that user's candidates;
2. an image with no caption when exactly one task is outstanding → attached to it;
3. otherwise the numbered prompt above, with the reply stored as pending state.

**Media handling.** `@whiskeysockets/baileys` 6.7.24 (already installed) exports
`downloadMediaMessage`; the bridge downloads to a temp path and calls
`digital-bast bot-evidence --jid ... --file ... --caption ...`, mirroring how `bot-reply` is already
shelled out. Accept both `imageMessage` and `documentMessage` — WhatsApp re-compresses photos, and
evidence screenshots are often text-heavy, so the bot should tell talent that sending as a document
preserves the original. Validate as in any upload path: sniff magic bytes for PNG/JPEG/WebP, cap at
5 MB, deduplicate by `sha256` per task, and confirm the task is Closed and owned by the sender
inside the same transaction as the insert.

**Storage**: bytes go to `task_evidence.image` (bytea). At this dataset size (tens of images per
month) this keeps backup/restore single-source and avoids orphaned files; the existing
`scripts/backup.sh` then already covers evidence.

Object storage (Supabase or similar) was considered and rejected — decided 2026-08-19. It would add
an external service, a second credential, a second failure mode, and a network dependency, to hold a
few dozen sub-5 MB images that PostgreSQL stores fine. It also points the wrong way: the whole reason
this system is being rebuilt locally is that a cloud dependency became unreachable.

**This reverses an existing policy decision.** `config/hermes/bast-bot.yaml` currently sets
`allow_direct_messages: false` and lists *"individual direct messages"* under `denied_intents`, and
`bot-bridge/server.js` drops every non-group message (`if (!jid.endsWith("@g.us")) continue`). Both
must be changed deliberately, and the channel scoping table above is what keeps the reversal safe —
update the Hermes config in the same commit so policy and behaviour do not drift apart.

Google login was considered and rejected: an OAuth client, a redirect URI, a new dependency, and a
Google identity for every talent — to answer a question a one-time activation code already answers,
for a fixed roster of 17 people.

### 3.4 How the WhatsApp resume works

The group stays low-noise. It carries **three kinds of message and nothing else** — never per-upload
or per-task chatter:

**1. Resume** (on request, and on a schedule if wanted)

```
*Evidence BAST — Agustus 2026*
13/17 talent lengkap

Kurang:
• Yoses Dwi Maheswara — 2 Closed task tanpa evidence
• Titin Ervina Sari — 1
• Muhammad Putra Tama Bayu Hargio — 2

Task belum Closed: 13 (dari 84)
Lengkapi lewat chat pribadi ke bot ini.
```

**2. Reminder**, only while something is outstanding.

**3. Generation / status** — "BAST Developer Agustus berhasil digenerate", plus the PDF itself.

Explicitly not in the group: "Yoses upload file ✅", "Titin upload ✅", per-task acknowledgements.
Those are DM-only, addressed to the person who acted.

Data comes from `completion_status`, so the resume and the BAST always agree by construction — same
query path, same rules. Extend `bot/whatsapp.py::format_completion` into the format above; the
per-employee ✅/❌/⚠️ breakdown it renders today stays available as the detailed `status` command.

### 3.5 LLM → deterministic backend contract

The LLM never executes anything and never computes a business value. It only converts free text into
a **command draft**, which is then validated and executed by the same deterministic code the regex
path uses.

**The LLM is the primary interpreter whenever it is available.** An earlier draft of this plan had
the LLM run only when the regex parser returned `UNKNOWN`; that is wrong, and it is worth writing
down why. The dangerous failure mode is not the regex *failing* — that is visible and recoverable.
It is the regex **succeeding with the wrong answer**: on 2026-08-18 the message
`export attendance shifting1 agustus 2026 - 20 agustus 2026` parsed cleanly to the range
20–20 August because the day pattern matched the `20` inside `2026`. A fallback that only triggers
on `UNKNOWN` can never see that class of error. Making the LLM primary also removes the maintenance
treadmill of patching a regex for every new phrasing.

```
                    BOT_LLM_URL set?
                    │              │
                   yes             no
                    │              │
                    ▼              ▼
   Ollama /api/chat            parse_command()      ← today's deterministic parser
   (format=json, temp 0)            │                 (also the fallback on any LLM failure)
                    │               │
                    ▼               │
      BotCommandDraft (pydantic, strict)
        intent: Literal[...]        │
        start_date / end_date: date | None
        report_type: Literal["developer","shifting"] | None
                    │               │
      reject if: unknown intent, unparsable dates,
      end < start, span > 366 days, missing required field
                    │               │
                    └───────┬───────┘
                            ▼
                    BotCommand ─► executor   ← one deterministic path, identical either way
```

Rules:

- Model call is behind `BOT_LLM_URL`. Unset ⇒ exactly today's regex-only behaviour, so the system
  still runs with no model available. `httpx` is already a dependency; nothing new is installed.
- Failure of any kind — timeout, non-JSON, schema violation, range sanity — falls back to
  `parse_command()`, and if that also yields nothing, to `HELP_REPLY`. The bot never guesses a period.
- **Every** command echoes its interpretation before the payload, whichever parser produced it:
  *"Saya baca sebagai: export attendance developer, 1–20 Agustus 2026."* This is the actual safety
  net — it makes a misread visible in one line regardless of which parser misread it.
- The LLM is never given database contents, only the user's sentence and today's date.
- All commands are read-only (reports, exports, documents), so a misinterpretation costs a wasted
  export, never damaged data. That is what makes LLM-primary an acceptable trade here; it would not
  be if these commands mutated records.
- Model choice: a small local instruct model (3B class) is enough for slot extraction and keeps the
  added latency to roughly 1–3 s against the ~10 s the reply already takes.

**Evidence task selection is a bounded choice, not free extraction.** In the DM flow the backend
already knows the candidate set — that employee's outstanding Closed tasks, typically two or three.
The model is handed the numbered list and must return **an index into it**, never a task title, an
id, or a query:

```
system:  Pilih satu nomor dari daftar. Jawab JSON {"choice": <int|null>}.
user:    Daftar: 1. CCTV Gate 2  2. Firmware Validation
         Pesan: "yang cctv dulu"
→        {"choice": 1}
```

`null` or an out-of-range index means "ask again", never a guess. This keeps a natural phrasing
("yang cctv dulu", "ini buat firmware validation") working while making it structurally impossible
for the model to reach a task that is not the sender's, not Closed, or not in this period — the
authorisation is in the candidate list, not in the prompt.

### 3.6 How data changes make an existing BAST stale

At generation time the assembler computes, inside the read transaction:

```
fingerprint = sha256(
    "durable:" + Σ over scope rows, ordered by external_id: f"{external_id}:{version}:{updated_at}"
  + "evidence:" + Σ over evidence rows, ordered by id:      f"{id}:{sha256}"
)
```

Scope = all `durable_records` for the report's month and role (task / timesheet / attendance /
schedule / holiday) plus every `task_evidence` row joined to those tasks.

`version` and `updated_at` already exist on `durable_records` and are already bumped by
`PostgresDomainRepository._upsert`. Nothing new needs to be tracked.

Staleness is then a comparison, not a guess: recompute the fingerprint and compare with
`bast_artifacts.fingerprint`. Equal ⇒ the stored document is still exactly what the current data
would produce, and it is served as-is. Different ⇒ it is reported as stale and regenerated. This
also gives the bot an honest answer to "apakah BAST bulan ini masih valid?".

### 3.7 How generation takes a consistent input

All reads for one BAST happen on **one connection, in one transaction, at REPEATABLE READ**:

```python
with psycopg.connect(dsn) as connection:
    connection.set_isolation_level(IsolationLevel.REPEATABLE_READ)
    with connection.transaction():
        rows = _load_scope(connection, ...)  # tasks, timesheets, attendance, schedules
        evidence = _load_evidence(connection, ...)
        fingerprint = _fingerprint(rows, evidence)
        document = assemble(rows, evidence)
        _insert_artifact(connection, fingerprint, document)
```

PostgreSQL gives that transaction a single stable snapshot, so an import or an upload landing
mid-generation cannot produce a document that mixes old tasks with new evidence — and the
fingerprint written alongside describes exactly the snapshot that was rendered. No advisory locks,
no queue, no worker. This is the whole atomicity story, and at this scale it is sufficient.

The two write paths are independently atomic and need nothing extra:

- evidence upload = one `INSERT` after an in-transaction ownership + Closed check;
- task import = per-record `INSERT ... ON CONFLICT DO UPDATE` through `PipelineService`.

### 3.8 How the V1-compatible BAST is produced

**Templates are copied verbatim** from `v1-prod/templates/` into `v2-prod/templates/bast/`:
`all_report_template.html`, `timesheet_report_template.html`, `attendance_report_template.html`,
`evidence/evidence_aktivitas.html`, `tasklistdeveloper/*.html`, `tasklistiotoperation/*.html`, plus
`static/img/logo_pama.png` and `logo_celerates.jpg`. No re-authoring — parity comes from using the
same files.

A new `web/bast_assembler.py` builds each section's context from Postgres and renders the same
templates in the same order, reproducing V1's section titles, ordering and pagination
(10/page developer, 50/page IoT respon, summary on last page only).

Source mapping per section:

| Section | V1 source | V2 source |
| --- | --- | --- |
| Timesheet | NocoDB `timesheet` table | `durable_records` `entity_kind='timesheet'` (already generated by `TimesheetGenerationOperation`) |
| Developer tasklist | NocoDB `tasklist`, `Status=Closed` | `durable_records` `entity_kind='task'`, category + `status='Closed'` |
| IoT problem | hardcoded literal table | same literal table, moved into a module constant |
| IoT aktivitas | NocoDB tasklist filtered `%95%` | `durable_records` IoT tasks for the period |
| IoT respon | Postgres view `vw_sla_iot_operations` (**down VPS**) | computed in `domain/` from `Task.start_at / response_at / close_at` |
| Evidence | NocoDB attachment `signedPath` URLs | `task_evidence`, embedded as `data:` URIs |
| Attendance | NocoDB `attendance_raw` | `durable_records` `entity_kind='attendance'` |

**IoT SLA — deferred to backlog (decided 2026-08-19).** `Detail Respon Resolution Time` is the one
section whose numbers came from `vw_sla_iot_operations` on the unreachable VPS, so its parity cannot
be verified against anything today. It is therefore **out of scope for this implementation**: build
the Developer BAST completely, and render the IoT respon section as an explicit
"data SLA belum tersedia" placeholder rather than shipping unverifiable numbers.

The recovery path is recorded here so the backlog item is cheap to pick up: the formulas are printed
by the report itself (`detail_problem_pihak_kedua`) — SLA respon 15 minutes, SLA penyelesaian
30 minutes, `achievement% = clamp(200 − 100 × actual ÷ SLA, 0, 100)`, section summary = mean of the
two achievement means rounded to one decimal, computed from `Task.start_at / response_at / close_at`
which V2 already ingests from Google Sheets. When the VPS returns, implement `domain/iot_sla.py`,
pin the boundary cases in a unit test (actual = SLA ⇒ 100 %, actual = 2 × SLA ⇒ 0 %, clamping
outside), and reconcile against the view before trusting it.

**Evidence images** are embedded as `data:{content_type};base64,...` when the document is assembled.
The artifact is then self-contained: it prints identically from any browser, needs no auth on image
routes, and survives being sent as a file.

**PDF is produced by V1's own exporter, driven headlessly.** Decided 2026-08-19: the bot must send
the finished PDF into the chat, so a server-side step is required — but it must not become a
*different renderer*, or "sama persis" is lost.

V1's PDF comes from `report_editor.html` (jsPDF + per-page rasterisation, client-side). That file is
ported verbatim, and generation runs **that same JavaScript** inside headless Chromium:

1. `/admin/report-editor?artifact={id}` serves the stored artifact HTML into the ported editor page.
2. Playwright opens that URL, waits for the pages to settle, and calls the export.
3. The ported page gains one small addition — `window.__bastExportPdf()`, which runs the existing
   export routine but ends in `doc.output('datauristring')` instead of `doc.save()`, so the bytes can
   be read back deterministically instead of racing a browser download.
4. The PDF is written to `bot-bridge/data/exports/` and sent as a WhatsApp document by the existing
   `sendFileReply` path.

The rendering code is therefore V1's, unchanged; only the harness around it is new. This is the one
place where the plan accepts a new dependency (`playwright` + its Chromium download) — justified by
the explicit requirement that the user receives a finished file rather than a link. Chromium's own
`page.pdf()` is **not** an acceptable substitute here: it is a different rasteriser and would change
the output.

Browser export from `/admin/report-editor` keeps working by hand, unchanged, as the fallback.

---

## 4. Implementation plan

Five work packages, in dependency order. Each ends in a runnable state.

### WP1 — NocoDB-free run context

- Add `create_local_run_context()` in `flows/production.py` (or extend `create_run_context` to fall
  back when `NOCODB_DATABASE_DSN` is absent), wiring `PostgresDomainRepository` +
  `LocalEmployeeSource` into the existing `PipelineService`.
- Drop `IOT_PIC_UPDATE` from the local context (it calls a NocoDB stored procedure); it must report
  unavailable rather than fail obscurely.
- `operations.py::_default_completion_source` already falls back this way — follow that pattern.
- Verify: `digital-bast run holiday-sync --period 2026-08` and `run timesheet-generation` write to
  `durable_records` with no NocoDB configured.

### WP2 — Task List ingestion — DONE (2026-08-19)

- Implemented `RedmineTaskImportOperation` in `flows/production_operations.py`, modelled on
  `IoTTaskImportOperation`.
- SQL Server rows → `RedmineTaskInput` via `SqlServerRedmineTaskSource` in
  `infrastructure/production_sources.py`, resolving NRP through `LocalEmployeeSource`
  (`employee.external_id == nrp`).
- **Deviation from the audit's assumption:** `infrastructure/sqlserver.py::SqlServerSource` (pyodbc)
  is dead code — no ODBC driver is installed in this environment (`pyodbc.drivers()` returns `[]`),
  matching why `scripts/load_pama_attendance.py` already uses `pymssql` instead. Left `sqlserver.py`
  untouched; `SqlServerRedmineTaskSource` connects with `pymssql` directly, same pattern as the
  attendance script. Added `pymssql>=2.3,<3` to `pyproject.toml` and a minimal stub at
  `typings/pymssql/__init__.pyi` (`basedpyright` strict has no upstream stubs for it).
- Redmine lives on a **separate SQL Server** from attendance (`JIEPBDSQ403` / `DB_SATUPAMA_CIS`,
  vs. attendance's `jiepsqco423`), matching V1's `REDMINE_DB_*` split. Added
  `REDMINE_DB_SERVER` / `REDMINE_DB_USERNAME` / `REDMINE_DB_PASSWORD(_FILE)` / `REDMINE_DB_NAME` to
  `config.py` (not folded into the existing, already-orphaned `SQLSERVER_CONNECTION_STRING`).
  Not added to `_validate_production`'s required-secrets list — same "conditionally wired, reports
  unavailable if absent" treatment as `IOT_TASK_IMPORT`/Google credentials.
- Field mapping verified against `v1-prod/src/classes/ClsRedMine.py`: title=`isu_subject`,
  requestor=`author_name`, status=`status_desc`, start=`start_date`, end=`due_date`,
  tracker=`tracker_name` (`"DIGI-SI"` ⇒ `RELEASE`), achievement=`done_ratio`, source_id=`isu_id`.
- Registered under `Operation.REDMINE_IMPORT`; removed `redmine-import` from
  `DIGITAL_BAST_DISABLED_OPERATIONS` in `.env` / `.env.example` (left `attendance-import` disabled —
  that path stays on `scripts/load_pama_attendance.py`, out of scope, per §1.1).
- Fixed a real, pre-existing `basedpyright` strict failure while getting `src/` clean: `operations.py`
  passed `PostgresAttendanceFactReader` where `NocoDBCompletionSource.__init__` demanded the
  concrete, `@final` `NocoDBAttendanceReader` class. Added a structural `AttendanceReader` Protocol
  in `infrastructure/completion_source.py` and typed the parameter against it — this was already
  broken from WP1, not introduced here.
- Verified: ran `Operation.REDMINE_IMPORT` directly against real `JIEPBDSQ403` and local Postgres for
  period 2026-08 — 22 rows read/written first run, second run reports `unchanged=22`. Spot-checked
  `durable_records`: titles, status, category (`DIGI-SI` → release), and achievement all populated
  correctly for real employees.
- `basedpyright src/` and `ruff check src/` both clean except 10 pre-existing errors in the
  untouched, dead `infrastructure/nocodb_repository.py` (baseline before this session, unrelated to
  Redmine — not fixed, out of WP2 scope).
- `digital-bast run operational-import` (the Prefect-flow CLI path) requires a reachable
  `PREFECT_API_URL`, which is not up in this dev environment — verification therefore ran the
  operation directly through `create_run_context()`, same as the WP1 verification did. The Prefect
  flow wiring itself is untouched and should work once a Prefect server is reachable.

### WP3 — Evidence over DM: schema, binding, upload, resume — DONE (2026-08-19)

- Migration `20260819_0002_bast_evidence.py`: `task_evidence`, `wa_identity`, `activation_codes`,
  `bot_conversations`, `bast_artifacts` (§2.2), applied to `bast-local-pg`.
- `bot/identity.py::ActivationService` — 8-char alphanumeric codes, bcrypt-hashed (mirrors
  `nocodb_postgres_auth.py::_verify_password`), `FOR UPDATE` row lock during verify, attempt
  counter + 15-minute lockout after 5 wrong tries, one-time use, `resolve(wa_jid)` lookup.
- `bot/evidence.py::EvidenceService` — `list_candidates` (Closed tasks only, LEFT JOIN
  `task_evidence` for a live per-task count), `outstanding()` filter, `select_by_caption` /
  `select_by_index` (numeric / caption resolution only — the bounded-LLM-choice mode from §3.5 is
  WP5's job, not built here), `pending_task`/`set_pending`/`clear_pending` (`bot_conversations`,
  naturally TTL'd via `updated_at > now() - interval '15 minutes'` rather than a stored snapshot,
  since `list_candidates`' `ORDER BY work_date, external_id` is already deterministic — replying "1"
  re-resolves the same index without needing to persist the shown list), and `upload` (magic-byte
  sniff for PNG/JPEG/WebP, 5 MB cap, ownership + Closed check and the `sha256` dedupe insert inside
  one transaction).
- CLI: `digital-bast issue-activation-codes` (prints `{employee_id: code}` for the whole roster from
  `employee_data.json`), `digital-bast bot-evidence --jid --file --caption`, and `bot-reply` gained
  `--jid` / `--channel {group,dm}`. DM text protocol: unbound JID accepts only
  `aktivasi <Employee ID> <code>`; bound JID accepts `evidence` (list) and a bare number (select,
  stored as pending). New group intent `evidence <period>` → `format_evidence_resume`.
- `bot-bridge/server.js`: `messages.upsert` now branches on `@g.us` (existing group path, untouched)
  vs `@s.whatsapp.net` (new `handleDirectMessage`/`handleEvidenceUpload`, no trigger-word gating —
  every DM is in scope, `digital-bast` itself enforces the unbound/bound split). Accepts both
  `imageMessage` and `documentMessage` via `downloadMediaMessage`, saved to
  `bot-bridge/data/evidence-uploads/` and cleaned up after the CLI call.
- `config/hermes/bast-bot.yaml` updated in the same commit: `allow_direct_messages: true`, the
  per-channel scoping documented inline, `denied_intents` now names "reporting/generation from a
  DM" instead of "individual direct messages." (This file isn't read by any code in this repo — it's
  a spec for a separate, unimplemented Hermes Agent integration; `bot-bridge/server.js` is what
  actually runs. Updated anyway since the plan calls it out as a same-commit policy record.)
- `domain/completion.py`: `TaskFact` gained `evidence_count: int`; `EmployeeFacts.task_evidence_count
  : int | None` (employee-wide scalar) became `evidence_available: bool`, with per-task detail read
  from each `TaskFact`. `_evidence()` now names the specific Closed tasks missing evidence instead of
  one binary flag for the whole employee. `EmployeeCompletion` gained `total_tasks: int`. The
  `TaskEvidenceReader`/`AttendanceReader` reader params on `NocoDBCompletionSource` are now
  Protocols (structural), not the concrete `@final` NocoDB classes, so `PostgresTaskEvidenceReader`
  (new, `infrastructure/local_completion_source.py`, real per-task counts from `task_evidence`) and
  `PostgresAttendanceFactReader` both satisfy them without inheritance.
  **Known, accepted limitation:** `NocoDBTaskEvidenceReader` (legacy, unreachable, zero test
  coverage) has no way to map its NocoDB `Id_Key` to the domain `RecordKey` computed in
  `domain/identity.py::task_key` — that correspondence was never established anywhere in this
  codebase, not something WP3 introduced. Re-keyed it by `Id_Key` for internal consistency with the
  new per-task-key protocol and documented the limitation inline; it is not wired into
  `create_run_context` or `operations.py` and cannot run today.
- `bot/whatsapp.py`: new `format_evidence_resume()` implementing the §3.4 group format exactly
  (`N/M talent lengkap`, named `Kurang:` lines, `Task belum Closed: X (dari Y)`). Found and fixed a
  real bug while building it: naively summing `len(employee.task_list.issues)` over-counted "not
  Closed" — an employee with **zero** tasks at all gets a single `NEEDS_REVIEW` issue ("Belum ada
  Task List pada periode") from `_task_list()`, which isn't a not-Closed *task* and was inflating the
  numerator past the denominator (e.g. `24 (dari 22)`, live output before the fix). Fixed by summing
  only over employees whose `task_list.state is CheckState.INCOMPLETE`; regression-tested in
  `tests/unit/bot/test_whatsapp.py::test_evidence_resume_counts_only_real_not_closed_tasks`.
  `format_completion` (the detailed per-employee ✅/❌/⚠️ breakdown) is untouched, per the plan's own
  note that it stays available as the detailed `status` command.
- Tests: `tests/integration/test_identity.py` (activation binds once, wrong code counts a failure
  but a later correct one still works, 5 failures lock and stay locked, code expires after first use,
  unknown employee ID rejected, unbound DM JID gets the activation prompt regardless of what it
  sends) and `tests/integration/test_evidence.py` (only Closed tasks are candidates, upload rejects
  not-owned/not-Closed, upload stores once and dedupes by hash, `select_by_index` bounds) — both
  gated on `TEST_DATABASE_DSN`, same skip pattern as `tests/integration/test_postgres.py`. Extended
  `tests/unit/domain/test_completion.py` for the per-task evidence shape.
- Verified against real `bast-local-pg` + real August 2026 Redmine task data end-to-end over the CLI
  (standing in for the WhatsApp transport, which `bot-bridge/server.js` already drives): issued 17
  activation codes; wrong code counted a failure and a correct one still activated; 5 wrong attempts
  on a second employee locked them and a subsequently-correct code was still refused; `evidence`
  listed real Closed tasks; picking a number set `bot_conversations` pending state; a real 1×1 PNG
  uploaded through `bot-evidence` with no caption resolved via that pending state, landed in
  `task_evidence` with correct `sha256`/`byte_size`, and cleared the pending row; re-uploading the
  same bytes returned `DUPLICATE`; the group `evidence 1 sampai 31 Agustus 2026` command produced a
  correct resume against that same data (`13/17 talent lengkap`, 4 named employees, `13 (dari 22)`).
- `basedpyright` (project-wide) and `ruff check src/ tests/` both clean except the same 10
  pre-existing `nocodb_repository.py` errors carried over from WP2 (untouched, dead code).
  Full suite: 180 passed with `TEST_DATABASE_DSN` set (176 unit/e2e + integration), 1 pre-existing
  failure (`test_current_period_uses_jakarta_calendar_independent_of_source_offset`, documented,
  unrelated to this work).
- **Not built in WP3, left for WP5 per the plan:** the LLM-backed "bounded choice" task selection
  (§3.5) — DM selection here is numeric-index and caption-substring only, which is what §3.3 lists as
  the deterministic fallback modes; `bot/evidence.py::select_by_caption`/`select_by_index` are
  already shaped so a WP5 LLM chooser slots in as a third, still-bounded resolution path without
  changing `EvidenceService`.

### WP4 — V1-compatible BAST assembly and PDF delivery

- Copy V1 templates and logos verbatim (§3.8), including `report_editor.html`.
  `pelaksanaan_pekerjaan.html` is copied but stays unused (§1.5).
- `web/bast_assembler.py` — per-section context builders + `assemble(report_type, year, month)`,
  reading inside one REPEATABLE READ transaction, returning `(document, fingerprint)`.
  IoT `Detail Respon Resolution Time` renders a "data SLA belum tersedia" placeholder (§3.8).
- Persist to `bast_artifacts`; add `GET /admin/bast/{id}` and wire `/admin/report-editor` to it.
- Add `window.__bastExportPdf()` to the ported editor page — same export routine, ending in
  `doc.output('datauristring')`.
- `infrastructure/pdf_export.py` — Playwright headless Chromium: open the editor URL, call
  `__bastExportPdf()`, decode the data URI, write the file. Add `playwright` to `pyproject.toml`
  and document the `playwright install chromium` step in the README.
- Rework `operations.generate_bast` to use the assembler and return the PDF path; keep the existing
  CLI surface. Wire `Intent.GENERATE_BAST` to emit the same JSON file marker the attendance export
  uses, so `bot-bridge/server.js::sendFileReply` delivers the PDF unchanged.
- Replace `templates/bast.html` (the 44-line placeholder) with the ported document.
- Verify against a V1 reference export for the same month, section by section.

### WP5 — Natural-language interface — DONE (2026-08-19)

- `bot/llm.py` — `LlmInterpreter`, an Ollama client behind `BOT_LLM_URL` (`/api/chat`,
  `format=json`, `temperature=0`, 10 s timeout). `BotCommandDraft` (strict pydantic, `Literal`
  intent/report_type, `date | None` bounds) is validated into a `BotCommand`; any failure —
  timeout, non-JSON, schema violation, `end < start`, span > 366 days, missing period for a
  period-requiring intent — returns `None` rather than raising, so the caller's fallback is a
  plain `is None` check, not exception handling.
- `operations.create_llm_interpreter()` returns `None` when `settings.bot_llm_url` is unset
  (`config.py` gained `bot_llm_url: AnyHttpUrl | None` / `bot_llm_model: str`, default
  `llama3.2:3b`, no secret handling needed — it's a local URL, not a credential), matching the
  existing `create_activation_service()`/`create_evidence_service()` factory pattern.
- `cli.py::_resolve_command()` is now what `_group_reply` calls instead of `parse_command()`
  directly: tries the LLM first when configured, falls back to `parse_command()` on `None` from
  either an absent interpreter or a failed draft. `_echo_interpretation()` builds the "Saya baca
  sebagai: ..." line from the *resolved* `BotCommand`, so the echo is identical regardless of
  which parser produced it (§3.5's actual safety net). For `EXPORT_ATTENDANCE`/`GENERATE_BAST`
  the echo goes into the JSON file-marker's `caption` field, not prepended to the reply string —
  prepending would have broken `bot-bridge/server.js::parseFileReply`'s `JSON.parse(text)` and
  silently degraded file delivery to a plain-text dump of the JSON. Caught by re-reading that
  function before wiring the echo in, not by a failing test.
- DM evidence selection (§3.3's third, bounded-choice resolution path, deferred from WP3):
  `_dm_llm_pick()` in `cli.py` — when digit-index and caption-substring both miss, and an
  interpreter is configured, the sender's own outstanding-candidate *titles* (not ids, not raw
  task rows) go to `LlmInterpreter.choose_index()`, which must return an in-range index or
  `None`. Authorisation is structural: the model physically cannot select a task that isn't
  already in the caller-supplied candidate tuple.
- Tests: `tests/e2e/flows/test_cli.py::test_bot_reply_llm_disambiguates_ambiguous_date_range`
  (fakes `create_llm_interpreter` to return the correct 1–20 August split for exactly the
  `shifting1 agustus 2026 - 20 agustus 2026` message the audit flagged, asserts the echo line
  and the correct period reach `export_attendance_report`) and
  `test_bot_reply_falls_back_to_regex_when_llm_returns_none` (fakes an interpreter whose
  `interpret()` returns `None`, confirms `parse_command()` still drives the reply). `ruff` and
  `basedpyright` (strict) both clean on every file this work package touched.
- Verified live, not just unit-tested: `bast-local-pg` started, `ollama serve` started (model on
  hand was already-pulled `llama3.2:1b`, not the `llama3.2:3b` default — `BOT_LLM_MODEL` set
  accordingly in `.env`; either is fine for this slot-extraction task), `bot-bridge/server.js`
  launched with `APP_DATABASE_DSN` exported in its process env (per the handoff note: never in
  `.env`) and reconnected to WhatsApp using the existing `bot-bridge/auth/` session — no QR scan
  needed. Hit the bridge's own `/try` endpoint with `status 1 sampai 5 agustus 2026`: the LLM
  path produced the correct period, the echo line, and the real per-employee completion status
  against live `durable_records` data end to end.
- Full suite after this work package: 173 passed, 13 skipped (all `TEST_DATABASE_DSN` —
  environmental, container was down at that point in the session, not a code issue), 1 failed —
  still only the pre-existing `test_pipelines.py` Jakarta-calendar case, unrelated to this work.

### Tests — critical path only

Add these, and nothing more until the feature is complete:

1. `tests/unit/domain/test_completion.py` (extend) — Closed-without-evidence and not-Closed
   classification.
2. `tests/unit/bot/test_identity.py` — activation binds once, a wrong code counts a failure,
   five failures lock, an unbound JID is refused every command except activation.
3. `tests/unit/web/test_bast_fingerprint.py` — fingerprint changes when a task version or an
   evidence row changes, and is stable otherwise.
4. `tests/e2e/flows/test_cli.py` (extend) — `generate-bast` produces a document containing the
   expected V1 section titles.

Then run the real end-to-end check: import → upload → resume → generate → compare with the V1
reference document.

### Known pre-existing failure

`tests/unit/flows/test_pipelines.py::test_current_period_uses_jakarta_calendar_independent_of_source_offset`
fails today (`lookback_months` 1 ≠ 0) and is unrelated to this work. Do not let it mask new
regressions; leave it failing unless the user asks for it to be fixed.

---

## 5. Decisions taken (2026-08-19)

1. **`Pelaksanaan Pekerjaan`** — follow V1: the section stays omitted. Do not implement it, do not
   treat the V1 `NameError` as a bug to fix.
2. **PDF delivery over WhatsApp** — the user receives a finished PDF file in the chat, not a link.
   Parity is kept by running V1's own jsPDF exporter inside headless Chromium (§3.8) rather than
   substituting a different renderer. This is the plan's one accepted new dependency.
3. **IoT SLA / `Detail Respon Resolution Time`** — backlog, out of scope. Render a
   "data SLA belum tersedia" placeholder; recovery notes are in §3.8.
4. **Evidence file storage** — PostgreSQL `bytea`. Supabase and other object storage rejected as
   disproportionate at this scale (§3.3).
5. **Evidence submission channel** — private DM to the bot, not the group and not a web portal
   (§3.3). The group carries resume, reminder and generation status only; per-upload chatter stays
   in DM. This reverses `allow_direct_messages: false` in `config/hermes/bast-bot.yaml`, which must
   be updated in the same commit.
6. **WhatsApp identity** — one-time self-binding (Employee ID + one-time activation code) rather
   than a pre-collected phone list. No phone numbers are gathered in advance.

---

## 6. Handoff prompt for the implementation session

Copy everything below into a fresh session.

---

**Task: implement the BAST end-to-end extension described in `docs/bast-e2e-plan.md`.**

Read that document first, in full. It is the result of a dedicated audit session; follow its
architecture and work-package order rather than redesigning. Where it names a file, function or
protocol, that thing already exists — go read it before writing anything new.

Context you must respect:

- The attendance export path (`scripts/load_pama_attendance.py`, `web/csv_export.py`,
  `operations.export_attendance_report`, `bot-bridge/server.js`) is working end-to-end and is
  verified against real data. Do not refactor it. Extend around it.
- NocoDB and the OVH VPS are unreachable and will stay unreachable. Everything must run against
  local PostgreSQL (`docker` container `bast-local-pg`, port 5544), the reachable SQL Servers
  (`jiepsqco423`, `JIEPBDSQ403`), Google Sheets, and files already in the repo.
- Credentials for the SQL Servers live in `/mnt/d/Github/celerates/digital-bast/v1-prod/.env`
  (`DB_SERVER`, `DB_USERNAME`, `DB_PASSWORD`, `REDMINE_DB_SERVER`, `REDMINE_DB_USERNAME`,
  `REDMINE_DB_PASSWORD`). Use `pymssql`; the project venv is `.venv` (Python 3.12).
- `APP_DATABASE_DSN` must be exported in the environment, not written into `.env` — a direct value
  there collides with the `Settings()` tests ("duplicate secret sources").

Constraints:

- No new services. `playwright` (plus `playwright install chromium`) is the **one** approved new
  dependency, and only for driving V1's own jsPDF exporter headlessly — see §3.8. Do not add
  `weasyprint`, do not substitute Chromium's native `page.pdf()`, and do not introduce object
  storage; evidence bytes go in PostgreSQL. Ollama is optional and must stay behind `BOT_LLM_URL`;
  with it unset, behaviour is unchanged.
- The decisions in §5 are settled. In particular: `Pelaksanaan Pekerjaan` stays omitted, the IoT
  `Detail Respon Resolution Time` section renders a placeholder (SLA is backlog), and the bot sends
  the PDF file itself rather than a link.
- Business logic is deterministic and lives in `domain/`. The LLM only converts text into a
  validated command draft and never computes a reported value. When `BOT_LLM_URL` is set the LLM is
  the primary interpreter and the regex parser is the fallback — read §3.5 before implementing WP5,
  including the note on why the reverse ordering was rejected.
- V1 BAST templates are copied verbatim. Do not re-author their HTML or CSS; parity comes from
  reusing the same files with equivalent context dicts.
- `basedpyright` runs in strict mode and `ruff` selects `ALL`. Both must be clean.

Work in the order WP1 → WP2 → WP3 → WP4 → WP5. After each work package, run the checks that package
touches and make them green before moving on. Write the critical-path tests listed in the plan —
those four, not a broader suite.

When the feature set is complete, do a real end-to-end verification: import tasks for a real month,
activate a number over DM and upload an evidence image through it, ask the group for the resume,
generate the BAST,
confirm the PDF actually arrives in WhatsApp as a document, and compare the rendered sections
against the V1 reference
(`/mnt/d/Github/celerates/digital-bast/v1-prod/templates/all_report_template.html` and its section
templates). Fix every test and runtime failure you find until the whole path is green.

Report honestly: if a section cannot be made identical to V1, say which one and why, rather than
approximating it silently. `tests/unit/flows/test_pipelines.py::test_current_period_uses_jakarta_calendar_independent_of_source_offset`
already fails before your changes — leave it, but do not let it hide new failures.
