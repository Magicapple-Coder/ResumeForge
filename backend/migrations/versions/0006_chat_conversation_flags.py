"""Add pinned and favorite flags to assistant conversations.

Revision ID: 0006_chat_conversation_flags
Revises: 0005_chat_assistant
Create Date: 2026-08-22
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_chat_conversation_flags"
down_revision: str | Sequence[str] | None = "0005_chat_assistant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_conversation" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("chat_conversation")}
    # SQLite batch_alter_table recreates the parent table. With foreign keys
    # enabled, dropping that table cascades into chat_message, so use the
    # native ADD COLUMN operation for this additive migration.
    if "pinned" not in columns:
        op.add_column(
            "chat_conversation",
            sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "favorite" not in columns:
        op.add_column(
            "chat_conversation",
            sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_conversation" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("chat_conversation")}
    # Modern SQLite supports DROP COLUMN and preserves child rows. Avoid a
    # batch rebuild here for the same foreign-key cascade reason as upgrade.
    if "favorite" in columns:
        op.drop_column("chat_conversation", "favorite")
    if "pinned" in columns:
        op.drop_column("chat_conversation", "pinned")
