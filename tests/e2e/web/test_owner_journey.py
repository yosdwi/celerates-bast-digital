from tests.unit.web.test_security_routes import login, make_client


def test_owner_can_login_use_attendance_and_logout() -> None:
    client, _, sessions, _ = make_client()

    login(client)
    dashboard = client.get("/admin/")
    csrf = next(iter(sessions.records.values())).csrf_token
    attendance = client.post(
        "/admin/attendance-celerates/employee-data",
        data={
            "employee": "Alice",
            "start_date": "2026-08-01",
            "end_date": "2026-08-01",
            "_csrf_token": csrf,
        },
    )
    logout = client.post("/admin/auth/logout", data={"_csrf_token": csrf}, follow_redirects=False)
    after_logout = client.get("/admin/", follow_redirects=False)

    assert dashboard.status_code == 200
    assert attendance.json()["count"] == 1
    assert logout.status_code == 303
    assert after_logout.status_code == 303
