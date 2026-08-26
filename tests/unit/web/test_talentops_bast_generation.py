from datetime import date
from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch

from digital_bast.domain.completion import DateRange
from tests.unit.web.test_talentops_routes import make_client


def test_bast_generation_requires_csrf_and_returns_pdf(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake_generate_bast(
        period: DateRange,
        report_type: str,
    ) -> tuple[Path, SimpleNamespace]:
        assert period.start == date(2026, 8, 1)
        assert period.end == date(2026, 8, 31)
        assert report_type == "iotoperation"
        path = tmp_path / "BAST_iotoperation_2026-08.pdf"
        path.write_bytes(b"%PDF-1.4\nconform-test")
        return path, SimpleNamespace(fingerprint="fingerprint-test")

    monkeypatch.setattr(
        "digital_bast.web.talentops_router.generate_bast_artifact",
        fake_generate_bast,
    )
    client = make_client(authenticated=True)
    endpoint = "/api/talentops/v1/bast/generate?year=2026&month=8&report_type=iotoperation"

    missing_csrf = client.post(endpoint)
    response = client.post(endpoint, headers={"X-CSRF-Token": "csrf-token"})

    assert missing_csrf.status_code == 403
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="BAST_iotoperation_2026-08.pdf"'
    )
    assert response.headers["x-bast-fingerprint"] == "fingerprint-test"
    assert response.content.startswith(b"%PDF-1.4")


def test_bast_generation_rejects_unknown_report_type() -> None:
    response = make_client(authenticated=True).post(
        "/api/talentops/v1/bast/generate?year=2026&month=8&report_type=shifting",
        headers={"X-CSRF-Token": "csrf-token"},
    )

    assert response.status_code == 422
