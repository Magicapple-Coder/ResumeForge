"""Add common query indexes and repair the legacy resume-to-job foreign key.

Revision ID: 0002_indexes_resume_fk
Revises: 0001_existing_schema
Create Date: 2026-08-18
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_indexes_resume_fk"
down_revision: str | Sequence[str] | None = "0001_existing_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = {
    "job": {
        "ix_job_status": ["status"],
        "ix_job_created_at": ["created_at"],
    },
    "resume_record": {
        "ix_resume_record_job_id": ["job_id"],
        "ix_resume_record_created_at": ["created_at"],
    },
}
_BATCH_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
}


def _index_names(bind, table_name: str) -> set[str]:
    return {
        item["name"]
        for item in sa.inspect(bind).get_indexes(table_name)
        if item.get("name")
    }


def _has_resume_job_foreign_key(bind) -> bool:
    return any(
        foreign_key.get("referred_table") == "job"
        and foreign_key.get("constrained_columns") == ["job_id"]
        for foreign_key in sa.inspect(bind).get_foreign_keys("resume_record")
    )


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table_name, indexes in _INDEXES.items():
        if table_name not in tables:
            continue
        existing = _index_names(bind, table_name)
        columns = {item["name"] for item in sa.inspect(bind).get_columns(table_name)}
        for index_name, indexed_columns in indexes.items():
            if index_name not in existing and set(indexed_columns) <= columns:
                op.create_index(index_name, table_name, indexed_columns, unique=False)

    resume_columns = (
        {item["name"] for item in sa.inspect(bind).get_columns("resume_record")}
        if "resume_record" in tables
        else set()
    )
    if {"resume_record", "job"} <= tables and "job_id" in resume_columns:
        # Old SQLite databases could contain orphaned IDs even when an anonymous
        # FK was present, because foreign-key enforcement was historically off.
        bind.execute(
            sa.text(
                "UPDATE resume_record SET job_id = NULL "
                "WHERE job_id IS NOT NULL AND job_id NOT IN (SELECT id FROM job)"
            )
        )
    if (
        {"resume_record", "job"} <= tables
        and "job_id" in resume_columns
        and not _has_resume_job_foreign_key(bind)
    ):
        # Old compatibility upgrades could add job_id but could not add a SQLite FK.
        with op.batch_alter_table("resume_record", recreate="always") as batch_op:
            batch_op.create_foreign_key(
                "fk_resume_record_job_id_job",
                "job",
                ["job_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table_name, indexes in _INDEXES.items():
        if table_name not in tables:
            continue
        existing = _index_names(bind, table_name)
        for index_name in indexes:
            if index_name in existing:
                op.drop_index(index_name, table_name=table_name)

    if "resume_record" in tables and _has_resume_job_foreign_key(bind):
        # SQLite cannot drop a foreign key in place. The naming convention also
        # gives legacy anonymous constraints a stable name during reflection.
        with op.batch_alter_table(
            "resume_record",
            recreate="always",
            naming_convention=_BATCH_NAMING_CONVENTION,
        ) as batch_op:
            batch_op.drop_constraint(
                "fk_resume_record_job_id_job",
                type_="foreignkey",
            )
