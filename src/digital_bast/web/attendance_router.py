from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from digital_bast.web.contracts import (
    AttendanceEmployeeInput,
    AttendanceExportInput,
    AttendanceFilterInput,
)
from digital_bast.web.csv_export import attendance_csv
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.security import require_session, verify_csrf


def attendance_router(deps: WebDependencies, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(prefix="/admin/attendance-celerates")

    async def page(request: Request) -> HTMLResponse:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=False)
        employees = await deps.backend.employees()
        return templates.TemplateResponse(
            request,
            "attendance.html",
            {
                "user": session.user,
                "csrf_token": session.csrf_token,
                "employees": employees,
                "rows": (),
            },
        )

    router.add_api_route("", page, methods=["GET"], response_class=HTMLResponse)

    async def filtered_page(
        request: Request,
        payload: Annotated[AttendanceFilterInput, Form()],
    ) -> HTMLResponse:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(session, payload.csrf_token)
        if payload.end_date < payload.start_date:
            return templates.TemplateResponse(
                request,
                "attendance.html",
                {
                    "user": session.user,
                    "csrf_token": session.csrf_token,
                    "employees": await deps.backend.employees(),
                    "rows": (),
                    "error": "End date must not be before start date.",
                },
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        rows = await deps.backend.attendance(
            tuple(payload.employee), payload.start_date, payload.end_date
        )
        return templates.TemplateResponse(
            request,
            "attendance.html",
            {
                "user": session.user,
                "csrf_token": session.csrf_token,
                "employees": await deps.backend.employees(),
                "rows": rows,
                "start_date": payload.start_date,
                "end_date": payload.end_date,
            },
        )

    router.add_api_route("", filtered_page, methods=["POST"], response_class=HTMLResponse)

    async def employee_data(
        request: Request,
        payload: Annotated[AttendanceEmployeeInput, Form()],
    ) -> JSONResponse:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(session, payload.csrf_token)
        if payload.end_date < payload.start_date:
            return JSONResponse(
                {"error": "invalid date range"}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
            )
        rows = await deps.backend.attendance(
            (payload.employee,), payload.start_date, payload.end_date
        )
        return JSONResponse(
            {
                "employee": payload.employee,
                "records": [
                    {
                        "employee_id": row.employee_id,
                        "full_name": row.full_name,
                        "date": row.work_date.isoformat(),
                        "shift": row.shift,
                        "schedule_in": row.schedule_in,
                        "schedule_out": row.schedule_out,
                        "attendance_code": row.attendance_code,
                        "check_in": row.check_in,
                        "check_out": row.check_out,
                        "keterangan": row.notes,
                    }
                    for row in rows
                ],
                "count": len(rows),
            }
        )

    router.add_api_route("/employee-data", employee_data, methods=["POST"])

    async def export_csv(
        request: Request,
        payload: Annotated[AttendanceExportInput, Form()],
    ) -> Response:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(session, payload.csrf_token)
        if payload.end_date < payload.start_date:
            return JSONResponse(
                {"error": "invalid date range"}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
            )
        selected = tuple(payload.employee)
        if payload.role_filter and payload.role_filter != "all":
            selected = tuple(
                item.name
                for item in await deps.backend.employees()
                if item.role == payload.role_filter
            )
        rows = await deps.backend.attendance(selected, payload.start_date, payload.end_date)
        content = attendance_csv(rows)
        filename = f"attendance-{payload.start_date.isoformat()}-{payload.end_date.isoformat()}.csv"
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    router.add_api_route("/export-csv", export_csv, methods=["POST"])
    return router
