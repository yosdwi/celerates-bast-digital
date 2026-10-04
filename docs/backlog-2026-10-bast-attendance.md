# Backlog — BAST, attendance and tasklist findings (October 2026)

Written 2026-10-04 from the production investigation of the failed WhatsApp/web BAST exports, the September
tasklist feedback, and the attendance/timesheet questions that followed. Each item says what was observed,
why it matters, and what "done" looks like. Evidence is from the live database unless stated.

Status legend: **DONE** shipped and verified · **OPEN** not started · **WAITING** needs input from someone.

## Shipped in this round (for reference)

| Commit | What |
| --- | --- |
| `d7a81c6` | WhatsApp export no longer dies at 5 minutes: worker hands slow commands back as jobs, bridge polls; render cache; web "stale" 10 → 30 min |
| `857603e` | A task belongs to the period it **ends** in (`end_date`); tasks without `end_date` are in no period |
| `9bc3b71` | Bridge image ships `worker-client.js` (first deploy crashed on `require`) |
| `553aeaf` | Schedule-Libur day renders as Libur in the IoT BAST; readiness flags a timesheet still marked as a working day on an OFF day |
| `a6f8dda` | Readiness flags a timesheet marked OFF on a day with complete clock-in and clock-out |

Data fixes (no commit), each row set to `manual` so the sync cannot overwrite it; originals saved in `~/backups/`:
- Yoses Dwi Maheswara 2026-09-02 `check_in` = 09:06 (from the 1 PAMA export).
- Hanung Rizqi Widianto 2026-09-10 `check_in` = 07:20 and Oditya Andalas Putra 2026-09-12 `check_in` = 14:50
  (values supplied by the owner on 2026-10-04). September attendance (Log 1 PAMA) is now complete for all 17 talents.

## P1 — Attendance data is silently lost or corrupted

### B1. A clock-in can disappear and nobody can tell  — OPEN
- **Observed:** Yoses 2 Sep had `check_in` empty and `check_out` 17:29, but 1 PAMA shows IN 09:06. The row was first
  created at 10:05 that morning (consistent with an IN punch existing then). Hanung 10 Sep and Oditya 12 Sep show the
  same shape (OUT present, IN empty). Alert on all three was "Clock In kosong".
- **Cause (code):** `repositories.py` attendance upsert does `ON CONFLICT … SET check_in = EXCLUDED.check_in`. If a
  later PAMA payload has no `(IN)` punch for that day, the stored value is replaced by NULL. There is no history, so
  the earlier value cannot be recovered or even seen.
- **Why the PAMA payload may lack it is not proven.** Raw punches are not kept on the VPS (the replay poller deletes
  relay rows after success) and PAMA SQL Server is only reachable from the PAMA Windows PC.
- **Done when:** (a) an `attendance_history` table records every change of `check_in`/`check_out` with time and source;
  (b) a punch that goes from a value to NULL is kept (or at least raised as a finding) instead of silently erased;
  (c) a readiness finding "Clock In hilang setelah sebelumnya terisi" for PMO; (d) test with a payload sequence
  IN+OUT → OUT only.
- **Diagnostic still wanted:** run on the PAMA PC for NRP `JIMT24002`, 2026-09-01..03, both
  `tbl_t_att_daily` and `tbl_t_att_daily_history`, to see whether 09:06 was ever returned and with what `trans`.

### B2. Hanung (10 Sep) and Oditya (12 Sep) clock-in gaps  — DONE (data only)
- Same pattern as B1. Corrected by hand on 2026-10-04 (Hanung 07:20, Oditya 14:50). The cause (B1) is still open,
  so the next gap of this kind will need the same manual fix.

### B3. Yoses and Ovianto clock-ins around 05:20 before 16 Sep  — WAITING
- **Observed:** Yoses IN 05:18–05:28 on 3–14 Sep (8 days) then ~07:2x from 16 Sep; Ovianto 10 days before 06:00.
  The 1 PAMA export shows the same 05:xx values, so this is **in PAMA itself**, not introduced by this system.
- **Open question:** a consistent ~2 hour shift on two people looks like a device or PAMA clock/timezone issue.
  Needs PMO/PAMA to confirm whether those punches are real. Affects computed work hours in the BAST
  (Yoses 3 Sep shows 11 h 24 min effective).

## P1 — Timesheet and readiness

### T1. Fix the 7 stale timesheet rows at the source  — WAITING
- Gading Aulia 1, 22, 23, 26, 27 Sep and Oktavia Nur Azizah 1 and 30 Sep: schedule says Libur but the row still says
  `SHIFT 1`/`SHIFT 1.5`. The BAST already renders them as Libur; readiness now blocks final September BAST for both
  until the sheet remark is corrected (or PMO forces with a reason). Same for 17 Aug (Gading, Oktavia, Titin).
- **Root cause not fixed:** the timesheet sync creates the row on the 1st of the month and never updates the remark
  when the schedule changes afterwards (`version` stays 1). **Done when** the timesheet remark follows later
  schedule changes, or the schedule is the only source for OFF days.

### T2. Real hours hidden by a "Libur" timesheet  — WAITING
- Muhamad Alviani 1 Sep (clocked 06:36–15:36) and Titin Ervina Sari 9 Sep (04:23–18:15): schedule is a working day
  and attendance is complete, but the timesheet row says Libur, so the BAST drops the hours. Now a readiness finding
  for PMO; the document itself is deliberately unchanged. PMO decides which side is right and corrects the timesheet.

## P2 — Tasklist and BAST

### K1. September readiness changed after the `end_date` rule  — OPEN (communication)
- Total tasks 1251 → 1257; several developers moved from "evidence complete" to "incomplete" because Closed tasks that
  started earlier and ended in September never had evidence requested (Farhan, Hanung, Atsal, Taufiq, Ovianto,
  Ahmad Anwar). PMO and Talents need to be told before September BAST closes.
- Tasks with no `end_date` (8 Redmine tasks overall, 2 Closed in September) are excluded by decision. Consider a
  report of "Closed but no end date" so they are not invisible.

### K2. Render time  — OPEN (needs a decision)
- A September BAST renders in 4–11 minutes (Chromium captures per page in batches of 10). The renderer runs one
  render at a time. The cache and job polling remove the user-facing failure but not the cost.
- **Option:** native Chromium `page.pdf()` (seconds). Not adopted: output is vector text with different page breaks
  and may move the fit-to-page/centred layout already tuned. **Done when** a side-by-side render of one month with
  both methods is reviewed by the people who sign the BAST.

## P2 — Operations

### O1. `system status` from WhatsApp always fails  — OPEN
- `bot-worker` has no `docker` binary, so the command raises `DockerUnavailableError`. Pre-existing; unrelated to the
  export fix. Either give the worker a read-only status source or remove the command.

### O2. Four unit tests fail on a clean checkout  — OPEN
- `tests/unit/domain/test_completion.py` (3) and `tests/unit/bot/test_whatsapp.py` (1) fail on `HEAD` before any of
  the changes above (evidence-requirement tests). Either the tests or the rule is stale.

### O3. Image/deploy hygiene  — OPEN
- `whatsapp-web-session/Dockerfile` copies an explicit file list; a new `.js` file crashes the container at start.
  Replace with a glob or add a build-time `node -e require(...)` smoke step. (Hit once on 2026-10-04.)
- web, worker, runner and bridge have read-only root filesystems, so only `bot-worker` accepts `docker cp`; everything
  else needs an image and `scripts/deploy.sh` (blue/green) or `deploy-whatsapp-web-session.sh` (one WhatsApp reconnect).
- `.env` `APP_IMAGE` had been left at an old tag; it now follows each deploy. Keep it in step or any plain
  `docker compose up` recreates services from an old image.
- Raw PAMA punches are not retained (poller deletes relay rows). Consider keeping the last N days of raw payloads for
  incident analysis (see B1).
