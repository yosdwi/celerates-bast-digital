from __future__ import annotations

from digital_bast.bot.identity import resolve_employee_by_nrp
from digital_bast.domain.models import Employee, EmployeeId, EmployeeRole

ROSTER = (
    Employee(
        EmployeeId("MTG-TF/2024020213"), "LJIMT24002", "Yoses Dwi Maheswara", EmployeeRole.DEVELOPER
    ),
    Employee(EmployeeId("MTG-TF/2025020305"), "LJIMT25004", "Aris Purnomo", EmployeeRole.DEVELOPER),
)


def test_resolves_exact_nrp_case_insensitively() -> None:
    employee = resolve_employee_by_nrp("ljimt24002", ROSTER)
    assert employee is not None
    assert employee.name == "Yoses Dwi Maheswara"


def test_free_text_that_is_not_an_nrp_resolves_to_nothing() -> None:
    assert resolve_employee_by_nrp("aku mau upload evidence", ROSTER) is None


def test_blank_input_resolves_to_nothing() -> None:
    assert resolve_employee_by_nrp("   ", ROSTER) is None
