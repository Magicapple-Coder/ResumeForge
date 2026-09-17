"""新增自动投递中心的数据表：匹配结论、投递队列与执行批次。

本次迁移**只加表**，不改既有列、不动既有表 —— 这是让"旧备份仍可导入"天然成立的前提：
``data_backup.inspect_archive`` 会先把旧备份迁移到当前 head 再校验表集合，只加表就意味着
一份停在 ``0009`` 的备份被迁到 head 后自动补上这 4 张表，不会因为"缺少数据表"被拒收。

四张表：
- ``job_match_analysis``：一个岗位保留最近一次匹配结论（job_id 唯一即覆盖）。
- ``apply_queue_item``：用户显式勾选的待投递队列（同一岗位唯一）。
- ``apply_task``：一次执行批次（采集与投递共用，靠 kind 区分）。
- ``apply_task_item``：批次内每个岗位的执行条目（投递记录），随批次 CASCADE 删除。

Revision ID: 0010_apply_center
Revises: 0009_templates_and_interview
Create Date: 2026-09-18
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_apply_center"
down_revision: str | Sequence[str] | None = "0009_templates_and_interview"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    # 岗位匹配度分析结果。只加表；幂等（重复 upgrade 不报错）。索引与外键在 create_table
    # 内一次性声明——SQLite 不支持用 add_column 补带约束的列（见 0009 的记录）。
    if "job_match_analysis" not in tables:
        op.create_table(
            "job_match_analysis",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("job_title", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("company", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("hard_gate", sa.String(length=16), nullable=False, server_default="unknown"),
            sa.Column(
                "requires_confirm", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("model", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_job_match_analysis_job_id", "job_match_analysis", ["job_id"], unique=True
        )
        op.create_index("ix_job_match_analysis_hard_gate", "job_match_analysis", ["hard_gate"])

    # 投递队列：同一岗位只能有一条（去重第一道闸）。
    if "apply_queue_item" not in tables:
        op.create_table(
            "apply_queue_item",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("job_title", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("company", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("resume_id", sa.Integer(), nullable=True),
            sa.Column("greeting", sa.Text(), nullable=False, server_default=""),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["resume_id"], ["resume_record.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("job_id", name="uq_apply_queue_item_job_id"),
        )
        op.create_index("ix_apply_queue_item_job_id", "apply_queue_item", ["job_id"])
        op.create_index("ix_apply_queue_item_sort_order", "apply_queue_item", ["sort_order"])
        op.create_index("ix_apply_queue_item_status", "apply_queue_item", ["status"])

    # 一次执行批次（采集与投递共用）。
    if "apply_task" not in tables:
        op.create_table(
            "apply_task",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("succeeded", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("current_step", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("stop_reason", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("message", sa.Text(), nullable=False, server_default=""),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_apply_task_kind", "apply_task", ["kind"])
        op.create_index("ix_apply_task_status", "apply_task", ["status"])

    # 批次内的每岗位执行条目（投递记录）。随批次删除。
    if "apply_task_item" not in tables:
        op.create_table(
            "apply_task_item",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("job_title", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("company", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("resume_id", sa.Integer(), nullable=True),
            sa.Column("resume_title", sa.String(length=256), nullable=False, server_default=""),
            sa.Column("greeting", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("failure_category", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("failure_detail", sa.Text(), nullable=False, server_default=""),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["apply_task.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["resume_id"], ["resume_record.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_apply_task_item_task_id", "apply_task_item", ["task_id"])
        op.create_index("ix_apply_task_item_job_id", "apply_task_item", ["job_id"])
        op.create_index("ix_apply_task_item_status", "apply_task_item", ["status"])


def _drop_index_if_present(table: str, name: str) -> None:
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name in indexes:
        op.drop_index(name, table_name=table)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    # 逆序删除：先删有外键指向 apply_task 的条目表，再删批次表。
    if "apply_task_item" in tables:
        _drop_index_if_present("apply_task_item", "ix_apply_task_item_status")
        _drop_index_if_present("apply_task_item", "ix_apply_task_item_job_id")
        _drop_index_if_present("apply_task_item", "ix_apply_task_item_task_id")
        op.drop_table("apply_task_item")
    if "apply_task" in tables:
        _drop_index_if_present("apply_task", "ix_apply_task_status")
        _drop_index_if_present("apply_task", "ix_apply_task_kind")
        op.drop_table("apply_task")
    if "apply_queue_item" in tables:
        _drop_index_if_present("apply_queue_item", "ix_apply_queue_item_status")
        _drop_index_if_present("apply_queue_item", "ix_apply_queue_item_sort_order")
        _drop_index_if_present("apply_queue_item", "ix_apply_queue_item_job_id")
        op.drop_table("apply_queue_item")
    if "job_match_analysis" in tables:
        _drop_index_if_present("job_match_analysis", "ix_job_match_analysis_hard_gate")
        _drop_index_if_present("job_match_analysis", "ix_job_match_analysis_job_id")
        op.drop_table("job_match_analysis")
