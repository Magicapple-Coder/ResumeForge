"""``0010_apply_center`` 迁移：建表、幂等与完整 downgrade。

迁移是数据安全的落点，所以这里不只测"能跑通"，还测：重复执行不报错（幂等）、
downgrade 把 4 张表干净删掉且不误伤既有表、以及 upgrade/downgrade 往返后既有数据仍在。
"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config

APPLY_TABLES = (
    "job_match_analysis",
    "apply_queue_item",
    "apply_task",
    "apply_task_item",
)
PREVIOUS_REVISION = "0009_templates_and_interview"
# 本测试只针对 ``0010`` 自己这一版，所以显式指定 revision 而不是 "head"：
# 以后再加迁移时，"head" 会跑到新版本上去，这条测试就会因为一个与它无关的原因变红。
HEAD_REVISION = "0010_apply_center"

EXPECTED_COLUMNS = {
    "job_match_analysis": {
        "id",
        "job_id",
        "job_title",
        "company",
        "result",
        "hard_gate",
        "requires_confirm",
        "model",
        "created_at",
        "updated_at",
    },
    "apply_queue_item": {
        "id",
        "job_id",
        "job_title",
        "company",
        "resume_id",
        "greeting",
        "sort_order",
        "status",
        "created_at",
        "updated_at",
    },
    "apply_task": {
        "id",
        "kind",
        "status",
        "total",
        "processed",
        "succeeded",
        "failed",
        "skipped",
        "current_step",
        "stop_reason",
        "config",
        "message",
        "started_at",
        "finished_at",
        "created_at",
    },
    "apply_task_item": {
        "id",
        "task_id",
        "job_id",
        "job_title",
        "company",
        "resume_id",
        "resume_title",
        "greeting",
        "status",
        "failure_category",
        "failure_detail",
        "attempt",
        "sort_order",
        "started_at",
        "finished_at",
        "created_at",
    },
}


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _index_names(inspector, table: str) -> set[str]:
    return {item["name"] for item in inspector.get_indexes(table)}


def test_upgrade_creates_the_apply_center_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'apply-center.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)

        inspector = inspect(engine)
        assert set(APPLY_TABLES) <= set(inspector.get_table_names())
        assert _revision(engine) == HEAD_REVISION
        for table, columns in EXPECTED_COLUMNS.items():
            assert {item["name"] for item in inspector.get_columns(table)} == columns

        # 岗位匹配：job_id 唯一索引 + hard_gate 索引。
        job_id_index = next(
            item
            for item in inspector.get_indexes("job_match_analysis")
            if item["name"] == "ix_job_match_analysis_job_id"
        )
        assert job_id_index["unique"]
        assert "ix_job_match_analysis_hard_gate" in _index_names(inspector, "job_match_analysis")

        # 队列：同一岗位唯一。
        assert any(
            "job_id" in item["column_names"]
            for item in inspector.get_unique_constraints("apply_queue_item")
        )
        assert {"ix_apply_queue_item_job_id", "ix_apply_queue_item_sort_order", "ix_apply_queue_item_status"} <= _index_names(
            inspector, "apply_queue_item"
        )

        # 外键删除语义：岗位/简历 SET NULL，批次条目的 task_id CASCADE。
        job_match_fks = inspector.get_foreign_keys("job_match_analysis")
        assert any(
            item["referred_table"] == "job"
            and item["constrained_columns"] == ["job_id"]
            and item["options"].get("ondelete") == "SET NULL"
            for item in job_match_fks
        )
        item_fks = inspector.get_foreign_keys("apply_task_item")
        assert any(
            item["referred_table"] == "apply_task"
            and item["constrained_columns"] == ["task_id"]
            and item["options"].get("ondelete") == "CASCADE"
            for item in item_fks
        )
        assert any(
            item["referred_table"] == "resume_record"
            and item["constrained_columns"] == ["resume_id"]
            and item["options"].get("ondelete") == "SET NULL"
            for item in item_fks
        )
    finally:
        engine.dispose()


def test_upgrade_is_idempotent_when_tables_already_exist(tmp_path):
    """重复执行迁移不能报错。

    这里把版本退回 ``0009`` 再升一次：此时 4 张表都还在，``upgrade()`` 里的
    ``if "<table>" not in tables`` 守卫必须让它们被跳过，而不是抛"table already exists"。
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'apply-center-idempotent.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)

        inspector = inspect(engine)
        assert set(APPLY_TABLES) <= set(inspector.get_table_names())
        assert _revision(engine) == HEAD_REVISION
    finally:
        engine.dispose()


def test_downgrade_drops_only_the_apply_center_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'apply-center-downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.downgrade(config, PREVIOUS_REVISION)

        inspector = inspect(engine)
        assert not (set(APPLY_TABLES) & set(inspector.get_table_names()))
        # 既有表不受影响。
        assert {"job", "resume_record", "resume_template", "interview_session"} <= set(
            inspector.get_table_names()
        )
        assert _revision(engine) == PREVIOUS_REVISION
    finally:
        engine.dispose()


def test_upgrade_downgrade_round_trip_keeps_existing_data(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'apply-center-roundtrip.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO job (title, company, location, salary, job_type, description, "
                    "requirements, additional_info, keywords, source, source_url, posted_at, "
                    "status, note, note_images, favorite, recognition_source, created_at, "
                    "updated_at) VALUES ('后端开发', '示例科技', '', '', '社招', '', '', '', '[]', "
                    "'手动添加', '', '', '开放中', '', '[]', 0, '', '2026-09-18', '2026-09-18')"
                )
            )

        command.downgrade(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)

        inspector = inspect(engine)
        assert set(APPLY_TABLES) <= set(inspector.get_table_names())
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(1) FROM job")).scalar_one() == 1
            assert connection.execute(
                text("SELECT title FROM job WHERE company = '示例科技'")
            ).scalar_one() == "后端开发"
            # 重建后的投递表是空的（数据不可逆丢失，符合预期）。
            assert (
                connection.execute(text("SELECT count(1) FROM apply_task_item")).scalar_one() == 0
            )
    finally:
        engine.dispose()
