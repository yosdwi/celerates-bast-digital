from __future__ import annotations

from digital_bast.infrastructure.legacy_pic import LegacyIoTPicUpdater


async def test_update_executes_safe_direct_relation_insert() -> None:
    statements: list[str] = []

    def execute(statement: str) -> int:
        statements.append(statement)
        return 3

    updater = LegacyIoTPicUpdater("postgresql://unused", executor=execute)

    inserted = await updater.update()

    assert inserted == 3
    assert len(statements) == 1
    statement = statements[0]
    assert '"Tasklist IoT Operations"' in statement
    assert '"PIC_Selection"' in statement
    assert '"Employee Data"' in statement
    assert '"Employee Data_id"' in statement
    assert '"_nc_m2m_tasklist_develo_Employee Data"' in statement
    assert "SELECT DISTINCT" in statement
    assert 'employee."Employee_Name" % a."PIC_Selection"' in statement
    assert "JOIN LATERAL" in statement
    assert "ORDER BY similarity(" in statement
    assert "LIMIT 1" in statement
    assert "b.id IS NOT NULL" in statement
    assert "LEFT JOIN" in statement
    assert "c.tasklist_developer_copy_id IS NULL" in statement
    assert "tasklist_developer_copy_id" in statement
    assert "ON CONFLICT DO NOTHING" in statement
