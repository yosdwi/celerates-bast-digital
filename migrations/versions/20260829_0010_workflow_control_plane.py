"""Workflow authorization, PMO WhatsApp linking, rebind, and BAST audit.

Roles are never inferred from a WhatsApp number. Admin provisions PMO access
through TalentOps Web, then issues a one-time WhatsApp activation token. Talent
number changes are auditable rebind requests reviewed by the shared PMO pool.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0010"
down_revision: str | None = "20260829_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE workflow_operators (
            email                   text PRIMARY KEY,
            display_name            text NOT NULL,
            role                    text NOT NULL CHECK (role IN ('admin', 'pmo')),
            scope_key               text NOT NULL DEFAULT 'default',
            active                  boolean NOT NULL DEFAULT TRUE,
            can_approve_attendance  boolean NOT NULL DEFAULT TRUE,
            can_approve_rebind      boolean NOT NULL DEFAULT TRUE,
            can_generate_bast       boolean NOT NULL DEFAULT TRUE,
            whatsapp_notify         boolean NOT NULL DEFAULT FALSE,
            created_by              text NOT NULL,
            created_at              timestamptz NOT NULL DEFAULT now(),
            updated_at              timestamptz NOT NULL DEFAULT now()
        );

        CREATE INDEX ix_workflow_operators_scope_active
            ON workflow_operators (scope_key, active, role);

        CREATE TABLE pmo_whatsapp_invites (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            operator_email  text NOT NULL REFERENCES workflow_operators(email) ON DELETE CASCADE,
            token_hash      text NOT NULL UNIQUE,
            expires_at      timestamptz NOT NULL,
            issued_by       text NOT NULL,
            issued_at       timestamptz NOT NULL DEFAULT now(),
            used_at         timestamptz,
            used_by_jid     text
        );

        CREATE INDEX ix_pmo_whatsapp_invites_operator
            ON pmo_whatsapp_invites (operator_email, issued_at DESC);

        CREATE TABLE wa_operator_identity (
            wa_jid          text PRIMARY KEY,
            operator_email  text NOT NULL UNIQUE
                REFERENCES workflow_operators(email) ON DELETE CASCADE,
            linked_at       timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE identity_rebind_requests (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            employee_id       text NOT NULL REFERENCES employees(employee_id) ON UPDATE CASCADE,
            old_wa_jid        text NOT NULL,
            new_wa_jid        text NOT NULL,
            scope_key         text NOT NULL DEFAULT 'default',
            status            text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected')),
            requested_at      timestamptz NOT NULL DEFAULT now(),
            reviewed_by       text,
            reviewed_at       timestamptz,
            rejection_reason  text
        );

        CREATE UNIQUE INDEX uq_identity_rebind_pending_employee
            ON identity_rebind_requests (employee_id)
            WHERE status = 'pending';
        CREATE UNIQUE INDEX uq_identity_rebind_pending_new_jid
            ON identity_rebind_requests (new_wa_jid)
            WHERE status = 'pending';
        CREATE INDEX ix_identity_rebind_queue
            ON identity_rebind_requests (scope_key, status, requested_at);

        ALTER TABLE bot_conversations
            ADD COLUMN pending_rebind_employee_id text;

        CREATE TABLE workflow_notification_settings (
            scope_key                    text PRIMARY KEY,
            attendance_immediate         boolean NOT NULL DEFAULT FALSE,
            rebind_immediate             boolean NOT NULL DEFAULT FALSE,
            digest_enabled               boolean NOT NULL DEFAULT TRUE,
            digest_hour                  smallint NOT NULL DEFAULT 9
                CHECK (digest_hour BETWEEN 0 AND 23),
            deadline_reminder_days       smallint[] NOT NULL DEFAULT ARRAY[7,3,1]::smallint[],
            updated_by                   text NOT NULL,
            updated_at                   timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE bast_generation_audit (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            report_type       text NOT NULL CHECK (report_type IN ('developer', 'iotoperation')),
            year              integer NOT NULL,
            month             integer NOT NULL CHECK (month BETWEEN 1 AND 12),
            mode              text NOT NULL CHECK (mode IN ('preview', 'final')),
            forced            boolean NOT NULL DEFAULT FALSE,
            force_reason      text,
            readiness_state   text NOT NULL,
            blockers          jsonb NOT NULL DEFAULT '[]'::jsonb,
            generated_by      text NOT NULL,
            artifact_name     text,
            fingerprint       text,
            created_at        timestamptz NOT NULL DEFAULT now(),
            CHECK (NOT forced OR (force_reason IS NOT NULL AND length(trim(force_reason)) > 0))
        );

        CREATE INDEX ix_bast_generation_audit_period
            ON bast_generation_audit (year, month, report_type, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_bast_generation_audit_period;
        DROP TABLE IF EXISTS bast_generation_audit;
        DROP TABLE IF EXISTS workflow_notification_settings;
        ALTER TABLE bot_conversations DROP COLUMN IF EXISTS pending_rebind_employee_id;
        DROP INDEX IF EXISTS ix_identity_rebind_queue;
        DROP INDEX IF EXISTS uq_identity_rebind_pending_new_jid;
        DROP INDEX IF EXISTS uq_identity_rebind_pending_employee;
        DROP TABLE IF EXISTS identity_rebind_requests;
        DROP TABLE IF EXISTS wa_operator_identity;
        DROP INDEX IF EXISTS ix_pmo_whatsapp_invites_operator;
        DROP TABLE IF EXISTS pmo_whatsapp_invites;
        DROP INDEX IF EXISTS ix_workflow_operators_scope_active;
        DROP TABLE IF EXISTS workflow_operators;
        """
    )
