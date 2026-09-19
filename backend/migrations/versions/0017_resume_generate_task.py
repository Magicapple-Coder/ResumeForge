"""新增简历生成后台任务表：把「一次 SSE 生成」升级成「可轮询的后台任务」。

与 ``0010`` / ``0011`` / ``0012`` 一样，本次迁移**只加表**，不改既有列、不动既有表：
旧备份被 ``inspect_archive`` 迁到当前 head 时会自动补上这张表，不会因为"缺少数据表"
被拒收。

表：``resume_generate_task``。状态取值见 ``app/models/resume.py`` 顶部常量
（pending/running/completed/cancelled/failed），前端镜像同一份字符串。

**为什么 ``resume_id`` / ``job_id`` 用 SET NULL 而不是 CASCADE**：任务只是"生成动作"
的记录，岗位或简历被删后，任务的历史状态（成功/失败/取消）仍要可读，不应连坐删除。

Revision ID: 0017_resume_generate_task
Revises: 0016_soft_delete_marks
Create Date: 2026-09-18
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_resume_generate_task"
down_revision: str | Sequence[str] | None = "0016_soft_delete_marks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "resume_generate_task"


def _exists(bind) -> bool:
    return TABLE_NAME in set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    if _exists(bind):
        return

    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("resume_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("received_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("options", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["resume_id"], ["resume_record.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(f"ix_{TABLE_NAME}_status", TABLE_NAME, ["status"])
    op.create_index(f"ix_{TABLE_NAME}_job_id", TABLE_NAME, ["job_id"])
    op.create_index(f"ix_{TABLE_NAME}_created_at", TABLE_NAME, ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if not _exists(bind):
        return

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes(TABLE_NAME)}
    for name in (
        f"ix_{TABLE_NAME}_created_at",
        f"ix_{TABLE_NAME}_job_id",
        f"ix_{TABLE_NAME}_status",
    ):
        if name in indexes:
            op.drop_index(name, table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
