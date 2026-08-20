"""Add favorite state to saved resumes.

Revision ID: 0004_resume_favorite
Revises: 0003_job_additional_info
Create Date: 2026-08-20
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_resume_favorite"
down_revision: str | Sequence[str] | None = "0003_job_additional_info"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "resume_record" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("resume_record")}
    if "favorite" in columns:
        return
    with op.batch_alter_table("resume_record") as batch_op:
        batch_op.add_column(
            sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "resume_record" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("resume_record")}
    if "favorite" not in columns:
        return
    with op.batch_alter_table("resume_record") as batch_op:
        batch_op.drop_column("favorite")
