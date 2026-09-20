"""``0020_daily_20260920_columns`` 迁移：只加两列、幂等、完整 downgrade。

与 0015 同性质：**只加列、不改表集合**——这正是"旧备份仍可导入"成立的前提。额外验两件事：
表集合前后不变，以及旧行升级后新列拿到的是空串而不是 null（界面按"没填"处理）。
"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config

PREVIOUS_REVISION = "0019_interview_history_knowledge_referral_fields"
HEAD_REVISION = "0020_daily_20260920_columns"

NEW_COLUMNS = {"resume_record": {"note"}, "candidate_job": {"job_type"}}


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _columns(engine, table: str) -> set[str]:
    return {item["name"] for item in inspect(engine).get_columns(table)}


def test_upgrade_adds_both_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'daily.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)
        assert _revision(engine) == HEAD_REVISION
        assert "note" in _columns(engine, "resume_record")
        assert "job_type" in _columns(engine, "candidate_job")
    finally:
        engine.dispose()


def test_upgrade_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'daily-idempotent.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)
        assert "note" in _columns(engine, "resume_record")
        assert "job_type" in _columns(engine, "candidate_job")
        assert _revision(engine) == HEAD_REVISION
    finally:
        engine.dispose()


def test_head_does_not_add_or_remove_any_table(tmp_path):
    """加列不该改变表集合——这正是"旧备份仍可导入"成立的前提。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'daily-tables.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        before = set(inspect(engine).get_table_names())
        command.upgrade(config, HEAD_REVISION)
        assert set(inspect(engine).get_table_names()) == before
    finally:
        engine.dispose()


def test_existing_rows_get_empty_defaults(tmp_path):
    """旧行升级后新列必须是空串，而不是 null。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'daily-default.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO resume_record (title, job_title, company, content, warnings, "
                    "source, model, tone, enhancement_enabled, enhancement_level, parse_error, "
                    "created_at) VALUES ('旧简历', '', '', '{}', '[]', 'ai', '', 'standard', 0, "
                    "'balanced', '', '2026-09-20')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO candidate_job (title, company, raw_text, images, note, source, "
                    "status, created_at, updated_at) VALUES ('旧候选', '某公司', '原文', '[]', '', "
                    "'手动添加', 'pending', '2026-09-20', '2026-09-20')"
                )
            )

        command.upgrade(config, HEAD_REVISION)

        with engine.connect() as connection:
            resume_note = connection.execute(
                text("SELECT note FROM resume_record WHERE title = '旧简历'")
            ).scalar_one()
            job_type = connection.execute(
                text("SELECT job_type FROM candidate_job WHERE title = '旧候选'")
            ).scalar_one()
        assert resume_note == ""
        assert job_type == ""
    finally:
        engine.dispose()


def test_upgrade_is_skipped_when_a_table_is_absent(tmp_path):
    """表不在时应当跳过，而不是 ALTER 到不存在的表上崩掉（迁移链可用于历史库）。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'daily-missing.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE candidate_job"))

        command.upgrade(config, HEAD_REVISION)  # 不应抛异常

        assert _revision(engine) == HEAD_REVISION
        assert "candidate_job" not in set(inspect(engine).get_table_names())
        assert "note" in _columns(engine, "resume_record")
    finally:
        engine.dispose()


def test_downgrade_removes_only_the_new_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'daily-downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.downgrade(config, PREVIOUS_REVISION)

        assert "note" not in _columns(engine, "resume_record")
        assert "job_type" not in _columns(engine, "candidate_job")
        # 原有列一个没少。
        assert {"title", "custom_instruction", "parse_error"} <= _columns(engine, "resume_record")
        assert {"title", "company", "source", "requirements"} <= _columns(engine, "candidate_job")
        assert _revision(engine) == PREVIOUS_REVISION
    finally:
        engine.dispose()
