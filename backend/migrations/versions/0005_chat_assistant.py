"""Add AI assistant conversations and message history.

Revision ID: 0005_chat_assistant
Revises: 0004_resume_favorite
Create Date: 2026-08-20
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_chat_assistant"
down_revision: str | Sequence[str] | None = "0004_resume_favorite"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "chat_conversation" not in tables:
        op.create_table(
            "chat_conversation",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=120), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_chat_conversation_updated_at", "chat_conversation", ["updated_at"], unique=False
        )

    tables = set(sa.inspect(bind).get_table_names())
    if "chat_message" not in tables:
        op.create_table(
            "chat_message",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("conversation_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("attachments", sa.JSON(), nullable=False),
            sa.Column("context", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("error", sa.Text(), nullable=False),
            sa.Column("model", sa.String(length=128), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["conversation_id"], ["chat_conversation.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_chat_message_conversation_id", "chat_message", ["conversation_id"], unique=False
        )
        op.create_index("ix_chat_message_created_at", "chat_message", ["created_at"], unique=False)


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "chat_message" in tables:
        op.drop_index("ix_chat_message_created_at", table_name="chat_message")
        op.drop_index("ix_chat_message_conversation_id", table_name="chat_message")
        op.drop_table("chat_message")
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "chat_conversation" in tables:
        op.drop_index("ix_chat_conversation_updated_at", table_name="chat_conversation")
        op.drop_table("chat_conversation")
