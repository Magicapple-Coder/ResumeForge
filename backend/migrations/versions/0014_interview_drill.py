"""新增按台账深挖的面试会话：评分契约、逐轮问答与复盘。

与 ``0010``~``0013`` 一样，本次迁移**只加表**，不改既有列、不动既有表：旧备份被
``inspect_archive`` 迁到当前 head 时会自动补上这三张表，不会因为"缺少数据表"被拒收。

三张表：``drill_session``（一次会话）、``drill_contract``（一道题的评分契约，
提问前锁定）、``drill_turn``（一轮问答）。契约与轮次都随会话 ``CASCADE`` 删除。

Revision ID: 0014_interview_drill
Revises: 0013_resume_format_config
Create Date: 2026-09-18
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_interview_drill"
down_revision: str | Sequence[str] | None = "0013_resume_format_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "drill_session" not in tables:
        op.create_table(
            "drill_session",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("job_title", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("company", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
            sa.Column(
                "feedback_policy", sa.String(length=16), nullable=False, server_default="deferred"
            ),
            sa.Column("claim_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("max_questions", sa.Integer(), nullable=False, server_default="6"),
            sa.Column("current_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("review", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["job.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_drill_session_status", "drill_session", ["status"])

    if "drill_contract" not in tables:
        op.create_table(
            "drill_contract",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("claim_id", sa.Integer(), nullable=True),
            sa.Column("claim_title", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("question", sa.Text(), nullable=False, server_default=""),
            sa.Column("intent", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "required_evidence", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
            ),
            sa.Column(
                "followup_triggers", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
            ),
            sa.Column("stop_condition", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "status", sa.String(length=24), nullable=False, server_default="not_covered"
            ),
            sa.Column("evidence_found", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("missing", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("contradictions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("followup_depth", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "next_followup_kind", sa.String(length=24), nullable=False, server_default=""
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["drill_session.id"], ondelete="CASCADE"),
            # 主张被删掉后这道题的记录仍要可读（复盘要看当时问了什么）。
            sa.ForeignKeyConstraint(["claim_id"], ["claim_record.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_drill_contract_session_id", "drill_contract", ["session_id"])
        op.create_index("ix_drill_contract_claim_id", "drill_contract", ["claim_id"])
        op.create_index("ix_drill_contract_status", "drill_contract", ["status"])

    if "drill_turn" not in tables:
        op.create_table(
            "drill_turn",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("contract_id", sa.Integer(), nullable=True),
            sa.Column("question", sa.Text(), nullable=False, server_default=""),
            sa.Column("answer", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=24), nullable=False, server_default=""),
            sa.Column("feedback", sa.Text(), nullable=False, server_default=""),
            sa.Column("next_question", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["drill_session.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["contract_id"], ["drill_contract.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_drill_turn_session_id", "drill_turn", ["session_id"])
        op.create_index("ix_drill_turn_contract_id", "drill_turn", ["contract_id"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    # 逆序删除：先删引用契约与会话的轮次，再删契约，最后删会话。
    for table, indexes in (
        (
            "drill_turn",
            ("ix_drill_turn_contract_id", "ix_drill_turn_session_id"),
        ),
        (
            "drill_contract",
            (
                "ix_drill_contract_status",
                "ix_drill_contract_claim_id",
                "ix_drill_contract_session_id",
            ),
        ),
        ("drill_session", ("ix_drill_session_status",)),
    ):
        if table not in tables:
            continue
        present = {item["name"] for item in sa.inspect(bind).get_indexes(table)}
        for name in indexes:
            if name in present:
                op.drop_index(name, table_name=table)
        op.drop_table(table)
