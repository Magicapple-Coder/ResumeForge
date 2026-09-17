"""新增事实台账表：把可对外表达的主张与其依据、边界、核实状态沉淀下来。

与 ``0010`` 一样，本次迁移**只加表**，不改既有列、不动既有表：``data_backup.inspect_archive``
会先把旧备份迁移到当前 head 再校验表集合，只加表就意味着停在更早 revision 的备份被迁到
head 后会补上这张表，不会因为"缺少数据表"被拒收。

表：``claim_record`` —— 一条主张一行。字段含义见 ``app/models/claim.py`` 的模块说明；
核实状态与承担程度的取值同样只在模型层定义一次。

Revision ID: 0011_claim_ledger
Revises: 0010_apply_center
Create Date: 2026-09-18
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_claim_ledger"
down_revision: str | Sequence[str] | None = "0010_apply_center"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "claim_record" in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        "claim_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column(
            "category", sa.String(length=32), nullable=False, server_default="其他"
        ),
        sa.Column("subject", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("source_fact", sa.Text(), nullable=False, server_default=""),
        sa.Column("candidate_wording", sa.Text(), nullable=False, server_default=""),
        sa.Column("sources", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "responsibility_level",
            sa.String(length=32),
            nullable=False,
            server_default="参与",
        ),
        sa.Column(
            "verification_status",
            sa.String(length=16),
            nullable=False,
            server_default="待确认",
        ),
        sa.Column("allowed_uses", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "interview_details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("boundary", sa.Text(), nullable=False, server_default=""),
        sa.Column("risk_notes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("last_verified", sa.String(length=10), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claim_record_category", "claim_record", ["category"])
    op.create_index("ix_claim_record_subject", "claim_record", ["subject"])
    op.create_index(
        "ix_claim_record_verification_status", "claim_record", ["verification_status"]
    )
    op.create_index(
        "ix_claim_record_responsibility_level", "claim_record", ["responsibility_level"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "claim_record" not in set(sa.inspect(bind).get_table_names()):
        return

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("claim_record")}
    for name in (
        "ix_claim_record_responsibility_level",
        "ix_claim_record_verification_status",
        "ix_claim_record_subject",
        "ix_claim_record_category",
    ):
        if name in indexes:
            op.drop_index(name, table_name="claim_record")
    op.drop_table("claim_record")
