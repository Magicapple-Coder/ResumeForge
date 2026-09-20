"""给备选岗位加「其他招聘信息」一列（采集三段切分的第三段）。

沿用 0015/0020 的幂等 `_columns()` 写法：**只加列、不改既有列、不建表、不建外键**。
加列不改表集合，因此"旧备份仍可导入"的前提（迁移到 head 后表集合对得上）不受影响；
旧行升级后新列拿到空串（而不是 null），界面按"没填"渲染。

- ``candidate_job.additional_info``：采集端把 JD 按小标题切成
  「职位描述 / 任职要求 / 其他招聘信息」三段，第三段（福利待遇、公司/团队介绍这类）
  此前没有列可落，只能留在描述里，于是导入后的岗位「其他招聘信息」永远是空的。
  这一列把它接住并透传给正式岗位的 ``job.additional_info``。

Revision ID: 0021_candidate_additional_info
Revises: 0020_daily_20260920_columns
Create Date: 2026-09-20
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_candidate_additional_info"
down_revision: str | Sequence[str] | None = "0020_daily_20260920_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (表名, 列名, 类型)。只加一列；列不存在才 ALTER，重复执行幂等。
NEW_COLUMNS = (("candidate_job", "additional_info", sa.Text()),)


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
