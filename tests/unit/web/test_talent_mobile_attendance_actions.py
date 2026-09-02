import digital_bast.web.talent_mobile_router as mobile_router
from digital_bast.bot.attendance_resolution import AbsenceType, ResolutionType


def test_missing_both_accepts_cuti_and_sakit_without_clock_values() -> None:
    for action, expected_absence in (
        ("cuti", AbsenceType.CUTI),
        ("sakit", AbsenceType.SAKIT),
    ):
        resolution_type, check_in, check_out, absence = mobile_router._resolution_shape(  # noqa: SLF001
            "missing_both",
            action,
            None,
            None,
        )

        assert resolution_type is ResolutionType.ABSENCE
        assert check_in is None
        assert check_out is None
        assert absence is expected_absence
