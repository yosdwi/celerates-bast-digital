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

ATTENDANCE_LEGACY = """
    SELECT jsonb_build_object(
               'employee_id', a.employee_id,
               'full_name', e.full_name,
               'work_date', a.work_date::text,
               'shift', a.shift,
               'schedule_in', a.schedule_in,
               'schedule_out', a.schedule_out,
               'attendance_code', a.attendance_code,
               'check_in', COALESCE(to_char(a.check_in, 'HH24:MI'), ''),
               'check_out', COALESCE(to_char(a.check_out, 'HH24:MI'), ''),
               'notes', a.notes
           ) AS payload
    FROM attendance a
    JOIN employees e ON e.employee_id = a.employee_id
    WHERE a.work_date BETWEEN %s AND %s
      AND e.role = %s
    ORDER BY e.full_name, a.work_date
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
