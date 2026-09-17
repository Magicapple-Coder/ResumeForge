"""新增求职进度表：一家公司一个岗位一条记录，随对方发来的通知往前推进。

与 ``0010`` / ``0011`` 一样，本次迁移**只加表**，不改既有列、不动既有表：旧备份被
``inspect_archive`` 迁到当前 head 时会自动补上这张表，不会因为"缺少数据表"被拒收。

表：``application_track``。状态取值、合并规则与归一化方式见 ``app/models/tracker.py``。

Revision ID: 0012_application_tracker
Revises: 0011_claim_ledger
Create Date: 2026-09-18
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_application_tracker"
down_revision: str | Sequence[str] | None = "0011_claim_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "application_track" in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        "application_track",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("company_key", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("title_key", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="applied"),
        sa.Column("stage_note", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("applied_at", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("status_date", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("next_action", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("next_action_date", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("resume_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resume_id"], ["resume_record.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        # 同一公司同一岗位只有一条——这是"漏斗只有一个口径"的结构保证，
        # 合并逻辑写在服务层，这里用约束兜住"并发写入绕过合并"的情况。
        sa.UniqueConstraint("company_key", "title_key", name="uq_application_track_company_title"),
    )
    op.create_index("ix_application_track_company_key", "application_track", ["company_key"])
    op.create_index("ix_application_track_title_key", "application_track", ["title_key"])
    op.create_index("ix_application_track_status", "application_track", ["status"])
    op.create_index("ix_application_track_job_id", "application_track", ["job_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "application_track" not in set(sa.inspect(bind).get_table_names()):
        return

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("application_track")}
    for name in (
        "ix_application_track_job_id",
        "ix_application_track_status",
        "ix_application_track_title_key",
        "ix_application_track_company_key",
    ):
        if name in indexes:
            op.drop_index(name, table_name="application_track")
    op.drop_table("application_track")
