"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = lambda: sa.DateTime(timezone=True)  # noqa: E731


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="Active"),
        sa.Column("permissions", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", _TS(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(64), nullable=True),
        sa.Column("department", sa.String(128), nullable=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="Active"),
        sa.Column("avatar", sa.String(16), nullable=True),
        sa.Column("last_login", _TS(), nullable=True),
        sa.Column("created_at", _TS(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_users_role_id_roles"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role_id", "users", ["role_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("target", sa.String(255), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("at", _TS(), nullable=False),
    )
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor"])
    op.create_index("ix_audit_logs_at", "audit_logs", ["at"])

    op.create_table(
        "cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reference", sa.String(32), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(32), nullable=False, server_default="Open"),
        sa.Column("owner", sa.String(128), nullable=True),
        sa.Column("owner_id", sa.String(36), nullable=True),
        sa.Column("linked_txn_id", sa.String(128), nullable=True),
        sa.Column("estimated_impact", sa.Float(), nullable=True),
        sa.Column("created_at", _TS(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cases_reference", "cases", ["reference"], unique=True)
    op.create_index("ix_cases_status", "cases", ["status"])

    op.create_table(
        "case_comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("author", sa.String(128), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", _TS(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], name="fk_case_comments_case_id_cases", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_case_comments_case_id", "case_comments", ["case_id"])

    op.create_table(
        "saved_queries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reference", sa.String(32), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("owner", sa.String(128), nullable=True),
        sa.Column("definition", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("last_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", _TS(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_saved_queries_reference", "saved_queries", ["reference"], unique=True)

    op.create_table(
        "decoders",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="Enabled"),
        sa.Column("throughput", sa.String(32), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", _TS(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "system_config",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("environment", sa.String(32), nullable=False, server_default="production"),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("sla_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("alert_email", sa.String(255), nullable=True),
        sa.Column("maintenance_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("extra", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", _TS(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "pipeline_alerts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="Open"),
        sa.Column("acknowledged_by", sa.String(128), nullable=True),
        sa.Column("created_at", _TS(), nullable=False),
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reference", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("report_type", sa.String(64), nullable=False, server_default="reconciliation"),
        sa.Column("period", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="Queued"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("file_path", sa.String(1024), nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("requested_by", sa.String(128), nullable=True),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("completed_at", _TS(), nullable=True),
        sa.Column("created_at", _TS(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_reports_reference", "reports", ["reference"], unique=True)
    op.create_index("ix_reports_status", "reports", ["status"])


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_table("pipeline_alerts")
    op.drop_table("system_config")
    op.drop_table("decoders")
    op.drop_table("saved_queries")
    op.drop_table("case_comments")
    op.drop_table("cases")
    op.drop_table("audit_logs")
    op.drop_table("users")
    op.drop_table("roles")
