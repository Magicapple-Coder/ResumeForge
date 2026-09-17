"""给简历记录加一列「只属于这份简历的版式覆盖」。

为什么需要它：``resume_record.format_name`` 指向的是**具名**格式模板，改那个模板会让
所有引用它的简历一起变。而「自动一页」试出来的方案只对当前这份内容成立——换一份内容
就不一样了——不该反过来去污染用户的模板清单，所以按简历单独存一份叠加在上面的覆盖。

只加列、不改既有列：``inspect_archive`` 会先把旧备份迁到当前 head 再校验，
加列不影响"旧备份仍可导入"。默认值 ``'{}'``（空对象），旧记录迁移后与迁移前渲染结果
完全一致。

Revision ID: 0013_resume_format_config
Revises: 0012_application_tracker
Create Date: 2026-09-18
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_resume_format_config"
down_revision: str | Sequence[str] | None = "0012_application_tracker"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str] | None:
    """表存在时返回它的列名；表不存在返回 None。

    把"表不存在"与"表存在但没这一列"分开，是因为前者必须**跳过**而不是报错：
    迁移链会被用在"只有部分业务表的历史库"与"从旧备份恢复出来的库"上，
    对着一张不存在的表执行 ALTER 会直接崩，而不是给出可理解的结果。
    """
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return None
    return {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    columns = _columns("resume_record")
    if columns is None or "format_config" in columns:
        return
    op.add_column(
        "resume_record",
        sa.Column(
            "format_config",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    columns = _columns("resume_record")
    if columns is None or "format_config" not in columns:
        return
    op.drop_column("resume_record", "format_config")
