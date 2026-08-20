"""Add a dedicated field for useful recruitment information.

Revision ID: 0003_job_additional_info
Revises: 0002_indexes_resume_fk
Create Date: 2026-08-20
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_job_additional_info"
down_revision: str | Sequence[str] | None = "0002_indexes_resume_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "job" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("job")}
    if "additional_info" in columns:
        return
    op.add_column(
        "job",
        sa.Column("additional_info", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "job" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("job")}
    if "additional_info" not in columns:
        return
    op.drop_column("job", "additional_info")
