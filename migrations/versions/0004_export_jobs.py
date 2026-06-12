"""bulk export jobs (export_jobs)

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-12

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("reference", sa.String(length=40), nullable=False),
        sa.Column("report_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="Queued", nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("total_rows", sa.BigInteger(), nullable=True),
        sa.Column("processed_rows", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("progress_pct", sa.Integer(), server_default="0", nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=True),
        sa.Column("file_format", sa.String(length=16), server_default="csv.gz", nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("kpis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("requested_by", sa.String(length=128), nullable=True),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_export_jobs")),
        sa.UniqueConstraint("reference", name=op.f("uq_export_jobs_reference")),
    )
    op.create_index(op.f("ix_export_jobs_status"), "export_jobs", ["status"], unique=False)
    op.create_index(
        op.f("ix_export_jobs_requested_by"), "export_jobs", ["requested_by"], unique=False
    )
    op.create_index(
        op.f("ix_export_jobs_reference"), "export_jobs", ["reference"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_export_jobs_reference"), table_name="export_jobs")
    op.drop_index(op.f("ix_export_jobs_requested_by"), table_name="export_jobs")
    op.drop_index(op.f("ix_export_jobs_status"), table_name="export_jobs")
    op.drop_table("export_jobs")
