"""保存「按岗位找公司」搜索历史与候选快照。

搜索结果来自外部搜索源，会随着排序、索引和页面内容变化。保存查询条件还不够，历史记录必须
同时保存当时的候选公司，否则用户点开旧记录时又会得到另一批结果。

Revision ID: 0024_official_discovery_history
Revises: 0023_drop_source_trend
Create Date: 2026-09-23
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_official_discovery_history"
down_revision: str | Sequence[str] | None = "0023_drop_source_trend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE = "official_discovery_search"


def upgrade() -> None:
    bind = op.get_bind()
    if TABLE in sa.inspect(bind).get_table_names():
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keywords", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("city", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("queries", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("candidates", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("detail", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_official_discovery_search_created_at", TABLE, ["created_at"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    if TABLE not in sa.inspect(bind).get_table_names():
        return
    op.drop_index("ix_official_discovery_search_created_at", table_name=TABLE)
    op.drop_table(TABLE)
