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


def test_a_dropped_character_still_resolves_when_unambiguous() -> None:
    # "LJIMT2402" instead of "LJIMT24002" -- a missing digit, the kind of
    # slip that's easy to make typing an NRP on a phone keyboard. There's
    # only one employee close enough to guess at, so it resolves; the
    # YA/BUKAN confirmation afterward is the real safety check.
    employee = resolve_employee_by_nrp("LJIMT2402", ROSTER)
    assert employee is not None
    assert employee.name == "Yoses Dwi Maheswara"


def test_a_mistyped_character_still_resolves_when_unambiguous() -> None:
    employee = resolve_employee_by_nrp("LJIMT24003", ROSTER)
    assert employee is not None
    assert employee.name == "Yoses Dwi Maheswara"


def test_refuses_to_guess_when_a_typo_is_equally_close_to_two_employees() -> None:
    # "LJIMT25002" is one character away from *both* LJIMT24002 and
    # LJIMT25004 -- picking either would mean showing the wrong person's
    # confirmation prompt. No unique closest match means no guess at all,
    # same as exact matching already refuses an ambiguous exact match.
    assert resolve_employee_by_nrp("LJIMT25002", ROSTER) is None
