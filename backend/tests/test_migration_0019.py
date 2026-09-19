"""``0019_...`` 迁移：只加 3 表 + 内推 2 列、幂等、完整 downgrade。

「旧备份仍可导入」靠的是"迁移到 head 后表集合对得上"。本迁移加表会改变表集合，所以这里验：
升级后表集合**多出且只多出**这三张新表（其余不变）、内推多出两列（其余列不变），以及
downgrade 能把这三张表与两列干净地拆掉、回到 0018 时的形态。
"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config

PREVIOUS_REVISION = "0018_referral_reminder_interview_experience_share_package"
HEAD_REVISION = "0019_interview_history_knowledge_referral_fields"

NEW_TABLES = ("question_bank_record", "interview_review_record", "knowledge_entry")
NEW_REFERRAL_COLUMNS = ("referral_code", "note_images")

EXPECTED_COLUMNS = {
    "question_bank_record": {
        "id", "job_id", "job_title", "company", "resume_id", "resume_title",
        "groups", "model", "created_at", "updated_at", "deleted_at",
    },
    "interview_review_record": {
        "id", "job_id", "job_title", "company", "resume_id", "resume_title",
        "questions", "analysis", "suggestions", "model", "created_at",
        "updated_at", "deleted_at",
    },
    "knowledge_entry": {
        "id", "title", "category", "tags", "content", "source",
        "created_at", "updated_at", "deleted_at",
    },
}

EXPECTED_INDEXES = {
    "question_bank_record": {"ix_question_bank_record_job_id"},
    "interview_review_record": {"ix_interview_review_record_job_id"},
    "knowledge_entry": {"ix_knowledge_entry_category"},
}


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _columns(engine, table: str) -> set[str]:
    return {item["name"] for item in inspect(engine).get_columns(table)}


def test_upgrade_creates_the_three_tables_and_referral_columns(tmp_path):
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
        assert set(NEW_REFERRAL_COLUMNS) <= _columns(engine, "referral")
    finally:
        engine.dispose()


def test_upgrade_adds_exactly_three_tables(tmp_path):
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
        assert set(NEW_REFERRAL_COLUMNS) <= _columns(engine, "referral")
        assert _revision(engine) == HEAD_REVISION
    finally:
        engine.dispose()


def test_downgrade_drops_only_the_three_tables_and_two_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't01-downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.downgrade(config, PREVIOUS_REVISION)

        inspector = inspect(engine)
        for table in NEW_TABLES:
            assert table not in inspector.get_table_names()
        assert {"job", "resume_record", "referral", "share_package"} <= set(
            inspector.get_table_names()
        )
        assert not (set(NEW_REFERRAL_COLUMNS) & _columns(engine, "referral"))
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
                text(
                    "INSERT INTO question_bank_record (created_at, updated_at) "
                    "VALUES ('2026-09-20', '2026-09-20')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO interview_review_record (created_at, updated_at) "
                    "VALUES ('2026-09-20', '2026-09-20')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_entry (created_at, updated_at) "
                    "VALUES ('2026-09-20', '2026-09-20')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO referral (created_at, updated_at) "
                    "VALUES ('2026-09-20', '2026-09-20')"
                )
            )
        with engine.connect() as connection:
            bank = connection.execute(
                text("SELECT groups, model FROM question_bank_record")
            ).one()
            review = connection.execute(
                text("SELECT questions, analysis, suggestions FROM interview_review_record")
            ).one()
            entry = connection.execute(
                text("SELECT category, tags FROM knowledge_entry")
            ).one()
            referral = connection.execute(
                text("SELECT referral_code, note_images FROM referral")
            ).one()

        assert bank.groups == "[]" and bank.model == ""
        assert review.questions == "[]" and review.analysis == "{}" and review.suggestions == "[]"
        assert entry.category == "" and entry.tags == "[]"
        assert referral.referral_code == "" and referral.note_images == "[]"
    finally:
        engine.dispose()
