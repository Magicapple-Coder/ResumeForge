"""给六类"用户会心疼"的内容加软删除标记（``deleted_at``），为回收站打底。

**为什么是软删除而不是搬到另一张表**：搬到回收站表意味着要把外键、快照字段、去重判据
全部重建一遍，而这些东西现在都是好的——软删除只加一个"什么时候删的"时间戳，其余一律照旧，
列表查询加一句 ``deleted_at IS NULL`` 即可。恢复就是把时间戳清空。

**范围克制**：只覆盖用户真正会心疼的六类——岗位、简历记录、投递记录、事实台账条目、
资料箱材料、助手会话。列级别、模板副本、数据集、录用记录这类要么有明确的沿用关系、
要么本来就能重建，不做回收站（每个可删项都进回收站只会让回收站本身变成垃圾场）。

**只加列、不改既有列、不建外键、不改表集合**：``inspect_archive`` 会先把旧备份迁到当前 head
再校验，只加列不影响"旧备份仍可导入"。

关于索引：这些表的列表查询会多一句 ``deleted_at IS NULL``，但绝大多数行都是 NULL、
选择性极低，单列索引反而可能被优化器忽略。这是本地单用户的库（量级在千行），
所以**刻意不加索引**，而不是"忘了加"。

Revision ID: 0016_soft_delete_marks
Revises: 0015_candidate_job_collect_fields
Create Date: 2026-09-18
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_soft_delete_marks"
down_revision: str | Sequence[str] | None = "0015_candidate_job_collect_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 六类进回收站的内容。顺序即回收站里的展示顺序（越靠前越常用）。
TRASHED_TABLES = (
    "job",
    "resume_record",
    "application_track",
    "claim_record",
    "material",
    "chat_conversation",
)

COLUMN_NAME = "deleted_at"


def _columns(table: str) -> set[str] | None:
    """表存在时返回它的列名；表不存在返回 None（该表应跳过而不是报错）。"""
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return None
    return {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    for table in TRASHED_TABLES:
        columns = _columns(table)
        if columns is None or COLUMN_NAME in columns:
            continue
        # 可空 + 无默认值：NULL 表示"没删"，这正是软删除的语义，不需要额外回填。
        op.add_column(table, sa.Column(COLUMN_NAME, sa.DateTime(), nullable=True))


def downgrade() -> None:
    for table in TRASHED_TABLES:
        columns = _columns(table)
        if columns is None or COLUMN_NAME not in columns:
            continue
        op.drop_column(table, COLUMN_NAME)
