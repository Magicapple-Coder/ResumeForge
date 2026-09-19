"""``0016_soft_delete_marks`` 迁移：加列、幂等、完整 downgrade。

加列与加表的性质不同——**旧备份导入靠的是"迁移到 head 后表集合对得上"**，而加列不改表集合，
所以这里额外验两件事：表集合前后不变，以及旧记录升级后新列是 **NULL**（NULL 才是"没删"，
若默认成某个时间戳，等于把所有历史数据一把塞进回收站）。
"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

import importlib.util
from pathlib import Path

from app.database_migrations import build_alembic_config
from app.services import trash

PREVIOUS_REVISION = "0015_candidate_job_collect_fields"
HEAD_REVISION = "0016_soft_delete_marks"


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _columns(engine, table: str) -> set[str]:
    return {item["name"] for item in inspect(engine).get_columns(table)}


def _migration_tables() -> set[str]:
    """从**迁移文件本体**读出它给哪些表加了列。

    直接读文件而不是抄一份常量：抄一份等于把"两处漂移"的问题从代码挪到测试里，
    而这条测试存在的全部意义就是发现漂移。
    """
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0016_soft_delete_marks.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0016", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return set(module.TRASHED_TABLES)


def test_the_migration_and_the_service_agree_on_which_tables_are_reclaimed():
    """0016 迁移加列的表，必须仍在回收站注册表里。

    0016 只给六张表加 ``deleted_at``；注册表随后还包含 0018 的四张新表（它们建表时就带该列）。
    "全部含 ``deleted_at`` 的表 ↔ 注册表"的一一对应，由 test_trash 的泛化断言覆盖（扫全库
    ``Base.metadata``），这里只守住 0016 这份清单不丢。
    """
    assert _migration_tables() <= set(trash.TRASHED_TABLES)
    # 0016 迁移本体仍只列六张表（它不负责 0018/0019 的新表）。
    assert len(_migration_tables()) == 6
    # 全量注册表现在是 6 + 4 + 3 = 13 类。
    assert len(trash.TRASHED_TABLES) == 13


def _insert_legacy_row(engine, table: str, **values) -> None:
    """插一行"迁移前就存在"的数据，只指定关心的列。

    ``job`` 这类表有很多 NOT NULL 列，而它们的默认值由 ORM 在 **Python 侧**给，裸 SQL 不走
    那一层。硬把列名一个个列出来会让"以后加一列就回来改测试"，所以这里按表结构自动补齐——
    补的值只要求"能插进去"，这些用例只读 ``count`` 与 ``deleted_at``。
    """
    filled = dict(values)
    for column in inspect(engine).get_columns(table):
        name = column["name"]
        if name in filled or column.get("nullable", True) or column.get("default") is not None:
            continue
        type_name = str(column["type"]).upper()
        if "JSON" in type_name:
            filled[name] = "[]"
        elif "INT" in type_name or "BOOL" in type_name:
            filled[name] = 0
        else:
            filled[name] = "2026-09-18 00:00:00" if "DATE" in type_name else ""

    names = ", ".join(filled)
    placeholders = ", ".join(f":{name}" for name in filled)
    with engine.begin() as connection:
        connection.execute(
            text(f"INSERT INTO {table} ({names}) VALUES ({placeholders})"), filled
        )


def test_upgrade_adds_the_column_to_every_trashed_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'trash.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)
        assert _revision(engine) == HEAD_REVISION
        # 0016 只给这六张表 ALTER 加列；0018 的新表在 0016 时点还不存在。
        for table in _migration_tables():
            assert "deleted_at" in _columns(engine, table), table
    finally:
        engine.dispose()


def test_upgrade_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'trash-idempotent.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)
        assert _revision(engine) == HEAD_REVISION
        for table in _migration_tables():
            assert "deleted_at" in _columns(engine, table), table
    finally:
        engine.dispose()


def test_head_does_not_add_or_remove_any_table(tmp_path):
    """加列不该改变表集合——这正是"旧备份仍可导入"成立的前提。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'trash-tables.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        before = set(inspect(engine).get_table_names())
        command.upgrade(config, HEAD_REVISION)
        assert set(inspect(engine).get_table_names()) == before
    finally:
        engine.dispose()


def test_existing_rows_are_not_thrown_into_the_trash(tmp_path):
    """旧记录升级后 ``deleted_at`` 必须是 NULL。

    这一条比"能不能加列"重要得多：如果新列的默认值是个时间戳（或用 ``server_default=now()``），
    升级后**用户所有历史数据会一次性全部出现在回收站里**——看起来就像"数据全被删了"。
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'trash-default.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        _insert_legacy_row(engine, "job", title="旧岗位", company="某公司")

        command.upgrade(config, HEAD_REVISION)

        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(1) FROM job")).scalar_one() == 1
            assert (
                connection.execute(text("SELECT deleted_at FROM job")).scalar_one() is None
            )
    finally:
        engine.dispose()


def test_upgrade_is_skipped_when_a_table_is_absent(tmp_path):
    """历史库里可能压根没有某张表：表不存在时应当**跳过**，而不是 ALTER 到不存在的表上崩掉。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'trash-missing-table.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE material"))

        command.upgrade(config, HEAD_REVISION)  # 不应抛异常

        assert _revision(engine) == HEAD_REVISION
        assert "material" not in set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_downgrade_removes_the_column_but_keeps_the_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'trash-downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        _insert_legacy_row(engine, "job", title="普通岗位", company="某公司")
        command.downgrade(config, PREVIOUS_REVISION)

        job_columns = _columns(engine, "job")
        assert "deleted_at" not in job_columns
        # 原有列一个没少，数据也还在（降级只是丢掉"删除标记"，不是丢数据）。
        assert {"title", "company", "source_url"} <= job_columns
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(1) FROM job")).scalar_one() == 1
        assert _revision(engine) == PREVIOUS_REVISION
    finally:
        engine.dispose()
