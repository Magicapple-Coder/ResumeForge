"""数据库迁移执行器、降级和备份行为测试。"""

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from alembic import command

from app.database import Base
from app.database_migrations import (
    BASELINE_REVISION,
    build_alembic_config,
    is_unversioned_legacy_database,
    run_database_migrations,
)
from app.models import Job, ResumeRecord
from tests.test_database import _APPLICATION_TABLES, _assert_head_schema


def test_migration_runner_builds_schema_from_empty_database(tmp_path):
    empty_engine = create_engine(f"sqlite:///{tmp_path / 'runner-empty.db'}")
    try:
        assert is_unversioned_legacy_database(empty_engine) is False
        assert run_database_migrations(empty_engine) is None

        _assert_head_schema(empty_engine)
        assert is_unversioned_legacy_database(empty_engine) is False
    finally:
        empty_engine.dispose()


def test_migration_runner_accepts_unversioned_metadata_schema_with_new_job_column(tmp_path):
    migration_engine = create_engine(f"sqlite:///{tmp_path / 'metadata-schema.db'}")
    try:
        Base.metadata.create_all(migration_engine)
        with Session(migration_engine) as session:
            session.add(Job(title="门店店长", additional_info="提供员工宿舍"))
            session.commit()

        backup_path = run_database_migrations(migration_engine)

        assert backup_path is not None and backup_path.exists()
        _assert_head_schema(migration_engine)
        with migration_engine.connect() as connection:
            additional_info = connection.execute(
                text("SELECT additional_info FROM job WHERE title = '门店店长'")
            ).scalar_one()
        assert additional_info == "提供员工宿舍"
    finally:
        migration_engine.dispose()


def test_migration_runner_supports_in_memory_database():
    memory_engine = create_engine("sqlite:///:memory:")
    try:
        assert run_database_migrations(memory_engine) is None

        _assert_head_schema(memory_engine)
    finally:
        memory_engine.dispose()


def test_unversioned_application_table_is_detected_as_legacy(tmp_path):
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy-detection.db'}")
    try:
        with legacy_engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE job (id INTEGER PRIMARY KEY)")

        assert is_unversioned_legacy_database(legacy_engine) is True
    finally:
        legacy_engine.dispose()


def test_alembic_downgrade_removes_resume_job_fk_without_losing_data(tmp_path):
    migration_engine = create_engine(f"sqlite:///{tmp_path / 'downgrade.db'}")
    config = build_alembic_config(migration_engine)
    try:
        command.upgrade(config, "head")
        with Session(migration_engine) as session:
            job = Job(title="Backend Engineer")
            session.add(job)
            session.flush()
            resume = ResumeRecord(title="Backend Resume", job_id=job.id)
            session.add(resume)
            session.commit()
            job_id = job.id
            resume_id = resume.id

        command.downgrade(config, BASELINE_REVISION)

        inspector = inspect(migration_engine)
        assert not any(
            item["referred_table"] == "job" and item["constrained_columns"] == ["job_id"]
            for item in inspector.get_foreign_keys("resume_record")
        )
        assert "ix_resume_record_job_id" not in {
            item["name"] for item in inspector.get_indexes("resume_record")
        }
        assert "chat_conversation" not in inspector.get_table_names()
        assert "chat_message" not in inspector.get_table_names()
        assert "additional_info" not in {
            column["name"] for column in inspector.get_columns("job")
        }
        assert "favorite" not in {
            column["name"] for column in inspector.get_columns("resume_record")
        }
        with migration_engine.connect() as connection:
            row = connection.execute(
                text("SELECT id, title, job_id FROM resume_record WHERE id = :resume_id"),
                {"resume_id": resume_id},
            ).one()
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert row == (resume_id, "Backend Resume", job_id)
        assert revision == BASELINE_REVISION

        command.upgrade(config, "head")
        _assert_head_schema(migration_engine)
        with migration_engine.connect() as connection:
            restored_job_id = connection.execute(
                text("SELECT job_id FROM resume_record WHERE id = :resume_id"),
                {"resume_id": resume_id},
            ).scalar_one()
            restored_favorite = connection.execute(
                text("SELECT favorite FROM resume_record WHERE id = :resume_id"),
                {"resume_id": resume_id},
            ).scalar_one()
        assert restored_job_id == job_id
        assert restored_favorite == 0
    finally:
        migration_engine.dispose()


def test_alembic_downgrade_handles_legacy_anonymous_resume_foreign_key(tmp_path):
    migration_engine = create_engine(f"sqlite:///{tmp_path / 'anonymous-fk.db'}")
    config = build_alembic_config(migration_engine)
    try:
        Base.metadata.create_all(migration_engine)
        with migration_engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO resume_record "
                "(title, job_id, job_title, company, content, warnings, source, model, tone, "
                "favorite, enhancement_enabled, enhancement_level, parse_error, created_at) "
                "VALUES ('孤立记录', 999, '', '', '{}', '[]', 'ai', '', 'standard', 0, 0, "
                "'balanced', '', '2026-08-18')"
            )
        command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, "head")

        with migration_engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT job_id FROM resume_record WHERE title = '孤立记录'"
            ).scalar_one() is None

        assert any(
            item["referred_table"] == "job" and item["constrained_columns"] == ["job_id"]
            for item in inspect(migration_engine).get_foreign_keys("resume_record")
        )

        command.downgrade(config, BASELINE_REVISION)

        assert not any(
            item["referred_table"] == "job" and item["constrained_columns"] == ["job_id"]
            for item in inspect(migration_engine).get_foreign_keys("resume_record")
        )
    finally:
        migration_engine.dispose()


@pytest.mark.parametrize("table_name", sorted(_APPLICATION_TABLES))
def test_migration_runner_backs_up_data_from_any_application_table(tmp_path, table_name):
    database_path = tmp_path / f"orphan-{table_name}.db"
    partial_engine = create_engine(f"sqlite:///{database_path}")
    try:
        quoted_table = partial_engine.dialect.identifier_preparer.quote(table_name)
        with partial_engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE TABLE {quoted_table} (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql(f"INSERT INTO {quoted_table} (id) VALUES (1)")

        backup_path = run_database_migrations(partial_engine)

        assert backup_path is not None and backup_path.exists()
        backup_engine = create_engine(f"sqlite:///{backup_path}")
        try:
            with backup_engine.connect() as connection:
                row_count = connection.exec_driver_sql(
                    f"SELECT COUNT(*) FROM {quoted_table}"
                ).scalar_one()
        finally:
            backup_engine.dispose()
        assert row_count == 1
    finally:
        partial_engine.dispose()
