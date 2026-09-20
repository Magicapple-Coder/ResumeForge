"""``0021_candidate_additional_info`` 迁移：只加一列、幂等、完整 downgrade。

与 0015/0020 同性质：**只加列、不改表集合**——这正是"旧备份仍可导入"成立的前提。
额外验两件事：表集合前后不变，以及旧行升级后新列拿到的是空串而不是 null。
"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config

PREVIOUS_REVISION = "0020_daily_20260920_columns"
HEAD_REVISION = "0021_candidate_additional_info"


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _columns(engine, table: str) -> set[str]:
    return {item["name"] for item in inspect(engine).get_columns(table)}


def test_upgrade_adds_the_column(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'additional.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)
        assert _revision(engine) == HEAD_REVISION
        assert "additional_info" in _columns(engine, "candidate_job")
    finally:
        engine.dispose()


def test_upgrade_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'additional-idempotent.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)
        assert "additional_info" in _columns(engine, "candidate_job")
        assert _revision(engine) == HEAD_REVISION
    finally:
        engine.dispose()


def test_head_does_not_add_or_remove_any_table(tmp_path):
    """加列不该改变表集合——这正是"旧备份仍可导入"成立的前提。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'additional-tables.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        before = set(inspect(engine).get_table_names())
        command.upgrade(config, HEAD_REVISION)
        assert set(inspect(engine).get_table_names()) == before
    finally:
        engine.dispose()


def test_existing_rows_get_empty_default(tmp_path):
    """旧行升级后新列必须是空串，而不是 null（界面按"没填"渲染）。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'additional-default.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO candidate_job (title, company, raw_text, images, note, source, "
                    "status, created_at, updated_at) VALUES ('旧候选', '某公司', '原文', '[]', '', "
                    "'手动添加', 'pending', '2026-09-20', '2026-09-20')"
                )
            )

        command.upgrade(config, HEAD_REVISION)

        with engine.connect() as connection:
            value = connection.execute(
                text("SELECT additional_info FROM candidate_job WHERE title = '旧候选'")
            ).scalar_one()
        assert value == ""
    finally:
        engine.dispose()


def test_upgrade_is_skipped_when_the_table_is_absent(tmp_path):
    """表不在时应当跳过，而不是 ALTER 到不存在的表上崩掉（迁移链可用于历史库）。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'additional-missing.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE candidate_job"))

        command.upgrade(config, HEAD_REVISION)  # 不应抛异常

        assert _revision(engine) == HEAD_REVISION
        assert "candidate_job" not in set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_downgrade_removes_only_the_new_column(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'additional-downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.downgrade(config, PREVIOUS_REVISION)

        assert "additional_info" not in _columns(engine, "candidate_job")
        # 原有列一个没少。
        assert {"title", "company", "source", "requirements", "description"} <= _columns(
            engine, "candidate_job"
        )
        assert _revision(engine) == PREVIOUS_REVISION
    finally:
        engine.dispose()
