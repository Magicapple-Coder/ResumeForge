"""``0015_candidate_job_collect_fields`` 迁移：加列、幂等、完整 downgrade。

加列与加表的性质不同——**旧备份导入靠的是"迁移到 head 后表集合对得上"**，而加列不改表集合，
所以这里额外验两件事：表集合前后不变（"旧备份仍可导入"成立的前提），以及旧候选升级后
新列拿到的是**空串**而不是 null（界面按"没填"处理，不必到处判 None）。
"""
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config

PREVIOUS_REVISION = "0014_interview_drill"
HEAD_REVISION = "0015_candidate_job_collect_fields"

NEW_COLUMNS = {"location", "salary", "source_url", "description", "requirements", "collect_task_id"}


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _columns(engine, table: str) -> set[str]:
    return {item["name"] for item in inspect(engine).get_columns(table)}


def test_upgrade_adds_the_collect_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cand.db'}")
    try:
        command.upgrade(build_alembic_config(engine), HEAD_REVISION)
        assert _revision(engine) == HEAD_REVISION
        assert NEW_COLUMNS <= _columns(engine, "candidate_job")
    finally:
        engine.dispose()


def test_upgrade_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cand-idempotent.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, HEAD_REVISION)
        assert NEW_COLUMNS <= _columns(engine, "candidate_job")
        assert _revision(engine) == HEAD_REVISION
    finally:
        engine.dispose()


def test_head_does_not_add_or_remove_any_table(tmp_path):
    """加列不该改变表集合——这正是"旧备份仍可导入"成立的前提。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'cand-tables.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        before = set(inspect(engine).get_table_names())
        command.upgrade(config, HEAD_REVISION)
        assert set(inspect(engine).get_table_names()) == before
    finally:
        engine.dispose()


def test_existing_candidates_get_empty_defaults(tmp_path):
    """旧候选升级后新列必须是空串：界面按"没填"渲染，判 None 会到处漏判。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'cand-default.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO candidate_job (title, company, raw_text, images, note, source, "
                    "status, created_at, updated_at) VALUES ('旧候选', '某公司', '原文', '[]', '', "
                    "'手动添加', 'pending', '2026-09-18', '2026-09-18')"
                )
            )

        command.upgrade(config, HEAD_REVISION)

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT location, salary, source_url, description, requirements, "
                    "collect_task_id FROM candidate_job"
                )
            ).one()
        assert row.location == ""
        assert row.salary == ""
        assert row.source_url == ""
        assert row.description == ""
        assert row.requirements == ""
        # 批次 id 例外：迁移前的候选本来就不属于任何批次，塞 0 或 -1 都是假数据。
        assert row.collect_task_id is None
    finally:
        engine.dispose()


def test_upgrade_is_skipped_when_the_table_is_absent(tmp_path):
    """历史上存在"只有部分业务表"的库：表不在时应当**跳过**，而不是 ALTER 到不存在的表上崩掉。

    这也正是迁移链能被用在旧备份上的原因——它不能假定每张表都存在。
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'cand-missing-table.db'}")
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


def test_downgrade_removes_only_the_new_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cand-downgrade.db'}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, HEAD_REVISION)
        command.downgrade(config, PREVIOUS_REVISION)

        columns = _columns(engine, "candidate_job")
        assert not (NEW_COLUMNS & columns)
        # 原有列一个没少——降级不该顺手带走别的东西。
        assert {"title", "company", "raw_text", "note", "source", "status"} <= columns
        assert _revision(engine) == PREVIOUS_REVISION
    finally:
        engine.dispose()
