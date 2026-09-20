"""给简历记录加备注、给备选岗位加岗位类型两列（B5 + C7）。

沿用 0015 的幂等 `_columns()` 写法：**只加列、不改既有列、不建表、不建外键**。
加列不改表集合，因此"旧备份仍可导入"的前提（迁移到 head 后表集合对得上）不受影响；
旧行升级后新列拿到空串（而不是 null），界面按"没填"渲染，不必到处判 None。

- ``resume_record.note``：用户给某份简历写的备注（列表默认可见、详情可编辑）。
- ``candidate_job.job_type``：采集任务透传的岗位类型（校招/实习/社招）；空串 = 不限。
  **仅做入库标注**：不入去重判据、不参与站点筛选。

Revision ID: 0020_daily_20260920_columns
Revises: 0019_interview_history_knowledge_referral_fields
Create Date: 2026-09-20
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_daily_20260920_columns"
down_revision: str | Sequence[str] | None = "0019_interview_history_knowledge_referral_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (表名, 列名, 类型)。两张表都只加一列；列不存在才 ALTER，重复执行幂等。
NEW_COLUMNS = (
    ("resume_record", "note", sa.Text()),
    ("candidate_job", "job_type", sa.String(length=32)),
)


def _columns(table: str) -> set[str] | None:
    """表存在时返回它的列名；表不存在返回 None。

    把"表不存在"与"表存在但没这一列"分开：迁移链也会被用在"只有部分业务表的历史库"上，
    对着一张不存在的表执行 ALTER 会直接崩，而不是给出可理解的结果。
    """
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return None
    return {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    for table, column_name, column_type in NEW_COLUMNS:
        columns = _columns(table)
        if columns is None or column_name in columns:
            continue
        # SQLite 上给已有表加 NOT NULL 列必须带 server_default，否则 ALTER 直接失败；
        # 空串也让迁移前的老行语义不变（"没填"而不是"填了 null"）。
        op.add_column(
            table,
            sa.Column(column_name, column_type, nullable=False, server_default=""),
        )


def downgrade() -> None:
    for table, column_name, _column_type in NEW_COLUMNS:
        columns = _columns(table)
        if columns is not None and column_name in columns:
            op.drop_column(table, column_name)
