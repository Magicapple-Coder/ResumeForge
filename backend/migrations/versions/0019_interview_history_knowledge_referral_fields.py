"""新增题库历史 / 复盘历史 / 知识库三张表 + 内推两列（D5 / 第 6、7 批的地基）。

与 ``0010`` / ``0012`` / ``0017`` / ``0018`` 一样，本次迁移**只加表、只加列**，不改既有列、
不动既有表：旧备份被 ``inspect_archive`` 迁到当前 head 时会自动补上这三张表与两列，不会因为
"缺少数据表 / 缺少列"被拒收。

三张表全部带 ``deleted_at`` 软删除 + ``created_at``/``updated_at``（``utcnow``），
外键一律 ``SET NULL`` + 快照字段。

- ``question_bank_record``：个性化题库的保存历史（D5 题库历史）。
- ``interview_review_record``：面试复盘的保存历史（D5 复盘历史）。
- ``knowledge_entry``：知识库条目（业务代码第 7 批再做，这里只建表 + 注册）。
- ``referral``：内推加 ``referral_code``（内推码）与 ``note_images``（图片路径）两列
  （业务代码第 6 批再做）。

Revision ID: 0019_interview_history_knowledge_referral_fields
Revises: 0018_referral_reminder_interview_experience_share_package
Create Date: 2026-09-20
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_interview_history_knowledge_referral_fields"
down_revision: str | Sequence[str] | None = "0018_referral_reminder_interview_experience_share_package"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 本迁移新增的三张表（升级后表集合"多出且只多出"这三张）。
NEW_TABLES = ("question_bank_record", "interview_review_record", "knowledge_entry")

# referral 新增的两列（只加列、不改既有列）。
REFERRAL_COLUMNS = {
    "referral_code": sa.Column("referral_code", sa.String(length=64), nullable=False, server_default=""),
    "note_images": sa.Column("note_images", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
}


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _table_names()

    if "question_bank_record" not in tables:
        op.create_table(
            "question_bank_record",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("job_title", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("company", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("resume_id", sa.Integer(), nullable=True),
            sa.Column("resume_title", sa.String(length=256), nullable=False, server_default=""),
            sa.Column("groups", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("model", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["resume_id"], ["resume_record.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_question_bank_record_job_id", "question_bank_record", ["job_id"])

    if "interview_review_record" not in tables:
        op.create_table(
            "interview_review_record",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("job_title", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("company", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("resume_id", sa.Integer(), nullable=True),
            sa.Column("resume_title", sa.String(length=256), nullable=False, server_default=""),
            sa.Column("questions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("analysis", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("suggestions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("model", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["resume_id"], ["resume_record.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_interview_review_record_job_id", "interview_review_record", ["job_id"]
        )

    if "knowledge_entry" not in tables:
        op.create_table(
            "knowledge_entry",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("category", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("source", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_knowledge_entry_category", "knowledge_entry", ["category"])

    # referral 只加列：表已存在时（历史库兼容）按列判断是否已加，不重复 ALTER。
    if "referral" in tables:
        columns = _column_names("referral")
        if "referral_code" not in columns:
            op.add_column("referral", REFERRAL_COLUMNS["referral_code"])
        if "note_images" not in columns:
            op.add_column("referral", REFERRAL_COLUMNS["note_images"])


def _drop_index_if_present(table: str, name: str) -> None:
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name in indexes:
        op.drop_index(name, table_name=table)


def downgrade() -> None:
    tables = _table_names()

    # 三张表之间无外键互相引用，删除顺序无依赖。
    if "knowledge_entry" in tables:
        _drop_index_if_present("knowledge_entry", "ix_knowledge_entry_category")
        op.drop_table("knowledge_entry")
    if "interview_review_record" in tables:
        _drop_index_if_present("interview_review_record", "ix_interview_review_record_job_id")
        op.drop_table("interview_review_record")
    if "question_bank_record" in tables:
        _drop_index_if_present("question_bank_record", "ix_question_bank_record_job_id")
        op.drop_table("question_bank_record")

    # 拆掉 referral 的两列（顺序与加列相反，先 note_images 后 referral_code）。
    if "referral" in tables:
        columns = _column_names("referral")
        if "note_images" in columns:
            op.drop_column("referral", "note_images")
        if "referral_code" in columns:
            op.drop_column("referral", "referral_code")
