"""新增官网岗位采集：源、采集账目与计数趋势。

与 ``0010``~``0014`` 一样，本次迁移**只加表**，不改既有列、不动既有表：旧备份被
``inspect_archive`` 迁到当前 head 时会自动补上这三张表，不会因为"缺少数据表"被拒收。

三张表：``official_site``（一个公司官网源及其识别结果）、``official_collect_run``（一次采集的账目
与对账结论）、``official_source_trend``（每源每次采集的岗位计数）。后两张随源 ``CASCADE`` 删除。

**为什么要单开一张计数表**：趋势离群要跟"近期基线"比，而基线若靠查询 run 表现算，就会随着
新数据不断漂移（今天的异常抬高明天的基线）。计数单独落一行，比对只读历史、不重算。

Revision ID: 0022_official_site_collect
Revises: 0021_candidate_additional_info
Create Date: 2026-09-23
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_official_site_collect"
down_revision: str | Sequence[str] | None = "0021_candidate_additional_info"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "official_site" not in tables:
        op.create_table(
            "official_site",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("company", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("homepage_url", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("careers_url", sa.String(length=512), nullable=False, server_default=""),
            # 空串 = 未识别出已知的招聘系统，走通用抽取路径。
            sa.Column("source_kind", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("endpoint", sa.String(length=1024), nullable=False, server_default=""),
            sa.Column("params", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("confidence", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("probe_evidence", sa.String(length=500), nullable=False, server_default=""),
            # 通用路径的选择器配方（阶段 2），带版本号以便站点改版后对比。
            sa.Column("recipe", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("recipe_version", sa.String(length=32), nullable=False, server_default=""),
            # robots 结论落库而不是每次重取：源列表上要能直接看到"允不允许采集"。
            # 三态（未查 / 允许 / 不允许），所以可空。
            sa.Column("robots_allowed", sa.Boolean(), nullable=True),
            sa.Column("robots_detail", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("crawl_delay_seconds", sa.Float(), nullable=True),
            sa.Column(
                "min_interval_seconds", sa.Integer(), nullable=False, server_default="10"
            ),
            sa.Column("max_per_hour", sa.Integer(), nullable=False, server_default="120"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("last_probed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_official_site_created_at", "official_site", ["created_at"])

    if "official_collect_run" not in tables:
        op.create_table(
            "official_collect_run",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("site_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
            # ===== 账目 =====
            sa.Column("pages", sa.Integer(), nullable=False, server_default="0"),
            # collected 是**去重后的取回条数**，对总数跟它比而不是跟 stored 比。
            sa.Column("collected", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stored", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("detail_missing", sa.Integer(), nullable=False, server_default="0"),
            # 站点给出的总数锚点；没有这个契约时为 NULL（不是 0——0 是一个合法的总数）。
            sa.Column("total_hint", sa.Integer(), nullable=True),
            sa.Column("blocks", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            # ===== 对账结论 =====
            sa.Column("verdict", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("evidence", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("headline", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("missing", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "reconcile_detail", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            ),
            # ===== 模型成本：用户自付 key，必须可查 =====
            sa.Column("llm_calls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("llm_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["site_id"], ["official_site.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_official_collect_run_site_id", "official_collect_run", ["site_id"])
        op.create_index("ix_official_collect_run_status", "official_collect_run", ["status"])
        op.create_index(
            "ix_official_collect_run_started_at", "official_collect_run", ["started_at"]
        )

    if "official_source_trend" not in tables:
        op.create_table(
            "official_source_trend",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("site_id", sa.Integer(), nullable=False),
            # 记录被删（例如源被停用重来）时计数仍要留着，所以这里是 SET NULL 而不是 CASCADE：
            # 计数是趋势的原料，它的价值恰恰在于"跨多次采集"。
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("job_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["site_id"], ["official_site.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["run_id"], ["official_collect_run.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_official_source_trend_site_id", "official_source_trend", ["site_id"])
        op.create_index(
            "ix_official_source_trend_recorded_at", "official_source_trend", ["recorded_at"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    # 先删依赖方，再删被依赖方——顺序反了会在有数据时因外键约束失败。
    if "official_source_trend" in tables:
        op.drop_table("official_source_trend")
    if "official_collect_run" in tables:
        op.drop_table("official_collect_run")
    if "official_site" in tables:
        op.drop_table("official_site")
