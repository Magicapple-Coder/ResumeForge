"""新增内推 / 提醒 / 面经 / 分享包四张表（R-13 / R-12 / R-15 / R-18 的地基）。

与 ``0010`` / ``0012`` / ``0017`` 一样，本次迁移**只加表**，不改既有列、不动既有表：
旧备份被 ``inspect_archive`` 迁到当前 head 时会自动补上这四张表，不会因为"缺少数据表"
被拒收。

四张表全部带 ``deleted_at`` 软删除 + ``created_at``/``updated_at``（``utcnow``），
外键一律 ``SET NULL`` + 快照字段。字段取值见各自模型文件顶部的常量。

- ``referral``：内推记录（状态/转化/关联漏斗）。
- ``reminder``：日历提醒（绑定漏斗/岗位/简历）。
- ``interview_experience``：面经知识库（真实问题 + 正文）。
- ``share_package``：离线分享包（快照/权限/评论回传）。

Revision ID: 0018_referral_reminder_interview_experience_share_package
Revises: 0017_resume_generate_task
Create Date: 2026-09-19
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_referral_reminder_interview_experience_share_package"
down_revision: str | Sequence[str] | None = "0017_resume_generate_task"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "referral" not in tables:
        op.create_table(
            "referral",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("job_title", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("company", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("referrer_name", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("referrer_contact", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("relation", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("position", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("channel", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
            sa.Column("track_id", sa.Integer(), nullable=True),
            sa.Column("converted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("submitted_at", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["track_id"], ["application_track.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_referral_job_id", "referral", ["job_id"])
        op.create_index("ix_referral_status", "referral", ["status"])

    if "reminder" not in tables:
        op.create_table(
            "reminder",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("remind_at", sa.DateTime(), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False, server_default="other"),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("track_id", sa.Integer(), nullable=True),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("resume_id", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["track_id"], ["application_track.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["resume_id"], ["resume_record.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_reminder_remind_at", "reminder", ["remind_at"])
        op.create_index("ix_reminder_status", "reminder", ["status"])
        op.create_index("ix_reminder_job_id", "reminder", ["job_id"])

    if "interview_experience" not in tables:
        op.create_table(
            "interview_experience",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("company", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("position", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("questions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("source", sa.String(length=16), nullable=False, server_default="self"),
            sa.Column("difficulty", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("round_type", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("interview_date", sa.String(length=10), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_interview_experience_company", "interview_experience", ["company"])
        op.create_index("ix_interview_experience_job_id", "interview_experience", ["job_id"])

    if "share_package" not in tables:
        op.create_table(
            "share_package",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("resume_id", sa.Integer(), nullable=True),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("files", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("permission", sa.String(length=16), nullable=False, server_default="read_only"),
            sa.Column("snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("comments_file", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("share_token", sa.String(length=64), nullable=False),
            sa.Column("redaction_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["resume_id"], ["resume_record.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_share_package_resume_id", "share_package", ["resume_id"])
        op.create_index(
            "ix_share_package_share_token", "share_package", ["share_token"], unique=True
        )


def _drop_index_if_present(table: str, name: str) -> None:
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name in indexes:
        op.drop_index(name, table_name=table)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    # 四张表之间无外键互相引用，删除顺序无依赖；按"引用方的相反顺序"拆除即可。
    if "share_package" in tables:
        _drop_index_if_present("share_package", "ix_share_package_share_token")
        _drop_index_if_present("share_package", "ix_share_package_resume_id")
        op.drop_table("share_package")
    if "interview_experience" in tables:
        _drop_index_if_present("interview_experience", "ix_interview_experience_job_id")
        _drop_index_if_present("interview_experience", "ix_interview_experience_company")
        op.drop_table("interview_experience")
    if "reminder" in tables:
        _drop_index_if_present("reminder", "ix_reminder_job_id")
        _drop_index_if_present("reminder", "ix_reminder_status")
        _drop_index_if_present("reminder", "ix_reminder_remind_at")
        op.drop_table("reminder")
    if "referral" in tables:
        _drop_index_if_present("referral", "ix_referral_status")
        _drop_index_if_present("referral", "ix_referral_job_id")
        op.drop_table("referral")
