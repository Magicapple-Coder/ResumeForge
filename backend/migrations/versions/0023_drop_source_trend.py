"""删掉 ``official_source_trend``：它记录的计数在运行记录里已经有了。

**这是一次删除，理由要说清楚**，因为"删表"通常意味着数据丢失：

- 那张表记的是每次采集的岗位计数，而 ``official_collect_run.collected`` **记的是同一个数**，
  且后者还带着这次采集的状态与阻断分类——趋势判断恰恰需要那两项（只有"有效测量"才进基线）。
- 它从建起来就没有读者：趋势一开始读的就是运行记录。当初单开一张表的理由是"基线靠查询运行记录
  现算会随新数据漂移"，**这个理由是错的**——按 ``id < 本次`` 取历史同样不会漂移。
- 运行记录从不被单独删除（随源 ``CASCADE``），所以那张表也没有"比运行记录活得更久"的价值。

**"旧备份仍可导入"的前提不受影响**：本迁移是幂等的（表不在就跳过），因此无论备份来自本表
存在之前还是之后，迁到 head 之后表集合都与当前代码一致。

Revision ID: 0023_drop_source_trend
Revises: 0022_official_site_collect
Create Date: 2026-09-23
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_drop_source_trend"
down_revision: str | Sequence[str] | None = "0022_official_site_collect"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "official_source_trend"


def upgrade() -> None:
    bind = op.get_bind()
    if TABLE in set(sa.inspect(bind).get_table_names()):
        op.drop_table(TABLE)


def downgrade() -> None:
    """把表建回来，结构与 ``0022`` 里的一致——降级要能真的回到上一版。"""
    bind = op.get_bind()
    if TABLE in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("job_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["official_site.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["official_collect_run.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_official_source_trend_site_id", TABLE, ["site_id"])
    op.create_index("ix_official_source_trend_recorded_at", TABLE, ["recorded_at"])
