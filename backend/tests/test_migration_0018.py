"""``0018_...`` 迁移：只加 4 表、幂等、完整 downgrade、表集合前后只多这 4 张。

「旧备份仍可导入」靠的是"迁移到 head 后表集合对得上"，而只加表会改变表集合，所以
这里额外验：升级后表集合**多出且只多出**这四张新表（其余不变），以及 downgrade 能把
这四张表干净地拆掉、回到 0017 时的表集合。
"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config

PREVIOUS_REVISION = "0017_resume_generate_task"
HEAD_REVISION = "0018_referral_reminder_interview_experience_share_package"

NEW_TABLES = ("referral", "reminder", "interview_experience", "share_package")

EXPECTED_COLUMNS = {
    "referral": {
        "id", "job_id", "job_title", "company", "referrer_name", "referrer_contact",
        "relation", "position", "channel", "status", "track_id", "converted",
        "submitted_at", "note", "created_at", "updated_at", "deleted_at",
    },
    "reminder": {
        "id", "title", "remind_at", "kind", "status", "track_id", "job_id",
        "resume_id", "note", "created_at", "updated_at", "deleted_at",
    },
    "interview_experience": {
        "id", "title", "company", "position", "job_id", "content", "questions",
        "tags", "source", "difficulty", "round_type", "interview_date",
        "created_at", "updated_at", "deleted_at",
    },
    "share_package": {
        "id", "title", "resume_id", "job_id", "files", "permission", "snapshot",
        "comments_file", "share_token", "redaction_config", "created_at",
        "updated_at", "deleted_at",
    },
}

EXPECTED_INDEXES = {
    "referral": {"ix_referral_job_id", "ix_referral_status"},
    "reminder": {"ix_reminder_remind_at", "ix_reminder_status", "ix_reminder_job_id"},
    "interview_experience": {
        "ix_interview_experience_company",
        "ix_interview_experience_job_id",
    },
    "share_package": {"ix_share_package_resume_id", "ix_share_package_share_token"},
}


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_upgrade_creates_the_four_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't01-tables.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)

        inspector = inspect(engine)
        assert _revision(engine) == HEAD_REVISION
        for table in NEW_TABLES:
            assert table in inspector.get_table_names()
            assert {
                item["name"] for item in inspector.get_columns(table)
            } == EXPECTED_COLUMNS[table]
            assert EXPECTED_INDEXES[table] <= {
                item["name"] for item in inspector.get_indexes(table)
            }
    finally:
        engine.dispose()


def test_upgrade_adds_exactly_four_tables(tmp_path):
    """只加表、不改既有表：这正是"旧备份仍可导入"成立的前提。"""
    engine = create_engine(f"sqlite:///{tmp_path / 't01-table-set.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        before = set(inspect(engine).get_table_names())
        command.upgrade(config, HEAD_REVISION)
        after = set(inspect(engine).get_table_names())
        assert after - before == set(NEW_TABLES)
        assert before - after == set()
    finally:
        engine.dispose()


def test_upgrade_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't01-idempotent.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)

        for table in NEW_TABLES:
            assert table in inspect(engine).get_table_names()
        assert _revision(engine) == HEAD_REVISION
    finally:
        engine.dispose()


def test_downgrade_drops_only_the_four_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't01-downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.downgrade(config, PREVIOUS_REVISION)

        inspector = inspect(engine)
        for table in NEW_TABLES:
            assert table not in inspector.get_table_names()
        assert {"job", "resume_record", "application_track"} <= set(inspector.get_table_names())
        assert _revision(engine) == PREVIOUS_REVISION
    finally:
        engine.dispose()


def test_defaults_match_the_model_constants(tmp_path):
    """迁移里的 server_default 必须与模型常量一致，否则升级库与新建库表现不同。"""
    engine = create_engine(f"sqlite:///{tmp_path / 't01-defaults.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO referral (created_at, updated_at) VALUES ('2026-09-19', '2026-09-19')")
            )
            connection.execute(
                text(
                    "INSERT INTO reminder (remind_at, created_at, updated_at) "
                    "VALUES ('2026-09-19 10:00:00', '2026-09-19', '2026-09-19')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO interview_experience (created_at, updated_at) "
                    "VALUES ('2026-09-19', '2026-09-19')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO share_package (share_token, created_at, updated_at) "
                    "VALUES ('tok', '2026-09-19', '2026-09-19')"
                )
            )
        with engine.connect() as connection:
            referral = connection.execute(
                text("SELECT status, converted FROM referral")
            ).one()
            reminder = connection.execute(
                text("SELECT kind, status FROM reminder")
            ).one()
            experience = connection.execute(
                text("SELECT source, questions, tags FROM interview_experience")
            ).one()
            package = connection.execute(
                text("SELECT permission, files, snapshot FROM share_package")
            ).one()

        assert referral.status == "active" and referral.converted == 0
        assert reminder.kind == "other" and reminder.status == "pending"
        assert experience.source == "self"
        assert experience.questions == "[]" and experience.tags == "[]"
        assert package.permission == "read_only"
        assert package.files == "[]" and package.snapshot == "{}"
    finally:
        engine.dispose()
