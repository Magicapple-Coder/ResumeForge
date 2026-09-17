"""Add message quoting, user resume templates and the mock interview tables.

Revision ID: 0009_templates_and_interview
Revises: 0008_materials_and_modules
Create Date: 2026-09-17
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_templates_and_interview"
down_revision: str | Sequence[str] | None = "0008_materials_and_modules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(inspector: sa.Inspector, table: str) -> set[str]:
    return {item["name"] for item in inspector.get_columns(table)}


def _add_column(table: str, column: sa.Column) -> None:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return
    if column.name in _columns(inspector, table):
        return
    op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 「引用某条消息追问」：被引用的消息删掉时由服务层置空，引用它的那条留着。
    # 不加外键：SQLite 的 ADD COLUMN 不支持带约束（Alembic 会直接抛
    # "No support for ALTER of constraints"），而这一列的完整性由应用层维护。
    _add_column("chat_message", sa.Column("quoted_message_id", sa.Integer(), nullable=True))

    # 模型配置记录：接口协议与更多高级参数。
    _add_column(
        "llm_config_record",
        sa.Column("api_style", sa.String(length=16), nullable=False, server_default="openai"),
    )
    _add_column("llm_config_record", sa.Column("top_k", sa.Integer(), nullable=True))
    _add_column("llm_config_record", sa.Column("repetition_penalty", sa.Float(), nullable=True))
    _add_column(
        "llm_config_record",
        sa.Column("stop", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    _add_column("llm_config_record", sa.Column("thinking_budget", sa.Integer(), nullable=True))
    _add_column(
        "llm_config_record",
        sa.Column("extra_body", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )

    # 简历记录：格式模板名（版式覆盖）。
    _add_column(
        "resume_record",
        sa.Column("format_name", sa.String(length=64), nullable=False, server_default=""),
    )

    # 用户自制的简历模板（内置模板仍是随包的 Jinja 文件，不入库）。
    if "resume_template" not in tables:
        op.create_table(
            "resume_template",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="style"),
            sa.Column("description", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("html", sa.Text(), nullable=False, server_default=""),
            sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("source_name", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_resume_template_name", "resume_template", ["name"], unique=True)

    # 模拟面试：一场面试 + 其中的问答。
    if "interview_session" not in tables:
        op.create_table(
            "interview_session",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("job_title", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("company", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("interview_type", sa.String(length=32), nullable=False, server_default="技术面"),
            sa.Column("difficulty", sa.String(length=16), nullable=False, server_default="中级"),
            sa.Column(
                "interviewer_style", sa.String(length=32), nullable=False, server_default="严谨专业"
            ),
            sa.Column("rounds", sa.Integer(), nullable=False, server_default="6"),
            sa.Column("persona", sa.Text(), nullable=False, server_default=""),
            sa.Column("focus", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
            sa.Column("report", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("model", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_interview_session_job_id", "interview_session", ["job_id"])
        op.create_index("ix_interview_session_status", "interview_session", ["status"])
        op.create_index("ix_interview_session_created_at", "interview_session", ["created_at"])

    if "interview_message" not in tables:
        op.create_table(
            "interview_message",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("context", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="complete"),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["interview_session.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_interview_message_session_id", "interview_message", ["session_id"])
        op.create_index("ix_interview_message_created_at", "interview_message", ["created_at"])


def _drop_index_if_present(table: str, name: str) -> None:
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name in indexes:
        op.drop_index(name, table_name=table)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "interview_message" in tables:
        _drop_index_if_present("interview_message", "ix_interview_message_created_at")
        _drop_index_if_present("interview_message", "ix_interview_message_session_id")
        op.drop_table("interview_message")
    if "interview_session" in tables:
        _drop_index_if_present("interview_session", "ix_interview_session_created_at")
        _drop_index_if_present("interview_session", "ix_interview_session_status")
        _drop_index_if_present("interview_session", "ix_interview_session_job_id")
        op.drop_table("interview_session")
    if "resume_template" in tables:
        _drop_index_if_present("resume_template", "ix_resume_template_name")
        op.drop_table("resume_template")

    if "resume_record" in tables and "format_name" in _columns(inspector, "resume_record"):
        op.drop_column("resume_record", "format_name")

    columns = _columns(inspector, "llm_config_record") if "llm_config_record" in tables else set()
    for name in (
        "extra_body",
        "thinking_budget",
        "stop",
        "repetition_penalty",
        "top_k",
        "api_style",
    ):
        if name in columns:
            op.drop_column("llm_config_record", name)

    if "chat_message" in tables and "quoted_message_id" in _columns(inspector, "chat_message"):
        op.drop_column("chat_message", "quoted_message_id")
