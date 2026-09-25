"""``0022_official_site_collect`` 迁移：只加三张表、幂等、完整 downgrade。

**注意**：``official_source_trend`` 已在 ``0023`` 里被删掉（它的计数在运行记录里已有）。
本文件仍然断言它在 0022 那一版存在——那是历史事实，不该因为后来删了就改掉。


与 0010/0014 同性质：**只加表**——这正是"旧备份仍可导入"成立的前提。额外验三件事：
表集合只增不减、表已存在时跳过、以及 **ORM 定义与迁移定义逐列一致**（三张表的列不少，
两边各写一遍迟早写歪，而写歪的表现是运行期才炸）。
"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config
from app.models import OfficialCollectRun, OfficialSite

PREVIOUS_REVISION = "0021_candidate_additional_info"
HEAD_REVISION = "0022_official_site_collect"

NEW_TABLES = ("official_site", "official_collect_run", "official_source_trend")


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _columns(engine, table: str) -> set[str]:
    return {item["name"] for item in inspect(engine).get_columns(table)}


def test_upgrade_creates_the_three_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'official.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)
        assert _revision(engine) == HEAD_REVISION
        tables = set(inspect(engine).get_table_names())
        assert set(NEW_TABLES) <= tables
    finally:
        engine.dispose()


def test_upgrade_only_adds_tables(tmp_path):
    """只加表：既有的表一个都不能少、也不能改。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'official-only-add.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        before = set(inspect(engine).get_table_names())
        command.upgrade(config, HEAD_REVISION)
        after = set(inspect(engine).get_table_names())

        assert before <= after, "升级过程删掉了既有的表"
        assert after - before == set(NEW_TABLES), "新增的表不止这三张"
    finally:
        engine.dispose()


def test_upgrade_is_idempotent(tmp_path):
    """表已存在时跳过，不重建——迁移链会在已经跑过一次的库上重复执行。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'official-idempotent.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO official_site (company, homepage_url, careers_url, source_kind, "
                    "endpoint, params, confidence, probe_evidence, recipe, recipe_version, "
                    "robots_detail, min_interval_seconds, max_per_hour, enabled, created_at, "
                    "updated_at) VALUES ('示例公司', '', '', '', '', '{}', '', '', '{}', '', '', "
                    "10, 120, 1, '2026-09-23', '2026-09-23')"
                )
            )

        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)

        with engine.connect() as connection:
            count = connection.execute(text("SELECT COUNT(*) FROM official_site")).scalar_one()
        assert count == 1, "重复执行迁移把已有数据清掉了"
    finally:
        engine.dispose()


def test_upgrade_is_skipped_when_tables_already_exist(tmp_path):
    """表不在迁移链管辖内也不该崩——迁移链会被用在"只有部分业务表的历史库"上。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'official-partial.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            for table in NEW_TABLES:
                connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))

        command.upgrade(config, HEAD_REVISION)  # 不应抛异常

        assert _revision(engine) == HEAD_REVISION
        # 已存在的那张（简表）没有被重建。
        assert _columns(engine, "official_site") == {"id"}
    finally:
        engine.dispose()


def test_downgrade_drops_them_in_dependency_order(tmp_path):
    """先删依赖方再删被依赖方——顺序反了在有数据时会因外键约束失败。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'official-downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO official_site (company, created_at, updated_at) "
                    "VALUES ('示例公司', '2026-09-23', '2026-09-23')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO official_collect_run (site_id, status, started_at) "
                    "VALUES (1, 'done', '2026-09-23')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO official_source_trend (site_id, run_id, job_count, recorded_at) "
                    "VALUES (1, 1, 12, '2026-09-23')"
                )
            )

        command.downgrade(config, PREVIOUS_REVISION)

        tables = set(inspect(engine).get_table_names())
        assert not (set(NEW_TABLES) & tables)
        assert _revision(engine) == PREVIOUS_REVISION
        # 既有表一个没少。
        assert "job" in tables and "candidate_job" in tables
    finally:
        engine.dispose()


def test_orm_and_migration_definitions_agree(tmp_path):
    """ORM 与迁移逐列一致。

    这两份定义各写一遍，写歪了不会在导入期暴露，而是等到某个功能去读一列不存在的字段时
    才炸。逐列比对是这条链路上最便宜的一道闸门。
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'official-columns.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)
        for model in (OfficialSite, OfficialCollectRun):
            table = model.__tablename__
            orm_columns = {column.name for column in model.__table__.columns}
            migrated_columns = _columns(engine, table)
            assert orm_columns == migrated_columns, (
                f"{table} 的 ORM 定义与迁移不一致："
                f"仅 ORM 有 {sorted(orm_columns - migrated_columns)}，"
                f"仅迁移有 {sorted(migrated_columns - orm_columns)}"
            )
    finally:
        engine.dispose()
