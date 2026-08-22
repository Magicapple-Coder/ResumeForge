"""SQLite 兼容升级测试。"""
import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database import Base, ensure_sqlite_columns
from app.database_migrations import (
    BASELINE_REVISION,
    build_alembic_config,
    is_unversioned_legacy_database,
    run_database_migrations,
)
from app.main import SQLITE_REQUIRED_COLUMNS
from app.models import Job, ResumeRecord

_APPLICATION_TABLES = {
    "job",
    "user_profile",
    "education",
    "experience",
    "campus_experience",
    "project",
    "skill",
    "award",
    "resume_record",
    "app_setting",
    "llm_config_record",
    "chat_conversation",
    "chat_message",
}


def _assert_head_schema(bind) -> None:
    inspector = inspect(bind)
    assert set(inspector.get_table_names()) == _APPLICATION_TABLES | {"alembic_version"}
    for table_name in _APPLICATION_TABLES:
        expected_columns = {column.name for column in Base.metadata.tables[table_name].columns}
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert actual_columns == expected_columns

    assert {"ix_job_status", "ix_job_created_at"} <= {
        item["name"] for item in inspector.get_indexes("job")
    }
    assert {"ix_resume_record_job_id", "ix_resume_record_created_at"} <= {
        item["name"] for item in inspector.get_indexes("resume_record")
    }
    assert any(
        item["referred_table"] == "job" and item["constrained_columns"] == ["job_id"]
        for item in inspector.get_foreign_keys("resume_record")
    )
    assert "ix_chat_conversation_updated_at" in {
        item["name"] for item in inspector.get_indexes("chat_conversation")
    }
    assert {"ix_chat_message_conversation_id", "ix_chat_message_created_at"} <= {
        item["name"] for item in inspector.get_indexes("chat_message")
    }
    assert any(
        item["referred_table"] == "chat_conversation"
        and item["constrained_columns"] == ["conversation_id"]
        for item in inspector.get_foreign_keys("chat_message")
    )
    with bind.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "0006_chat_conversation_flags"


def test_ensure_sqlite_columns_preserves_legacy_rows(tmp_path):
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    try:
        with legacy_engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE job (id INTEGER PRIMARY KEY, title VARCHAR(128) NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO job (id, title) VALUES (1, '算法工程师')"
            )
            connection.exec_driver_sql(
                "CREATE TABLE user_profile (id INTEGER PRIMARY KEY, name VARCHAR(64) NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO user_profile (id, name) VALUES (1, '张三')"
            )
            connection.exec_driver_sql(
                "CREATE TABLE education "
                "(id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, school VARCHAR(128) NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO education (id, profile_id, school) VALUES (1, 1, '示例大学')"
            )
            connection.exec_driver_sql(
                "CREATE TABLE experience "
                "(id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, company VARCHAR(128) NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO experience (id, profile_id, company) VALUES (1, 1, '示例科技')"
            )
            connection.exec_driver_sql(
                "CREATE TABLE campus_experience "
                "(id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, "
                "organization VARCHAR(128) NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO campus_experience (id, profile_id, organization) "
                "VALUES (1, 1, '学生会')"
            )
            connection.exec_driver_sql(
                "CREATE TABLE project "
                "(id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, name VARCHAR(128) NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO project (id, profile_id, name) VALUES (1, 1, '简历通')"
            )
            connection.exec_driver_sql(
                "CREATE TABLE resume_record "
                "(id INTEGER PRIMARY KEY, title VARCHAR(256) NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO resume_record (id, title) VALUES (1, '后端岗位简历')"
            )

        ensure_sqlite_columns(legacy_engine, SQLITE_REQUIRED_COLUMNS)
        ensure_sqlite_columns(legacy_engine, SQLITE_REQUIRED_COLUMNS)

        inspector = inspect(legacy_engine)
        assert "note" in {column["name"] for column in inspector.get_columns("job")}
        assert "photo" in {
            column["name"] for column in inspector.get_columns("user_profile")
        }
        for table_name in ("education", "experience", "campus_experience", "project"):
            column_names = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            assert {"reference_file_name", "reference_content"} <= column_names
        assert {"enhancement_enabled", "enhancement_level"} <= {
            column["name"] for column in inspector.get_columns("resume_record")
        }
        with legacy_engine.connect() as connection:
            job = connection.exec_driver_sql(
                "SELECT title, note, favorite FROM job WHERE id = 1"
            ).mappings().one()
            profile = connection.exec_driver_sql(
                "SELECT name, photo, section_order FROM user_profile WHERE id = 1"
            ).mappings().one()
            education = connection.exec_driver_sql(
                "SELECT school, reference_file_name, reference_content "
                "FROM education WHERE id = 1"
            ).mappings().one()
            experience = connection.exec_driver_sql(
                "SELECT company, reference_file_name, reference_content "
                "FROM experience WHERE id = 1"
            ).mappings().one()
            campus = connection.exec_driver_sql(
                "SELECT organization, reference_file_name, reference_content "
                "FROM campus_experience WHERE id = 1"
            ).mappings().one()
            project = connection.exec_driver_sql(
                "SELECT name, reference_file_name, reference_content "
                "FROM project WHERE id = 1"
            ).mappings().one()
            resume = connection.exec_driver_sql(
                "SELECT title, enhancement_enabled, enhancement_level "
                "FROM resume_record WHERE id = 1"
            ).mappings().one()
        assert dict(job) == {"title": "算法工程师", "note": "", "favorite": 0}
        assert dict(profile) == {"name": "张三", "photo": "", "section_order": "[]"}
        assert dict(education) == {
            "school": "示例大学",
            "reference_file_name": "",
            "reference_content": "",
        }
        assert dict(experience) == {
            "company": "示例科技",
            "reference_file_name": "",
            "reference_content": "",
        }
        assert dict(campus) == {
            "organization": "学生会",
            "reference_file_name": "",
            "reference_content": "",
        }
        assert dict(project) == {
            "name": "简历通",
            "reference_file_name": "",
            "reference_content": "",
        }
        assert dict(resume) == {
            "title": "后端岗位简历",
            "enhancement_enabled": 0,
            "enhancement_level": "balanced",
        }
    finally:
        legacy_engine.dispose()


def test_alembic_migration_preserves_rows_repairs_fk_and_is_idempotent(tmp_path):
    database_path = tmp_path / "migration.db"
    legacy_engine = create_engine(f"sqlite:///{database_path}")
    try:
        with legacy_engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE job ("
                "id INTEGER PRIMARY KEY, title VARCHAR(128) NOT NULL, "
                "status VARCHAR(16) NOT NULL, created_at DATETIME NOT NULL)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE resume_record ("
                "id INTEGER PRIMARY KEY, title VARCHAR(256) NOT NULL, "
                "job_id INTEGER, created_at DATETIME NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO job VALUES (1, '算法工程师', '开放中', '2026-08-18')"
            )
            connection.exec_driver_sql(
                "INSERT INTO resume_record VALUES "
                "(1, '有效简历', 1, '2026-08-18'), "
                "(2, '孤立简历', 999, '2026-08-18')"
            )

        backup_path = run_database_migrations(legacy_engine)

        inspector = inspect(legacy_engine)
        assert backup_path is not None and backup_path.exists()
        assert {"ix_job_status", "ix_job_created_at"} <= {
            item["name"] for item in inspector.get_indexes("job")
        }
        assert {"ix_resume_record_job_id", "ix_resume_record_created_at"} <= {
            item["name"] for item in inspector.get_indexes("resume_record")
        }
        assert any(
            item["referred_table"] == "job" and item["constrained_columns"] == ["job_id"]
            for item in inspector.get_foreign_keys("resume_record")
        )
        with legacy_engine.connect() as connection:
            rows = connection.execute(
                text("SELECT id, title, job_id, favorite FROM resume_record ORDER BY id")
            ).all()
            additional_info = connection.execute(
                text("SELECT additional_info FROM job WHERE id = 1")
            ).scalar_one()
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert rows == [(1, "有效简历", 1, 0), (2, "孤立简历", None, 0)]
        assert additional_info == ""
        assert revision == "0006_chat_conversation_flags"
        assert run_database_migrations(legacy_engine) is None
    finally:
        legacy_engine.dispose()


def test_alembic_upgrade_head_builds_schema_from_empty_database(tmp_path):
    empty_engine = create_engine(f"sqlite:///{tmp_path / 'alembic-empty.db'}")
    try:
        command.upgrade(build_alembic_config(empty_engine), "head")

        _assert_head_schema(empty_engine)
    finally:
        empty_engine.dispose()


def test_chat_flags_migration_preserves_existing_messages(tmp_path):
    migration_engine = create_engine(f"sqlite:///{tmp_path / 'chat-flags.db'}")
    config = build_alembic_config(migration_engine)
    try:
        command.upgrade(config, "0005_chat_assistant")
        with migration_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO chat_conversation "
                    "(id, title, created_at, updated_at) "
                    "VALUES (1, '保留会话', '2026-08-22', '2026-08-22')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO chat_message "
                    "(id, conversation_id, role, content, attachments, context, status, error, model, created_at) "
                    "VALUES (1, 1, 'user', '历史消息', '[]', '{}', 'complete', '', '', '2026-08-22')"
                )
            )

        command.upgrade(config, "head")

        with migration_engine.connect() as connection:
            assert connection.execute(text("SELECT count(1) FROM chat_message")).scalar_one() == 1
            assert connection.execute(
                text("SELECT content FROM chat_message WHERE id = 1")
            ).scalar_one() == "历史消息"
            assert connection.execute(
                text("SELECT pinned, favorite FROM chat_conversation WHERE id = 1")
            ).one() == (0, 0)
    finally:
        migration_engine.dispose()


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
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
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
