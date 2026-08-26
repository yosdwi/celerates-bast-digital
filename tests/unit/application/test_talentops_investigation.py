from digital_bast.application.talentops_investigation import (
    InvestigationEvidence,
    parse_investigation,
)


def evidence() -> tuple[InvestigationEvidence, ...]:
    return (
        InvestigationEvidence(
            id="signal:0",
            kind="signal",
            label="Attendance blocks Timesheet",
            detail="1 date requires Attendance review before Timesheet can complete.",
            domains=("attendance", "timesheet"),
        ),
        InvestigationEvidence(
            id="attendance:2026-08-01",
            kind="attendance",
            label="Attendance · 2026-08-01",
            detail="state=incomplete; record=false.",
            domains=("attendance",),
        ),
    )


def test_parse_investigation_resolves_only_known_evidence_ids() -> None:
    result = parse_investigation(
        """```json
{"title":"Related blocker","finding":"Attendance blocks Timesheet on the cited date.","impact":"Closure remains blocked.","suggested_action":"Review Attendance first.","evidence_ids":["signal:0","unknown:1","attendance:2026-08-01","signal:0"]}
```""",
        evidence(),
    )

    assert result is not None
    assert tuple(item.id for item in result.evidence) == (
        "signal:0",
        "attendance:2026-08-01",
    )


def test_parse_investigation_accepts_null_optional_sections() -> None:
    result = parse_investigation(
        '{"title":"Grounded finding","finding":"Only the cited signal is established.",'
        '"impact":null,"suggested_action":null,"evidence_ids":["signal:0"]}',
        evidence(),
    )

    assert result is not None
    assert result.impact is None
    assert result.suggested_action is None
    assert tuple(item.id for item in result.evidence) == ("signal:0",)


def test_parse_investigation_rejects_unbound_or_invalid_output() -> None:
    unknown_only = parse_investigation(
        '{"title":"Claim","finding":"Unsupported","impact":null,'
        '"suggested_action":null,"evidence_ids":["invented:1"]}',
        evidence(),
    )
    invalid_json = parse_investigation("not-json", evidence())

    assert unknown_only is None
    assert invalid_json is None
