"""``0013_resume_format_config`` 迁移：加列、幂等与完整 downgrade。

加列与加表的性质不同——**旧备份导入靠的是"迁移到 head 后表集合对得上"**，而加列不改
表集合，所以这里额外验一件事：旧记录升级后新列有默认值，渲染结果与升级前一致。
"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config

PREVIOUS_REVISION = "0012_application_tracker"
HEAD_REVISION = "0013_resume_format_config"


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _columns(engine, table: str) -> set[str]:
    return {item["name"] for item in inspect(engine).get_columns(table)}


def test_upgrade_adds_the_column(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fmt.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)
        assert _revision(engine) == HEAD_REVISION
        assert "format_config" in _columns(engine, "resume_record")
    finally:
        engine.dispose()


def test_upgrade_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fmt-idempotent.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)
        assert "format_config" in _columns(engine, "resume_record")
        assert _revision(engine) == HEAD_REVISION
    finally:
        engine.dispose()


def test_existing_rows_get_an_empty_default(tmp_path):
    """旧简历升级后覆盖必须是空对象——空对象等于"没有覆盖"，渲染结果与升级前一致。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'fmt-default.db'}")
    config = build_alembic_config(engine)
    try:
        # 先升到 0012、写一条简历，再升到 0013，模拟真实升级路径。
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    # 只给 NOT NULL 且无默认值的列赋值，其余走建表时的默认值——
                    # 这样这条 SQL 模拟的就是"迁移前的库里已经躺着一份简历"。
                    "INSERT INTO resume_record (title, job_title, company, content, warnings, "
                    "source, model, tone, enhancement_enabled, enhancement_level, parse_error, "
                    "created_at) VALUES ('旧简历', '', '', '{}', '[]', 'ai', '', 'standard', "
                    "0, 'balanced', '', '2026-09-18')"
                )
            )

        command.upgrade(config, HEAD_REVISION)

        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT count(1) FROM resume_record")).scalar_one() == 1
            )
            assert connection.execute(
                text("SELECT format_config FROM resume_record")
            ).scalar_one() == "{}"
    finally:
        engine.dispose()


def test_downgrade_removes_only_that_column(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fmt-downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.downgrade(config, PREVIOUS_REVISION)

        assert "format_config" not in _columns(engine, "resume_record")
        # 同一张表的其它列一个没少，投递表也还在。
        assert {"template", "format_name", "page_limit", "font_scale"} <= _columns(
            engine, "resume_record"
        )
        assert "application_track" in set(inspect(engine).get_table_names())
        assert _revision(engine) == PREVIOUS_REVISION
    finally:
        engine.dispose()


def test_round_trip_keeps_the_resume_content(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fmt-roundtrip.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO resume_record (title, job_title, company, content, warnings, "
                    "source, model, tone, enhancement_enabled, enhancement_level, parse_error, "
                    "format_config, created_at) VALUES ('带覆盖的简历', '', '', "
                    "'{\"name\": \"张三\"}', '[]', 'ai', '', 'standard', 0, 'balanced', '', "
                    "'{\"line_height\": 1.4}', '2026-09-18')"
                )
            )

        command.downgrade(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)

        with engine.connect() as connection:
            # 列被删掉又加回来，覆盖值随之丢失（不可逆，符合预期）；正文还在。
            assert connection.execute(
                text("SELECT count(1) FROM resume_record")
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT title FROM resume_record")
            ).scalar_one() == "带覆盖的简历"
            assert connection.execute(
                text("SELECT format_config FROM resume_record")
            ).scalar_one() == "{}"
    finally:
        engine.dispose()


def test_head_does_not_add_or_remove_any_table(tmp_path):
    """加列不该改变表集合——这正是"旧备份仍可导入"成立的前提。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'fmt-tables.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        before = set(inspect(engine).get_table_names())
        command.upgrade(config, HEAD_REVISION)
        assert set(inspect(engine).get_table_names()) == before
    finally:
        engine.dispose()
