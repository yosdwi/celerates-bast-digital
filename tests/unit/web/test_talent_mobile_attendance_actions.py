from digital_bast.bot.attendance_resolution import AbsenceType, ResolutionType
from digital_bast.web.attendance_forms import resolution_shape


def test_missing_both_accepts_cuti_and_sakit_without_clock_values() -> None:
    for action, expected_absence in (
        ("cuti", AbsenceType.CUTI),
        ("sakit", AbsenceType.SAKIT),
    ):
        resolution_type, check_in, check_out, absence = resolution_shape(
            "missing_both",
            action,
            None,
            None,
        )

        assert resolution_type is ResolutionType.ABSENCE
        assert check_in is None
        assert check_out is None
        assert absence is expected_absence


def test_missing_both_absence_accepts_optional_clock_values() -> None:
    resolution_type, check_in, check_out, absence = resolution_shape(
        "missing_both",
        "izin",
        "07:55",
        None,
    )

    assert resolution_type is ResolutionType.ABSENCE
    assert check_in is not None
    assert check_in.isoformat() == "07:55:00"
    assert check_out is None
    assert absence is AbsenceType.IZIN
