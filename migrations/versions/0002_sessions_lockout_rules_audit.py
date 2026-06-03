"""sessions, lockout, audit enrichment, rules/rule_runs, case check constraints

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-03

Mirrors the manual DDL applied to the administration schema. On a server where
these objects were already created by hand, run `alembic stamp 0002` instead of
`upgrade` (the objects exist). Fresh servers run `alembic upgrade head`.

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = lambda: sa.DateTime(timezone=True)  # noqa: E731


def upgrade() -> None:
    # --- users: failed-login / lockout state ---------------------------------
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("users", sa.Column("locked_until", _TS(), nullable=True))
    op.add_column(
        "users",
        sa.Column("must_reset_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("password_changed_at", _TS(), nullable=True))

    # --- user_sessions (refresh tokens) --------------------------------------
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("refresh_jti", sa.String(64), nullable=False),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("issued_at", _TS(), nullable=False),
        sa.Column("expires_at", _TS(), nullable=False),
        sa.Column("revoked_at", _TS(), nullable=True),
        sa.Column("last_seen_at", _TS(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_sessions_user_id", ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_user_sessions_refresh_jti", "user_sessions", ["refresh_jti"], unique=True
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])

    # --- audit_logs: enrichment ----------------------------------------------
    op.add_column("audit_logs", sa.Column("actor_id", sa.String(36), nullable=True))
    op.add_column("audit_logs", sa.Column("ip_address", postgresql.INET(), nullable=True))
    op.add_column("audit_logs", sa.Column("user_agent", sa.String(512), nullable=True))
    op.add_column("audit_logs", sa.Column("request_id", sa.String(64), nullable=True))
    op.create_foreign_key(
        "fk_audit_logs_actor_id", "audit_logs", "users", ["actor_id"], ["id"]
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])

    # --- rules ----------------------------------------------------------------
    op.create_table(
        "rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("parent_id", sa.String(36), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(32), nullable=False, server_default="Draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("schedule", sa.String(64), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("approved_by", sa.String(36), nullable=True),
        sa.Column("approved_at", _TS(), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column("disabled_at", _TS(), nullable=True),
        sa.Column("created_at", _TS(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_rules_created_by"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], name="fk_rules_approved_by"),
    )
    op.create_index("ix_rules_parent_id", "rules", ["parent_id"])
    op.create_index("ix_rules_status", "rules", ["status"])

    # --- rule_runs ------------------------------------------------------------
    op.create_table(
        "rule_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rule_id", sa.String(36), nullable=False),
        sa.Column("dag_run_id", sa.String(128), nullable=True),
        sa.Column("triggered_by", sa.String(36), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="Triggered"),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("started_at", _TS(), nullable=True),
        sa.Column("ended_at", _TS(), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("output_table", sa.String(255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", _TS(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["rules.id"], name="fk_rule_runs_rule_id"),
        sa.ForeignKeyConstraint(
            ["triggered_by"], ["users.id"], name="fk_rule_runs_triggered_by"
        ),
    )
    op.create_index("ix_rule_runs_rule_id", "rule_runs", ["rule_id"])
    op.create_index("ix_rule_runs_status", "rule_runs", ["status"])

    # --- cases: value constraints --------------------------------------------
    # Raw SQL to pin the exact constraint names (op.create_check_constraint would
    # apply the metadata naming convention and prefix them with ck_cases_...).
    op.execute(
        "ALTER TABLE cases ADD CONSTRAINT chk_cases_severity "
        "CHECK (severity IN ('low','medium','high','critical'))"
    )
    op.execute(
        "ALTER TABLE cases ADD CONSTRAINT chk_cases_status "
        "CHECK (status IN ('Open','In Progress','Resolved','Closed','Cancelled'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cases DROP CONSTRAINT chk_cases_status")
    op.execute("ALTER TABLE cases DROP CONSTRAINT chk_cases_severity")

    op.drop_table("rule_runs")
    op.drop_table("rules")

    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_constraint("fk_audit_logs_actor_id", "audit_logs", type_="foreignkey")
    op.drop_column("audit_logs", "request_id")
    op.drop_column("audit_logs", "user_agent")
    op.drop_column("audit_logs", "ip_address")
    op.drop_column("audit_logs", "actor_id")

    op.drop_table("user_sessions")

    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "must_reset_password")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
