"""给备选岗位加六列，让它能承载"投递台采集结果"的暂存。

**为什么复用 ``candidate_job`` 而不是新建一张表**：备选岗位已经是"招聘信息先存着、
核对后再导入正式岗位"的链路，且已有列表 / 新建 / 编辑 / **标记已导入** / 删除一整套接口。
投递台采集要做的事与它**形状完全一致**：采到的东西先陈列、由用户挑、挑中的才进岗位广场。
差别只是采集会多带出城市、薪资、原始链接、JD 正文与批次，所以加列即可，不必再引入一个
同义概念。

六个新列：

- ``location`` / ``salary``：采集能拿到、而"粘贴文本"拿不到的两个字段；
- ``source_url``：既用于**与正式岗位双向去重**（同一链接不再重复采集），也是后续"回原站看"
  的入口；
- ``description`` / ``requirements``：采集已在服务端按小标题切分好的 JD 两段（``raw_text``
  是"粘贴进来的原始文本"，语义不同，不能混用）；
- ``collect_task_id``：指向产生这条候选的采集批次（``apply_task``），用于按批次回看。

**只加列、不改既有列、不建外键**：``inspect_archive`` 会先把旧备份迁到当前 head 再校验，
只加列不影响"旧备份仍可导入"；不建外键则与 ``claim_record`` 同样的理由——批次记录被清理掉
也不该连带删掉用户还没处理的候选岗位。

Revision ID: 0015_candidate_job_collect_fields
Revises: 0014_interview_drill
Create Date: 2026-09-18
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_candidate_job_collect_fields"
down_revision: str | Sequence[str] | None = "0014_interview_drill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_COLUMNS = (
    # (列名, 类型, 是否可空, 服务端默认值)
    ("location", sa.String(length=64), False, ""),
    ("salary", sa.String(length=64), False, ""),
    ("source_url", sa.String(length=512), False, ""),
    # 采集带回来的 JD 正文与任职要求。**必须单独存**：``raw_text`` 是"粘贴进来的原始文本"
    # （手动链路用），而采集已经在服务端把两者按小标题切分好了——塞进 raw_text 会把这份
    # 结构丢掉，导入岗位时又变回"描述与要求混在一起"。
    ("description", sa.Text(), False, ""),
    ("requirements", sa.Text(), False, ""),
    # 批次 id 允许为空：迁移前已有的候选没有批次，不该被硬塞一个假的。
    ("collect_task_id", sa.Integer(), True, None),
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
    columns = _columns("candidate_job")
    if columns is None:
        return
    for name, column_type, nullable, default in NEW_COLUMNS:
        if name in columns:
            continue
        # SQLite 上给已有表加 NOT NULL 列必须带 server_default，否则 ALTER 直接失败；
        # 空串也让迁移前的老行语义不变（"没填"而不是"填了 null"）。
        op.add_column(
            "candidate_job",
            sa.Column(name, column_type, nullable=nullable, server_default=default),
        )


def downgrade() -> None:
    columns = _columns("candidate_job")
    if columns is None:
        return
    for name, _type, _nullable, _default in NEW_COLUMNS:
        if name in columns:
            op.drop_column("candidate_job", name)
