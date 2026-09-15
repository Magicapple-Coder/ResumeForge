"""Add assistant skill packs and their knowledge files.

Revision ID: 0007_assistant_skills
Revises: 0006_chat_conversation_flags
Create Date: 2026-09-15
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_assistant_skills"
down_revision: str | Sequence[str] | None = "0006_chat_conversation_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "assistant_skill" not in tables:
        op.create_table(
            "assistant_skill",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("source_name", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_assistant_skill_name", "assistant_skill", ["name"], unique=True)

    tables = set(sa.inspect(bind).get_table_names())
    if "assistant_skill_file" not in tables:
        op.create_table(
            "assistant_skill_file",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("skill_id", sa.Integer(), nullable=False),
            sa.Column("path", sa.String(length=255), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["skill_id"], ["assistant_skill.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_assistant_skill_file_skill_id", "assistant_skill_file", ["skill_id"], unique=False
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "assistant_skill_file" in tables:
        op.drop_index("ix_assistant_skill_file_skill_id", table_name="assistant_skill_file")
        op.drop_table("assistant_skill_file")
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "assistant_skill" in tables:
        op.drop_index("ix_assistant_skill_name", table_name="assistant_skill")
        op.drop_table("assistant_skill")
