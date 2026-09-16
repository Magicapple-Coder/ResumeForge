"""Add materials, candidate jobs, profile photos and module extras.

Revision ID: 0008_materials_and_modules
Revises: 0007_assistant_skills
Create Date: 2026-09-16
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_materials_and_modules"
down_revision: str | Sequence[str] | None = "0007_assistant_skills"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(inspector: sa.Inspector, table: str) -> set[str]:
    return {item["name"] for item in inspector.get_columns(table)}


def _add_column(table: str, column: sa.Column) -> None:
    """Add one column if it is missing; SQLite only supports native ADD COLUMN."""
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return
    if column.name in _columns(inspector, table):
        return
    # SQLite 的 ADD COLUMN 要求非常量默认值也必须写成字面量；布尔/JSON 统一用
    # server_default 写入文本形态，模型侧的 Python 默认值负责新记录。
    op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 会话：归档与分组（"移动到项目"）。
    _add_column(
        "chat_conversation",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column(
        "chat_conversation",
        sa.Column("group_name", sa.String(length=64), nullable=False, server_default=""),
    )

    # 岗位：备注图片与录入方式（溯源用）。
    _add_column(
        "job",
        sa.Column("note_images", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    _add_column(
        "job",
        sa.Column("recognition_source", sa.String(length=32), nullable=False, server_default=""),
    )

    # 简历：生成时选择的版式参数与用户补充提示词。
    _add_column(
        "resume_record",
        sa.Column("template", sa.String(length=32), nullable=False, server_default="classic"),
    )
    _add_column(
        "resume_record",
        sa.Column("page_limit", sa.Integer(), nullable=False, server_default="1"),
    )
    _add_column(
        "resume_record",
        sa.Column("font_scale", sa.String(length=16), nullable=False, server_default="standard"),
    )
    _add_column(
        "resume_record",
        sa.Column("custom_instruction", sa.Text(), nullable=False, server_default=""),
    )

    # 模型配置记录：高级调整参数（可空 = 不发送，沿用服务商默认值）。
    _add_column("llm_config_record", sa.Column("top_p", sa.Float(), nullable=True))
    _add_column("llm_config_record", sa.Column("frequency_penalty", sa.Float(), nullable=True))
    _add_column("llm_config_record", sa.Column("presence_penalty", sa.Float(), nullable=True))
    _add_column("llm_config_record", sa.Column("seed", sa.Integer(), nullable=True))

    # 多张个人照片。
    if "profile_photo" not in tables:
        op.create_table(
            "profile_photo",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("profile_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("image", sa.Text(), nullable=False),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["profile_id"], ["user_profile.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_profile_photo_profile_id", "profile_photo", ["profile_id"])

    # 资料箱。
    if "material" not in tables:
        op.create_table(
            "material",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=256), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("url", sa.String(length=1024), nullable=False),
            sa.Column("files", sa.JSON(), nullable=False),
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_material_created_at", "material", ["created_at"])

    # 备选岗位。
    if "candidate_job" not in tables:
        op.create_table(
            "candidate_job",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=128), nullable=False),
            sa.Column("company", sa.String(length=128), nullable=False),
            sa.Column("raw_text", sa.Text(), nullable=False),
            sa.Column("images", sa.JSON(), nullable=False),
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("imported_job_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_candidate_job_status", "candidate_job", ["status"])
        op.create_index("ix_candidate_job_created_at", "candidate_job", ["created_at"])


def _drop_index_if_present(table: str, name: str) -> None:
    """索引可能由 create_all 之外的路径创建（或本就缺失），存在才删。"""
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name in indexes:
        op.drop_index(name, table_name=table)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "candidate_job" in tables:
        _drop_index_if_present("candidate_job", "ix_candidate_job_created_at")
        _drop_index_if_present("candidate_job", "ix_candidate_job_status")
        op.drop_table("candidate_job")
    if "material" in tables:
        _drop_index_if_present("material", "ix_material_created_at")
        op.drop_table("material")
    if "profile_photo" in tables:
        _drop_index_if_present("profile_photo", "ix_profile_photo_profile_id")
        op.drop_table("profile_photo")

    columns = _columns(inspector, "llm_config_record") if "llm_config_record" in tables else set()
    for name in ("seed", "presence_penalty", "frequency_penalty", "top_p"):
        if name in columns:
            op.drop_column("llm_config_record", name)

    columns = _columns(inspector, "resume_record") if "resume_record" in tables else set()
    for name in ("custom_instruction", "font_scale", "page_limit", "template"):
        if name in columns:
            op.drop_column("resume_record", name)

    columns = _columns(inspector, "job") if "job" in tables else set()
    for name in ("recognition_source", "note_images"):
        if name in columns:
            op.drop_column("job", name)

    columns = (
        _columns(inspector, "chat_conversation") if "chat_conversation" in tables else set()
    )
    for name in ("group_name", "archived"):
        if name in columns:
            op.drop_column("chat_conversation", name)
