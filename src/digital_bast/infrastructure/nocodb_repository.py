from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Final, final

import psycopg
from anyio.to_thread import run_sync
from psycopg import sql
from psycopg.rows import dict_row

from digital_bast.domain.identity import canonical_text, daily_key, holiday_key, task_key
from digital_bast.domain.models import (
    DomainRecord,
    EmployeeId,
    EntityKind,
    Holiday,
    Month,
    RecordKey,
    RecordOrigin,
    Schedule,
    Task,
    TaskCategory,
    TaskSource,
    Timesheet,
)
from digital_bast.domain.time import JAKARTA
from digital_bast.infrastructure.errors import InfrastructureError

type SqlValue = str | int | float | bool | date | datetime | None
type SqlRow = dict[str, SqlValue]

_SYSTEM_USER_EMAIL: Final = "system@system.com"
_TASKLIST_IOT_TABLE: Final = "Tasklist IoT Operations"
_TASKLIST_DEVELOPER_TABLE: Final = "Tasklist Developer"
_CALENDAR_TABLE: Final = "Calendar"
_SCHEDULE_TABLE: Final = "Schedule Shifting"
_TIMESHEET_TABLE: Final = "timesheet"
_TASK_TABLES: Final = (_TASKLIST_IOT_TABLE, _TASKLIST_DEVELOPER_TABLE)


def _to_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    jakarta_value = value if value.tzinfo is not None else value.replace(tzinfo=JAKARTA)
    return jakarta_value.astimezone(UTC).replace(tzinfo=None)


def _from_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).astimezone(JAKARTA)


def _is_locked(row: SqlRow, system_user_id: str) -> bool:
    updated_by = row.get("updated_by")
    if updated_by is not None and updated_by != system_user_id:
        return True
    return str(row.get("IsManualEdit") or "").strip().lower() == "true"


def _origin(locked: bool) -> RecordOrigin:
    return RecordOrigin.MANUAL if locked else RecordOrigin.PIPELINE


def _employee_id_from_id_key(row: SqlRow) -> EmployeeId:
    id_key = row.get("Id_Key")
    if id_key:
        _, _, employee_id = str(id_key).rpartition("_")
        if employee_id:
            return EmployeeId(employee_id)
    return EmployeeId("")


def _employee_id_from_link(row: SqlRow) -> EmployeeId:
    linked_id = row.get("_employee_id")
    return EmployeeId(str(linked_id)) if linked_id is not None else EmployeeId("")


def _task_table(source: TaskSource) -> str:
    return _TASKLIST_IOT_TABLE if source is TaskSource.GOOGLE_SHEET else _TASKLIST_DEVELOPER_TABLE


def _holiday_to_row(record: Holiday) -> SqlRow:
    return {
        "Unique_Key": str(record.key),
        "Date": record.work_date,
        "Description": record.name,
        "Day_Name": record.work_date.strftime("%A"),
        "Day_Type": "Libur Nasional",
    }


def _holiday_from_row(row: SqlRow, *, locked: bool) -> Holiday:
    work_date: date = row["Date"]  # type: ignore[assignment]
    return Holiday(
        key=holiday_key(work_date),
        work_date=work_date,
        name=str(row.get("Description") or ""),
        origin=_origin(locked),
    )


def _task_to_row(record: Task) -> SqlRow:
    row: SqlRow = {
        "Unique_Key": str(record.key),
        "Id_Key": f"{record.work_date.isoformat()}_{record.employee_id}",
        "Date": record.work_date,
        "Start_Date": record.work_date,
        "End_Date": record.end_date,
        "Task_List": record.title,
        "Kategori": record.issue_type or record.category.value,
        "Requestor": record.requestor,
        "Status": record.status,
        "Pencapaian": float(record.achievement),
        "PIC_Selection": record.assignee,
    }
    if record.source is TaskSource.GOOGLE_SHEET:
        row["Start_Time"] = _to_utc_naive(record.start_at)
        row["Response_Time"] = _to_utc_naive(record.response_at)
        row["Close_Time"] = _to_utc_naive(record.close_at)
    return row


def _task_from_row(table: str, row: SqlRow, *, locked: bool) -> Task:
    work_date: date = row["Date"]  # type: ignore[assignment]
    employee_id = _employee_id_from_id_key(row)
    title = str(row.get("Task_List") or "")
    source = TaskSource.GOOGLE_SHEET if table == _TASKLIST_IOT_TABLE else TaskSource.REDMINE
    default_category = (
        TaskCategory.IOT if table == _TASKLIST_IOT_TABLE else TaskCategory.CODE_QUALITY
    )
    kategori = row.get("Kategori")
    try:
        category = TaskCategory(str(kategori)) if kategori else default_category
    except ValueError:
        category = default_category
    achievement_raw = row.get("Pencapaian")
    source_id = f"{work_date.isoformat()}_{employee_id}_{canonical_text(title)}"
    issue_type = str(kategori) if source is TaskSource.GOOGLE_SHEET and kategori else None
    return Task(
        key=task_key(work_date, employee_id, title, source.value, source_id),
        employee_id=employee_id,
        work_date=work_date,
        title=title,
        requestor=str(row.get("Requestor") or ""),
        status=str(row.get("Status") or ""),
        category=category,
        source=source,
        source_id=source_id,
        assignee=str(row["PIC_Selection"]) if row.get("PIC_Selection") is not None else None,
        start_at=_from_utc_naive(row.get("Start_Time")),  # type: ignore[arg-type]
        response_at=_from_utc_naive(row.get("Response_Time")),  # type: ignore[arg-type]
        close_at=_from_utc_naive(row.get("Close_Time")),  # type: ignore[arg-type]
        end_date=row.get("End_Date"),  # type: ignore[arg-type]
        achievement=int(achievement_raw) if achievement_raw is not None else 0,
        origin=_origin(locked),
        issue_type=issue_type,
    )


def _schedule_to_row(record: Schedule) -> SqlRow:
    return {
        "Unique_Key": str(record.key),
        "Date": record.work_date,
        "Date_Shifting": record.work_date,
    }


def _schedule_from_row(row: SqlRow, *, locked: bool) -> Schedule:
    work_date: date = row["Date"]  # type: ignore[assignment]
    employee_id = _employee_id_from_link(row)
    shift_name = row.get("Shift_Name")
    return Schedule(
        key=daily_key("schedule", work_date, employee_id),
        employee_id=employee_id,
        work_date=work_date,
        shift_name=str(shift_name) if shift_name else None,
        origin=_origin(locked),
    )


def _timesheet_to_row(record: Timesheet) -> SqlRow:
    return {
        "Unique_Key": str(record.key),
        "date": record.work_date,
        "Calendar_Month": record.calendar_month,
        "activity": record.activity,
        "project_name": record.project,
        "holiday": "true" if record.is_holiday else "false",
        "remarks": record.remarks,
    }


def _timesheet_from_row(row: SqlRow, *, locked: bool) -> Timesheet:
    work_date: date = row["date"]  # type: ignore[assignment]
    employee_id = _employee_id_from_link(row)
    return Timesheet(
        key=daily_key("timesheet", work_date, employee_id),
        employee_id=employee_id,
        work_date=work_date,
        calendar_month=str(row.get("Calendar_Month") or ""),
        activity=str(row.get("activity") or ""),
        project=str(row.get("project_name") or ""),
        is_holiday=str(row.get("holiday") or "").strip().lower() == "true",
        remarks=str(row.get("remarks") or ""),
        attendance_key=None,
        task_keys=(),
        origin=_origin(locked),
    )


@final
class NocoDBDomainRepository:
    def __init__(self, dsn: str, base_id: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn: str = dsn
        self._base_id: str = base_id
        self._connect_timeout_seconds: int = connect_timeout_seconds
        self._system_user_id: str | None = None

    async def get(self, key: RecordKey) -> DomainRecord | None:
        return await run_sync(self._get, key)

    async def upsert(self, record: DomainRecord) -> None:
        await run_sync(self._upsert, record)

    async def list_month(self, kind: EntityKind, period: Month) -> tuple[DomainRecord, ...]:
        return await run_sync(self._list_month, kind, period)

    def _connect(self) -> psycopg.Connection[SqlRow]:
        return psycopg.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_seconds,
            row_factory=dict_row,
        )

    def _resolve_system_user_id(self, cursor: psycopg.Cursor[SqlRow]) -> str:
        if self._system_user_id is not None:
            return self._system_user_id
        _ = cursor.execute(
            "SELECT id FROM nc_users_v2 WHERE email = %s",
            (_SYSTEM_USER_EMAIL,),
        )
        row = cursor.fetchone()
        if row is None:
            raise InfrastructureError(service="nocodb", operation="resolve_system_user")
        self._system_user_id = str(row["id"])
        return self._system_user_id

    def _table(self, name: str) -> sql.Composed:
        return sql.SQL("{}.{}").format(sql.Identifier(self._base_id), sql.Identifier(name))

    def _schedule_select(self, where_clause: sql.Composable) -> sql.Composed:
        return sql.SQL(
            'SELECT s.*, ms."Shift_Name", el."Employee Data_id" AS "_employee_id" '
            "FROM {schedule} s "
            'LEFT JOIN {shift_link} l ON l."Schedule Shifting_id" = s.id '
            'LEFT JOIN {master_shift} ms ON ms.id = l."Shift Setup_id" '
            'LEFT JOIN {employee_link} el ON el."Schedule Shifting_id" = s.id '
            "WHERE {where}"
        ).format(
            schedule=self._table(_SCHEDULE_TABLE),
            shift_link=self._table("_nc_m2m_Schedule Shifti_Shift Setup"),
            master_shift=self._table("Master Shift"),
            employee_link=self._table("_nc_m2m_Schedule Shifti_Employee Data"),
            where=where_clause,
        )

    def _timesheet_select(self, where_clause: sql.Composable) -> sql.Composed:
        return sql.SQL(
            'SELECT t.*, el."Employee Data_id" AS "_employee_id" '
            "FROM {timesheet} t "
            "LEFT JOIN {employee_link} el ON el.timesheet_id = t.id "
            "WHERE {where}"
        ).format(
            timesheet=self._table(_TIMESHEET_TABLE),
            employee_link=self._table("_nc_m2m_timesheet_Employee Data"),
            where=where_clause,
        )

    def _select_by_key(
        self,
        cursor: psycopg.Cursor[SqlRow],
        table: str,
        key: RecordKey,
    ) -> SqlRow | None:
        if table == _SCHEDULE_TABLE:
            statement = self._schedule_select(sql.SQL('s."Unique_Key" = %s'))
        elif table == _TIMESHEET_TABLE:
            statement = self._timesheet_select(sql.SQL('t."Unique_Key" = %s'))
        else:
            statement = sql.SQL('SELECT * FROM {table} WHERE "Unique_Key" = %s').format(
                table=self._table(table)
            )
        _ = cursor.execute(statement, (str(key),))
        return cursor.fetchone()

    def _get(self, key: RecordKey) -> DomainRecord | None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                system_user_id = self._resolve_system_user_id(cursor)
                return self._get_with_cursor(cursor, key, system_user_id)
        except psycopg.Error as error:
            raise InfrastructureError(
                service="nocodb", operation="get_domain_record"
            ) from error

    def _get_with_cursor(
        self, cursor: psycopg.Cursor[SqlRow], key: RecordKey, system_user_id: str
    ) -> DomainRecord | None:
        kind = key.split(":", 1)[0]
        if kind == "task":
            return self._get_task(cursor, key, system_user_id)
        if kind == "attendance":
            return None
        table_and_mapper = {
            "holiday": (_CALENDAR_TABLE, _holiday_from_row),
            "schedule": (_SCHEDULE_TABLE, _schedule_from_row),
            "timesheet": (_TIMESHEET_TABLE, _timesheet_from_row),
        }.get(kind)
        if table_and_mapper is None:
            raise InfrastructureError(service="nocodb", operation="get_domain_record")
        table, mapper = table_and_mapper
        row = self._select_by_key(cursor, table, key)
        if row is None:
            return None
        return mapper(row, locked=_is_locked(row, system_user_id))

    def _get_task(
        self, cursor: psycopg.Cursor[SqlRow], key: RecordKey, system_user_id: str
    ) -> Task | None:
        for table in _TASK_TABLES:
            row = self._select_by_key(cursor, table, key)
            if row is not None:
                return _task_from_row(table, row, locked=_is_locked(row, system_user_id))
        return None

    def _write_row(
        self,
        cursor: psycopg.Cursor[SqlRow],
        table: str,
        key: RecordKey,
        columns: SqlRow,
        system_user_id: str,
    ) -> int | None:
        column_names = list(columns)
        set_clause = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(name)) for name in column_names
        )
        manual_guard = sql.SQL('("updated_by" IS NULL OR "updated_by" = %s)')
        if table == _TIMESHEET_TABLE:
            manual_guard = sql.SQL(
                '{guard} AND ("IsManualEdit" IS NULL OR "IsManualEdit" <> \'true\')'
            ).format(guard=manual_guard)
        update_statement = sql.SQL(
            'UPDATE {table} SET {set_clause}, "updated_by" = %s, "updated_at" = now() '
            'WHERE "Unique_Key" = %s AND {manual_guard} RETURNING id'
        ).format(table=self._table(table), set_clause=set_clause, manual_guard=manual_guard)
        update_params = (
            *columns.values(),
            system_user_id,
            str(key),
            system_user_id,
        )
        _ = cursor.execute(update_statement, update_params)
        updated_row = cursor.fetchone()
        if updated_row is not None:
            return int(updated_row["id"])

        exists_statement = sql.SQL('SELECT 1 FROM {table} WHERE "Unique_Key" = %s').format(
            table=self._table(table)
        )
        _ = cursor.execute(exists_statement, (str(key),))
        if cursor.fetchone() is not None:
            return None

        insert_columns = [*column_names, "updated_by", "created_at", "updated_at"]
        insert_statement = sql.SQL(
            "INSERT INTO {table} ({columns}) VALUES ({placeholders}, %s, now(), now()) "
            "RETURNING id"
        ).format(
            table=self._table(table),
            columns=sql.SQL(", ").join(sql.Identifier(name) for name in insert_columns),
            placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in column_names),
        )
        insert_params = (*columns.values(), system_user_id)
        _ = cursor.execute(insert_statement, insert_params)
        inserted_row = cursor.fetchone()
        return int(inserted_row["id"]) if inserted_row is not None else None

    def _ensure_employee_link(
        self,
        cursor: psycopg.Cursor[SqlRow],
        m2m_table: str,
        entity_column: str,
        entity_id: int,
        employee_id: str,
    ) -> None:
        statement = sql.SQL(
            'INSERT INTO {table} ("Employee Data_id", {entity_column}) VALUES (%s, %s) '
            "ON CONFLICT DO NOTHING"
        ).format(table=self._table(m2m_table), entity_column=sql.Identifier(entity_column))
        _ = cursor.execute(statement, (int(employee_id), entity_id))

    def _link_timesheet_tasks(
        self,
        cursor: psycopg.Cursor[SqlRow],
        timesheet_id: int,
        task_keys: tuple[RecordKey, ...],
    ) -> None:
        task_links = (
            (
                _TASKLIST_IOT_TABLE,
                "_nc_m2m_timesheet_Tasklist IoT Op",
                "Tasklist IoT Operations_id",
            ),
            (
                _TASKLIST_DEVELOPER_TABLE,
                "_nc_m2m_timesheet_Tasklist Develo1",
                "Tasklist Developer_id",
            ),
        )
        for record_key in task_keys:
            for table, m2m_table, entity_column in task_links:
                select_statement = sql.SQL(
                    'SELECT id FROM {table} WHERE "Unique_Key" = %s'
                ).format(table=self._table(table))
                _ = cursor.execute(select_statement, (str(record_key),))
                row = cursor.fetchone()
                if row is None:
                    continue
                link_statement = sql.SQL(
                    "INSERT INTO {m2m} ({entity_column}, timesheet_id) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING"
                ).format(
                    m2m=self._table(m2m_table), entity_column=sql.Identifier(entity_column)
                )
                _ = cursor.execute(link_statement, (int(row["id"]), timesheet_id))
                break

    def _upsert(self, record: DomainRecord) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                system_user_id = self._resolve_system_user_id(cursor)
                match record:
                    case Holiday():
                        self._write_row(
                            cursor, _CALENDAR_TABLE, record.key, _holiday_to_row(record),
                            system_user_id,
                        )
                    case Task():
                        table = _task_table(record.source)
                        self._write_row(
                            cursor, table, record.key, _task_to_row(record), system_user_id
                        )
                    case Schedule():
                        row_id = self._write_row(
                            cursor, _SCHEDULE_TABLE, record.key, _schedule_to_row(record),
                            system_user_id,
                        )
                        if row_id is not None:
                            self._ensure_employee_link(
                                cursor,
                                "_nc_m2m_Schedule Shifti_Employee Data",
                                "Schedule Shifting_id",
                                row_id,
                                record.employee_id,
                            )
                    case Timesheet():
                        row_id = self._write_row(
                            cursor, _TIMESHEET_TABLE, record.key, _timesheet_to_row(record),
                            system_user_id,
                        )
                        if row_id is not None:
                            self._ensure_employee_link(
                                cursor,
                                "_nc_m2m_timesheet_Employee Data",
                                "timesheet_id",
                                row_id,
                                record.employee_id,
                            )
                            self._link_timesheet_tasks(cursor, row_id, record.task_keys)
                    case _:
                        raise InfrastructureError(
                            service="nocodb", operation="upsert_domain_record"
                        )
                connection.commit()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="nocodb", operation="upsert_domain_record"
            ) from error

    def _list_month(self, kind: EntityKind, period: Month) -> tuple[DomainRecord, ...]:
        if kind is EntityKind.ATTENDANCE:
            return ()
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                system_user_id = self._resolve_system_user_id(cursor)
                if kind is EntityKind.HOLIDAY:
                    return self._list_holidays(cursor, period, system_user_id)
                if kind is EntityKind.SCHEDULE:
                    return self._list_schedules(cursor, period, system_user_id)
                if kind is EntityKind.TIMESHEET:
                    return self._list_timesheets(cursor, period, system_user_id)
                if kind is EntityKind.TASK:
                    return self._list_tasks(cursor, period, system_user_id)
                raise InfrastructureError(service="nocodb", operation="list_month")
        except psycopg.Error as error:
            raise InfrastructureError(service="nocodb", operation="list_month") from error

    def _month_range(
        self,
        cursor: psycopg.Cursor[SqlRow],
        table: str,
        date_column: str,
        period: Month,
    ) -> list[SqlRow]:
        statement = sql.SQL(
            "SELECT * FROM {table} WHERE {date_column} >= make_date(%s, %s, 1) "
            "AND {date_column} < make_date(%s, %s, 1) + interval '1 month'"
        ).format(table=self._table(table), date_column=sql.Identifier(date_column))
        _ = cursor.execute(
            statement, (period.year, period.month, period.year, period.month)
        )
        return cursor.fetchall()

    def _list_holidays(
        self, cursor: psycopg.Cursor[SqlRow], period: Month, system_user_id: str
    ) -> tuple[DomainRecord, ...]:
        rows = self._month_range(cursor, _CALENDAR_TABLE, "Date", period)
        return tuple(
            _holiday_from_row(row, locked=_is_locked(row, system_user_id)) for row in rows
        )

    def _list_schedules(
        self, cursor: psycopg.Cursor[SqlRow], period: Month, system_user_id: str
    ) -> tuple[DomainRecord, ...]:
        statement = self._schedule_select(
            sql.SQL(
                's."Date" >= make_date(%s, %s, 1) AND s."Date" < '
                "make_date(%s, %s, 1) + interval '1 month'"
            )
        )
        _ = cursor.execute(
            statement, (period.year, period.month, period.year, period.month)
        )
        rows = cursor.fetchall()
        return tuple(
            _schedule_from_row(row, locked=_is_locked(row, system_user_id)) for row in rows
        )

    def _list_timesheets(
        self, cursor: psycopg.Cursor[SqlRow], period: Month, system_user_id: str
    ) -> tuple[DomainRecord, ...]:
        statement = self._timesheet_select(
            sql.SQL(
                't."date" >= make_date(%s, %s, 1) AND t."date" < '
                "make_date(%s, %s, 1) + interval '1 month'"
            )
        )
        _ = cursor.execute(
            statement, (period.year, period.month, period.year, period.month)
        )
        rows = cursor.fetchall()
        return tuple(
            _timesheet_from_row(row, locked=_is_locked(row, system_user_id)) for row in rows
        )

    def _list_tasks(
        self, cursor: psycopg.Cursor[SqlRow], period: Month, system_user_id: str
    ) -> tuple[DomainRecord, ...]:
        records: list[DomainRecord] = []
        for table in _TASK_TABLES:
            rows = self._month_range(cursor, table, "Date", period)
            records.extend(
                _task_from_row(table, row, locked=_is_locked(row, system_user_id))
                for row in rows
            )
        return tuple(records)
