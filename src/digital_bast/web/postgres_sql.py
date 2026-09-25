# Timesheet rows only ever appeared in the 'developer' report and were always
# dropped by evidence_only -- the old jsonb query reached that outcome via
# COALESCE(payload->>'category','') <> 'IoT Operations' and
# COALESCE(payload->>'achievement','') <> '', which no timesheet payload
# satisfied. The arms below state that directly instead of inferring it from
# missing keys. Tasks always carried a numeric achievement, so evidence_only
# never excluded any of them.
REPORT = """
    WITH args AS (
        SELECT %s::int AS year, %s::int AS month,
               %s::text AS report_type, %s::bool AS evidence_only
    )
    SELECT t.record_key AS external_id, t.work_date, t.title, t.status,
           t.achievement::text AS achievement
    FROM tasks t, args
    WHERE EXTRACT(YEAR FROM t.work_date) = args.year
      AND EXTRACT(MONTH FROM t.work_date) = args.month
      AND ((args.report_type = 'iotoperation' AND t.category = 'IoT Operations')
           OR (args.report_type = 'developer' AND t.category <> 'IoT Operations'))
    UNION ALL
    SELECT s.record_key AS external_id, s.work_date, s.activity AS title,
           '' AS status, '' AS achievement
    FROM timesheets s, args
    WHERE EXTRACT(YEAR FROM s.work_date) = args.year
      AND EXTRACT(MONTH FROM s.work_date) = args.month
      AND args.report_type = 'developer'
      AND NOT args.evidence_only
    ORDER BY work_date, external_id
"""

EMPLOYEES = """
    SELECT full_name AS name, role
    FROM employees
    WHERE status = 'Active'
    ORDER BY full_name
"""

ATTENDANCE = """
    SELECT a.employee_id,
           e.full_name,
           a.work_date,
           a.shift,
           a.schedule_in,
           a.schedule_out,
           a.attendance_code,
           COALESCE(to_char(a.check_in, 'HH24:MI'), '') AS check_in,
           COALESCE(to_char(a.check_out, 'HH24:MI'), '') AS check_out,
           a.notes
    FROM attendance a
    JOIN employees e ON e.employee_id = a.employee_id
    WHERE a.work_date BETWEEN %s AND %s
      AND (
          cardinality(%s::text[]) = 0
          OR e.full_name = ANY(%s::text[])
      )
    ORDER BY a.work_date, e.full_name
"""

# The BAST renderer reads the raw attendance row directly and therefore keeps
# missing punches empty. This legacy CSV path is the only projection layer:
# an approved attendance resolution may fill a missing punch or map a verified
# absence onto the contractual schedule, without ever UPDATE-ing the client
# source-of-truth attendance row.
#
# Driven from a generated day series CROSS JOIN employees, not `attendance`:
# a day the sync never sent (e.g. an evidence-upload stub, or a day PAMA
# dropped entirely) used to vanish from the export outright rather than show
# up empty -- confirmed against real exports where IoT Operations talents
# had as few as 19 of 31 days in a cycle. An earlier version of this query
# drove off `schedules` instead of a plain day series on the (correct, for
# IoT Operations) assumption that it has near-complete day coverage -- but
# Developer role NEVER writes to `schedules` at all (confirmed: 0 rows for
# any Developer, vs. thousands for IoT Operations; pama_attendance.py's
# derive_day() only reads a roster shift_code for IoT Operations, and gives
# Developers a fixed 07:30-16:30 window instead), which made every
# Developer export come back with zero rows. A calendar day series has no
# such asymmetry.
#
# schedule_shift_name backs the shift/schedule_in/schedule_out fallback
# csv_export.py applies through the same SHIFT_LEGEND pama_attendance.py
# uses (reversed by name, not duplicated), for a day missing shift and/or
# schedule_in/out -- confirmed against real data: both "no attendance row at
# all" and "a real shift like SHIFT 2 with schedule_in/out sync never sent"
# happen independently. It's simply NULL for Developer rows (no schedules
# entry to fall back to), which csv_export.py already handles.
ATTENDANCE_LEGACY = """
    WITH days AS (
        SELECT generate_series(%s::date, %s::date, interval '1 day')::date AS work_date
    )
    SELECT jsonb_build_object(
               'employee_id', e.employee_id,
               'full_name', e.full_name,
               'work_date', d.work_date::text,
               'shift', a.shift,
               'schedule_in', a.schedule_in,
               'schedule_out', a.schedule_out,
               'schedule_shift_name', s.shift_name,
               'attendance_code', a.attendance_code,
               'check_in',
                   CASE
                       WHEN r.resolution_type = 'missing_clock_in'
                           THEN to_char(r.proposed_check_in, 'HH24:MI')
                       WHEN r.resolution_type = 'missing_both_worked'
                           THEN to_char(r.proposed_check_in, 'HH24:MI')
                       WHEN r.resolution_type = 'absence' AND e.role = 'Developer'
                           THEN '07:30'
                       WHEN r.resolution_type = 'absence' AND e.role = 'IoT Operations'
                           THEN a.schedule_in
                       ELSE COALESCE(to_char(a.check_in, 'HH24:MI'), '')
                   END,
               'check_out',
                   CASE
                       WHEN r.resolution_type = 'missing_clock_out'
                           THEN to_char(r.proposed_check_out, 'HH24:MI')
                       WHEN r.resolution_type = 'missing_both_worked'
                           THEN to_char(r.proposed_check_out, 'HH24:MI')
                       WHEN r.resolution_type = 'absence' AND e.role = 'Developer'
                           THEN CASE
                               WHEN EXTRACT(ISODOW FROM d.work_date) = 5 THEN '17:00'
                               ELSE '16:30'
                           END
                       WHEN r.resolution_type = 'absence' AND e.role = 'IoT Operations'
                           THEN a.schedule_out
                       ELSE COALESCE(to_char(a.check_out, 'HH24:MI'), '')
                   END,
               'notes', a.notes
           ) AS payload
    FROM days d
    JOIN employees e
        ON e.role = %s
       AND e.status = 'Active'
       AND (%s::text IS NULL OR e.full_name ILIKE '%%' || %s || '%%')
    LEFT JOIN attendance a ON a.employee_id = e.employee_id AND a.work_date = d.work_date
    LEFT JOIN schedules s ON s.employee_id = e.employee_id AND s.work_date = d.work_date
    LEFT JOIN LATERAL (
        SELECT resolution_type, proposed_check_in, proposed_check_out
        FROM attendance_resolution_requests rr
        WHERE rr.attendance_id = a.id
          AND rr.status = 'approved'
        ORDER BY rr.reviewed_at DESC
        LIMIT 1
    ) r ON true
    ORDER BY e.full_name, d.work_date
"""

INSERT_PLAN = """
    INSERT INTO generation_plans (id, owner_id, status, plan, retention_until)
    VALUES (%s, %s, 'draft', %s, %s)
"""

UPDATE_PLAN = """
    UPDATE generation_plans
    SET plan = %s, status = %s, updated_at = now()
    WHERE id = %s
"""
