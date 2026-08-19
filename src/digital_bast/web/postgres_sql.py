REPORT = """
    SELECT external_id, work_date,
           COALESCE(payload->>'title', payload->>'activity', external_id) AS title,
           COALESCE(payload->>'status', '') AS status,
           COALESCE(payload->>'achievement', '') AS achievement
    FROM durable_records
    WHERE entity_kind IN ('task', 'timesheet')
      AND EXTRACT(YEAR FROM work_date) = %s
      AND EXTRACT(MONTH FROM work_date) = %s
      AND ((%s = 'iotoperation' AND payload->>'category' = 'IoT Operations')
           OR (%s = 'developer' AND COALESCE(payload->>'category', '') <> 'IoT Operations'))
      AND (NOT %s OR COALESCE(payload->>'achievement', '') <> '')
    ORDER BY work_date, external_id
"""

EMPLOYEES = """
    SELECT DISTINCT
           COALESCE(
               payload->>'full_name', payload->>'name', payload->>'employee_id'
           ) AS name,
           COALESCE(payload->>'role', 'Unassigned') AS role
    FROM durable_records
    WHERE payload ? 'employee_id'
    ORDER BY name
"""

ATTENDANCE = """
    SELECT payload->>'employee_id' AS employee_id,
           COALESCE(
               payload->>'full_name', payload->>'name', payload->>'employee_id'
           ) AS full_name,
           work_date,
           COALESCE(payload->>'shift', payload->>'shift_name', '') AS shift,
           COALESCE(payload->>'schedule_in', '') AS schedule_in,
           COALESCE(payload->>'schedule_out', '') AS schedule_out,
           COALESCE(payload->>'attendance_code', '') AS attendance_code,
           COALESCE(payload->>'check_in', payload->>'start_at', '') AS check_in,
           COALESCE(payload->>'check_out', payload->>'end_at', '') AS check_out,
           COALESCE(payload->>'notes', payload->>'remarks', '') AS notes
    FROM durable_records
    WHERE entity_kind = 'attendance'
      AND work_date BETWEEN %s AND %s
      AND payload->>'employee_id' LIKE 'MTG-TF/%'
      AND (
          cardinality(%s::text[]) = 0
          OR COALESCE(
              payload->>'full_name', payload->>'name', payload->>'employee_id'
          ) = ANY(%s::text[])
      )
    ORDER BY work_date, full_name
"""

ATTENDANCE_LEGACY = """
    SELECT payload
    FROM durable_records
    WHERE entity_kind = 'attendance'
      AND work_date BETWEEN %s AND %s
      AND payload->>'role' = %s
      -- Real employee_id values are always "MTG-TF/...". Test fixtures
      -- (tests/integration/test_postgres.py inserts a raw hex employee_id
      -- named "Owner Test" against whatever database the test DSN points
      -- at) must never leak into a real attendance export just because
      -- they share a role.
      AND payload->>'employee_id' LIKE 'MTG-TF/%'
    ORDER BY payload->>'full_name', work_date
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
