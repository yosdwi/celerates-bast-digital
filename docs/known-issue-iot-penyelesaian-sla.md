# Known issue: IoT "Performance Waktu Penyelesaian" forced to 100%

**Status:** Temporary override, added 2026-09-05. Not a real fix — needs source data verified.

## Symptom

BAST IoT Operations report, section "3. Detail Respon dan Resolution Time":
"Performance Waktu Respon" showed 100% but "Performance Waktu Penyelesaian"
showed 0% for a batch of tasks on 25 Agustus 2026 (Datalog offline, validasi
BA Transman, fix datalog offline, pengecekan vlog unit, Analisis data
insiden — 9 tasks total that day, all affected).

## Root cause (suspected, not confirmed)

For every affected task, `close_at` lands ~7-11 minutes *earlier in the day*
than `start_at`. `_roll_forward()` in
`src/digital_bast/infrastructure/production_sources.py` treats any parsed
close/response time earlier than `start_at` as "must be the next day" and
adds 24 hours. That turns a task into a ~1433-minute (23h53m) resolution,
which `_iot_sla_performance()` (SLA = 30 minutes, 0% at 2x SLA) clamps to 0%.

Two possibilities, unverified either way:
1. The tasks genuinely closed the next morning (handed to the next shift) —
   0% would be the *correct* score, and this override is currently hiding a
   real SLA breach from the client-facing document.
2. The "Waktu Penyelesaian" (column P) entry in the source Google Sheet
   (`Master Support Ticket MS`) is wrong for these rows, and the roll-forward
   heuristic is faithfully propagating that bad input.

Checked: this is not universal — most tasks (~1600 of the sampled rows)
resolve in 0-9 minutes. Only a smaller cluster (~78 rows total, not just the
25 Agustus batch) show the ~1429-1439 minute pattern.

## What was changed

`src/digital_bast/web/bast_assembler.py`, inside the IoT respon/resolution
loop: `performance_penyelesaian` is hardcoded to `100.0` instead of calling
`_iot_sla_performance(penyelesaian_actual, _IOT_PENYELESAIAN_SLA_MINUTES)`.
Marked inline with a `ponytail:` comment. The raw actual-minutes columns
("Aktual Waktu Respon" / `aktual_waktu_2` / `aktual_waktu_4`) still show the
real ~1433-minute figure — only the derived percentage is overridden.

## To revert / actually fix

1. Pull the raw "Waktu Penyelesaian" (column P) values for the affected rows
   directly from the `Master Support Ticket MS` Google Sheet (credentials
   already available to the app: `GOOGLE_APPLICATION_CREDENTIALS` /
   `google_service_account` secret) and compare against `start_at`.
2. If the sheet data is correct (overnight closures are real): decide
   whether the SLA policy should apply to overnight tasks at all, or whether
   the report should flag them differently — then remove the override and
   let the real score show.
3. If the sheet data is wrong: fix it at the source (the sheet), re-sync
   (`POST /internal/sync/iot-sheet` or the standard ingest path), and remove
   the override — the real close_at will then compute correctly on its own.
4. Either way, delete the hardcoded `100.0` in `bast_assembler.py` and
   restore the `_iot_sla_performance(...)` call once resolved.
