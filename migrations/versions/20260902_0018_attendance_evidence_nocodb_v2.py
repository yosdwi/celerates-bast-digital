"""Expose attendance evidence metadata safely to NocoDB V2.

The raw attendance_evidence table contains the uploaded binary payload. NocoDB
only needs operational metadata and the linked PMO resolution state, so expose a
read-only view that deliberately omits file_data. This keeps the existing
attendance and approval business rules unchanged while making evidence rows
usable from the V2 data workspace.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260902_0018"
down_revision: str | None = "20260901_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW attendance_evidence_nocodb_v2 AS
        SELECT
            e.id,
            e.attendance_record_key,
            e.employee_id,
            e.work_date,
            e.media_type,
            e.file_name,
            e.content_type,
            octet_length(e.file_data) AS byte_size,
            e.sha256,
            e.caption,
            e.source,
            e.whatsapp_message_id,
            e.created_at,
            e.requires_resolution,
            r.id AS resolution_request_id,
            r.resolution_type,
            r.absence_type,
            r.proposed_check_in,
            r.proposed_check_out,
            r.status AS resolution_status,
            r.submitted_at AS resolution_submitted_at,
            r.reviewed_by,
            r.reviewed_at,
            r.rejection_reason
        FROM attendance_evidence e
        LEFT JOIN attendance_resolution_requests r
            ON r.evidence_id = e.id;

        COMMENT ON VIEW attendance_evidence_nocodb_v2 IS
            'Read-only NocoDB V2 attendance evidence metadata; binary excluded.';
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nocodb_editor') THEN
                GRANT SELECT ON attendance_evidence_nocodb_v2 TO nocodb_editor;
            ELSE
                RAISE NOTICE
                    'role nocodb_editor is absent; skipping grant for attendance evidence V2 view.';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nocodb_editor') THEN
                REVOKE ALL ON attendance_evidence_nocodb_v2 FROM nocodb_editor;
            END IF;
        END $$;

        DROP VIEW attendance_evidence_nocodb_v2;
        """
    )
