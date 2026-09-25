"""搜索历史迁移只加表，支持重复升级以及从旧库升级。"""

from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config
from app.models.official import OfficialDiscoverySearch

PREVIOUS_REVISION = "0023_drop_source_trend"
HEAD_REVISION = "0024_official_discovery_history"
TABLE = "official_discovery_search"


def test_upgrade_only_adds_search_history_table_and_matches_model(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        before = set(inspect(engine).get_table_names())
        command.upgrade(config, HEAD_REVISION)
        after = set(inspect(engine).get_table_names())
        assert after - before == {TABLE}
        assert before <= after
        assert {column.name for column in OfficialDiscoverySearch.__table__.columns} == {
            column["name"] for column in inspect(engine).get_columns(TABLE)
        }
        assert "ix_official_discovery_search_created_at" in {
            index["name"] for index in inspect(engine).get_indexes(TABLE)
        }
    finally:
        engine.dispose()


def test_reupgrade_keeps_existing_history(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reupgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(f"INSERT INTO {TABLE} (keywords, city, created_at) VALUES "
                     "('算法', '', '2026-09-23')")
            )
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)
        with engine.connect() as connection:
            assert connection.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() == 1
    finally:
        engine.dispose()


def test_partial_database_does_not_gain_unrelated_changes(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'partial.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(text(f"CREATE TABLE {TABLE} (id INTEGER PRIMARY KEY)"))
        command.upgrade(config, HEAD_REVISION)
        assert {column["name"] for column in inspect(engine).get_columns(TABLE)} == {"id"}
    finally:
        engine.dispose()


def test_downgrade_removes_only_search_history(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        before = set(inspect(engine).get_table_names())
        command.downgrade(config, PREVIOUS_REVISION)
        after = set(inspect(engine).get_table_names())
        assert before - after == {TABLE}
        assert {"official_site", "official_collect_run"} <= after
    finally:
        engine.dispose()
