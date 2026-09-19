"""``0017_resume_generate_task`` 迁移：只加表、幂等、完整 downgrade、表集合不变。

「旧备份仍可导入」靠的是"迁移到 head 后表集合对得上"，而只加表会改变表集合，所以
这里额外验：升级后表集合**多出且只多出**这一张新表（其余不变），以及 downgrade 能
把这张表干净地拆掉、不回退到 0016 时的表集合。
"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config

PREVIOUS_REVISION = "0016_soft_delete_marks"
HEAD_REVISION = "0017_resume_generate_task"

EXPECTED_COLUMNS = {
    "id",
    "status",
    "resume_id",
    "error",
    "message",
    "received_chars",
    "job_id",
    "title",
    "options",
    "created_at",
    "started_at",
    "finished_at",
}

EXPECTED_INDEXES = {
    "ix_resume_generate_task_status",
    "ix_resume_generate_task_job_id",
    "ix_resume_generate_task_created_at",
}


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_upgrade_creates_the_generate_task_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'generate-task.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)

        inspector = inspect(engine)
        assert "resume_generate_task" in inspector.get_table_names()
        assert _revision(engine) == HEAD_REVISION
        assert {
            item["name"] for item in inspector.get_columns("resume_generate_task")
        } == EXPECTED_COLUMNS
        assert EXPECTED_INDEXES <= {
            item["name"] for item in inspector.get_indexes("resume_generate_task")
        }
    finally:
        engine.dispose()


def test_upgrade_adds_exactly_one_table(tmp_path):
    """只加表、不改既有表：这正是"旧备份仍可导入"成立的前提。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'generate-task-tables.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        before = set(inspect(engine).get_table_names())
        command.upgrade(config, HEAD_REVISION)
        after = set(inspect(engine).get_table_names())
        assert after - before == {"resume_generate_task"}
        assert before - after == set()
    finally:
        engine.dispose()


def test_upgrade_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'generate-task-idempotent.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)

        assert "resume_generate_task" in inspect(engine).get_table_names()
        assert _revision(engine) == HEAD_REVISION
    finally:
        engine.dispose()


def test_downgrade_drops_only_the_generate_task_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'generate-task-downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.downgrade(config, PREVIOUS_REVISION)

        inspector = inspect(engine)
        assert "resume_generate_task" not in inspector.get_table_names()
        assert {"job", "resume_record"} <= set(inspector.get_table_names())
        assert _revision(engine) == PREVIOUS_REVISION
    finally:
        engine.dispose()


def test_defaults_match_the_model_constants(tmp_path):
    """迁移里的 server_default 必须与模型常量一致，否则升级库与新建库表现不同。"""
    from app.models.resume import GENERATE_STATUS_PENDING

    engine = create_engine(f"sqlite:///{tmp_path / 'generate-task-defaults.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO resume_generate_task (created_at) VALUES ('2026-09-18')")
            )
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT status, resume_id, error, message, received_chars, job_id, "
                    "title, options, started_at, finished_at FROM resume_generate_task"
                )
            ).one()

        assert row.status == GENERATE_STATUS_PENDING
        assert row.received_chars == 0
        assert row.error == "" and row.message == "" and row.title == ""
        # 裸 SQL 读 JSON 列得到的是其底层 TEXT 值（'{}' 字符串），而不是反序列化后的 dict。
        assert row.options == "{}"
        assert row.resume_id is None and row.job_id is None
        assert row.started_at is None and row.finished_at is None
    finally:
        engine.dispose()
