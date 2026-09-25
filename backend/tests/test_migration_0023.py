"""``0023_drop_source_trend`` 迁移：删掉一张没人读的重复表。

这条迁移的特殊之处是**它减表**（其余迁移都是加表），所以除了幂等与降级，还要专门验一件事：
**"旧备份仍可导入"的前提没有被破坏**——无论备份来自这张表存在之前还是之后，
迁到 head 之后表集合都必须与当前代码一致。
"""
from alembic import command
from sqlalchemy import create_engine, inspect

from app.database_migrations import build_alembic_config

PREVIOUS_REVISION = "0022_official_site_collect"
HEAD_REVISION = "0023_drop_source_trend"
TABLE = "official_source_trend"


def _tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_upgrade_removes_the_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'drop.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        assert TABLE in _tables(engine), "前置条件：这一版它还在"

        command.upgrade(config, HEAD_REVISION)

        assert TABLE not in _tables(engine)
        # 同一批里的另外两张表不受影响。
        assert {"official_site", "official_collect_run"} <= _tables(engine)
    finally:
        engine.dispose()


def test_upgrade_is_idempotent_when_the_table_is_already_absent(tmp_path):
    """表不在时要跳过而不是报错——迁移链会跑在"本来就没有这张表"的历史库上。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'absent.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP TABLE {TABLE}")

        command.upgrade(config, HEAD_REVISION)  # 不应抛异常
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)

        assert TABLE not in _tables(engine)
    finally:
        engine.dispose()


def test_downgrade_brings_the_table_back(tmp_path):
    """降级要能真的回到上一版——它把表按原样建回来，连同索引与外键语义。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'back.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        assert TABLE not in _tables(engine)

        command.downgrade(config, PREVIOUS_REVISION)

        assert TABLE in _tables(engine)
        inspector = inspect(engine)
        columns = {item["name"] for item in inspector.get_columns(TABLE)}
        assert columns == {"id", "site_id", "run_id", "job_count", "recorded_at"}
        indexes = {item["name"] for item in inspector.get_indexes(TABLE)}
        assert {"ix_official_source_trend_site_id", "ix_official_source_trend_recorded_at"} <= indexes
        # 外键的删除语义也要回来：源删掉时计数跟着走。
        assert any(
            item["referred_table"] == "official_site"
            and item["options"].get("ondelete") == "CASCADE"
            for item in inspector.get_foreign_keys(TABLE)
        )
    finally:
        engine.dispose()


def test_head_table_set_matches_the_models(tmp_path):
    """移到 head 后，表集合与代码里的模型**完全一致**。

    减表类迁移最容易出岔子的地方：库里删掉了、模型里忘了删（或反过来），
    而症状是运行期才炸。这里逐表比对。
    """
    from app.database import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'match.db'}")
    try:
        # 这项断言验证的是**当前迁移 head**与 ORM 模型的表集合；
        # 0024 之后不能再停在本迁移自己的 revision，否则新表会被误报成模型孤儿。
        command.upgrade(build_alembic_config(engine), "head")
        expected = set(Base.metadata.tables)
        actual = _tables(engine) - {"alembic_version"}
        assert actual == expected, (
            f"仅库里有 {sorted(actual - expected)}，仅模型里有 {sorted(expected - actual)}"
        )
        assert TABLE not in expected
    finally:
        engine.dispose()


def test_a_backup_from_before_the_table_existed_still_lands_on_head(tmp_path):
    """**旧备份仍可导入**：一份来自 0021（表的诞生之前）的库迁到 head 后表集合正确。

    减表迁移若不幂等，这一条就会因为"要删一张不存在的表"而崩。
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, "0021_candidate_additional_info")
        assert TABLE not in _tables(engine)

        command.upgrade(config, HEAD_REVISION)

        assert TABLE not in _tables(engine)
        assert {"official_site", "official_collect_run"} <= _tables(engine)
    finally:
        engine.dispose()
