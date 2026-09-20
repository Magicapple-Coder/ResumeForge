"""对抗性测试：在**真实生产库的副本**上验证 0010 迁移与旧备份兼容。

把 ``backend/data/resume_forge.db`` **复制到临时目录**再操作，绝不碰用户真实数据。

注意：生产库的 revision 会随用户使用前进——装上投递台之后，用户一启动应用就会被自动升到
``0010``。因此 fixture **不假设它停在哪个版本**，而是把副本统一下降到升级前形态再交给用例；
否则这些用例只会在"恰好还没启动过应用"时通过，而它们本想验证的"在真实旧库上做迁移"其实
一次都没验到。

覆盖：
- upgrade → downgrade → upgrade 往返：表结构、索引、唯一约束、外键 ``ondelete`` 是否正确；
- downgrade 只删这 4 张表，不伤既有表，既有数据仍在；
- 重复 upgrade 幂等；
- 真实生产库形态的旧备份（0009、缺 4 张表）能被 ``inspect_archive`` 接受且补齐；
- 反向：声称在 head 却缺表的数据包被正确拒收。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.database_migrations import build_alembic_config
from app.services.data_backup import (
    DATABASE_MEMBER,
    MANIFEST_MEMBER,
    BackupError,
    build_manifest,
    inspect_archive,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
REAL_DATABASE = BACKEND_DIR / "data" / "resume_forge.db"

APPLY_TABLES = (
    "job_match_analysis",
    "apply_queue_item",
    "apply_task",
    "apply_task_item",
)
PREVIOUS_REVISION = "0009_templates_and_interview"
# 本文件的主角：只加表、不动既有列的那个迁移。
APPLY_MIGRATION_REVISION = "0010_apply_center"
# 当前迁移链的 head，用于"升级到底"与"声称在 head"的对照。
HEAD_REVISION = "0021_candidate_additional_info"

EXPECTED_INDEXES = {
    "job_match_analysis": {
        "ix_job_match_analysis_job_id",
        "ix_job_match_analysis_hard_gate",
    },
    "apply_queue_item": {
        "ix_apply_queue_item_job_id",
        "ix_apply_queue_item_sort_order",
        "ix_apply_queue_item_status",
    },
    "apply_task": {"ix_apply_task_kind", "ix_apply_task_status"},
    "apply_task_item": {
        "ix_apply_task_item_task_id",
        "ix_apply_task_item_job_id",
        "ix_apply_task_item_status",
    },
}


@pytest.fixture
def real_db_copy(tmp_path) -> Path:
    """真实生产库的副本，先退回升级前形态再交给用例。

    用户一启动应用，生产库就会被升到 ``0010``，所以这里不能假设它停在 ``0009``；那样
    只能保证"恰好还没启动过应用"时是绿的，而用例真正想验证的迁移路径根本没被走到。
    """
    if not REAL_DATABASE.exists():
        pytest.skip("真实生产库不存在，跳过基于生产库副本的迁移验证")
    destination = tmp_path / "resume_forge_copy.db"
    shutil.copy2(REAL_DATABASE, destination)

    engine = create_engine(f"sqlite:///{destination}")
    try:
        config = build_alembic_config(engine)
        current = _revision(engine)
        if current != PREVIOUS_REVISION:
            # 只有当目标 revision 确实位于当前版本的祖先链上时才降级；否则说明这个库
            # 比本次覆盖的迁移区间还旧，跳过比给出误报更诚实。
            chain = {
                revision.revision
                for revision in ScriptDirectory.from_config(config).iterate_revisions(
                    current, "base"
                )
            }
            if PREVIOUS_REVISION not in chain:
                pytest.skip(
                    f"生产库 revision={current} 不在 {PREVIOUS_REVISION} 之后，跳过本次迁移验证"
                )
            command.downgrade(config, PREVIOUS_REVISION)
        assert _revision(engine) == PREVIOUS_REVISION
    finally:
        engine.dispose()
    return destination


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _table_names(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _column_sets(engine, tables) -> dict[str, set[str]]:
    inspector = inspect(engine)
    return {name: {col["name"] for col in inspector.get_columns(name)} for name in tables}


def test_real_production_copy_starts_at_0009_without_apply_tables(real_db_copy):
    engine = create_engine(f"sqlite:///{real_db_copy}")
    try:
        assert _revision(engine) == PREVIOUS_REVISION
        assert not (set(APPLY_TABLES) & _table_names(engine))
    finally:
        engine.dispose()


def test_round_trip_on_a_copy_of_the_real_database_preserves_existing_data(real_db_copy):
    engine = create_engine(f"sqlite:///{real_db_copy}")
    config = build_alembic_config(engine)
    # 这条用例验证的是 **0010 这一个迁移**的性质（只加表、不动既有列），所以升到 0010
    # 而不是 "head"：后面 0013 会给 resume_record 加列，用 "head" 会让这条断言因为一个
    # 与本迁移无关的原因变红，而它想守住的"只加表"其实一直没被验到。
    try:
        baseline_tables = _table_names(engine)
        baseline_columns = _column_sets(engine, baseline_tables)

        command.upgrade(config, APPLY_MIGRATION_REVISION)
        assert _revision(engine) == APPLY_MIGRATION_REVISION
        assert set(APPLY_TABLES) <= _table_names(engine)
        # 既有表的列一个都没动。
        assert _column_sets(engine, baseline_tables) == baseline_columns

        # 索引 / 唯一约束 / 外键语义逐项核对。
        inspector = inspect(engine)
        for table, indexes in EXPECTED_INDEXES.items():
            assert indexes <= {item["name"] for item in inspector.get_indexes(table)}
        assert any(
            item["unique"] for item in inspector.get_indexes("job_match_analysis")
            if item["name"] == "ix_job_match_analysis_job_id"
        )
        assert any(
            "job_id" in item["column_names"]
            for item in inspector.get_unique_constraints("apply_queue_item")
        )
        assert any(
            item["referred_table"] == "apply_task"
            and item["constrained_columns"] == ["task_id"]
            and item["options"].get("ondelete") == "CASCADE"
            for item in inspector.get_foreign_keys("apply_task_item")
        )
        assert any(
            item["referred_table"] == "job"
            and item["options"].get("ondelete") == "SET NULL"
            for item in inspector.get_foreign_keys("apply_queue_item")
        )

        # 写一条标记岗位，验证降级/升往返不丢既有数据。
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO job (title, company, location, salary, job_type, description, "
                    "requirements, additional_info, keywords, source, source_url, posted_at, "
                    "status, note, note_images, favorite, recognition_source, created_at, "
                    "updated_at) VALUES ('QA标记岗位', 'QA公司', '', '', '社招', '', '', '', '[]', "
                    "'手动添加', '', '', '开放中', '', '[]', 0, '', '2026-09-18', '2026-09-18')"
                )
            )

        command.downgrade(config, PREVIOUS_REVISION)
        assert _revision(engine) == PREVIOUS_REVISION
        # 只删了这 4 张表，其余表集合与最初一模一样。
        assert _table_names(engine) == baseline_tables
        assert _column_sets(engine, baseline_tables) == baseline_columns

        command.upgrade(config, "head")
        assert _revision(engine) == HEAD_REVISION
        assert set(APPLY_TABLES) <= _table_names(engine)
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(1) FROM job WHERE company = 'QA公司'")
                ).scalar_one()
                == 1
            )
    finally:
        engine.dispose()


def test_repeated_upgrade_is_idempotent_on_the_real_copy(real_db_copy):
    engine = create_engine(f"sqlite:///{real_db_copy}")
    config = build_alembic_config(engine)
    try:
        command.upgrade(config, "head")
        # 把版本退回 0009 但保留 4 张表，再升一次：迁移必须跳过已存在的表而不报错。
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, "head")
        assert _revision(engine) == HEAD_REVISION
        assert set(APPLY_TABLES) <= _table_names(engine)
    finally:
        engine.dispose()


def test_head_schema_matches_a_freshly_migrated_database(real_db_copy, tmp_path):
    """生产库副本升到 head 后的 4 张新表结构，应与全新库完全一致（防漂移）。"""
    migrated = create_engine(f"sqlite:///{real_db_copy}")
    fresh = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    try:
        command.upgrade(build_alembic_config(migrated), "head")
        command.upgrade(build_alembic_config(fresh), "head")
        assert _column_sets(migrated, APPLY_TABLES) == _column_sets(fresh, APPLY_TABLES)
        for table in APPLY_TABLES:
            assert {
                item["name"] for item in inspect(migrated).get_indexes(table)
            } == {item["name"] for item in inspect(fresh).get_indexes(table)}
    finally:
        migrated.dispose()
        fresh.dispose()


# ===== 旧备份兼容：真实生产库形态 =====


def _build_old_backup_archive(database: Path, head_engine, destination: Path) -> Path:
    """用给定的 0009 数据库构造一份"旧版本导出的备份"。"""
    manifest = build_manifest(head_engine)
    manifest["alembic_revision"] = PREVIOUS_REVISION
    for name in APPLY_TABLES:
        manifest["tables"].pop(name, None)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(database, DATABASE_MEMBER)
        archive.writestr(MANIFEST_MEMBER, json.dumps(manifest, ensure_ascii=False, indent=2))
    return destination


def test_real_production_shape_backup_is_accepted_and_backfilled(real_db_copy, tmp_path):
    head_engine = create_engine(f"sqlite:///{tmp_path / 'head.db'}")
    command.upgrade(build_alembic_config(head_engine), "head")
    try:
        archive = _build_old_backup_archive(real_db_copy, head_engine, tmp_path / "old.zip")
        preview = inspect_archive(archive, head_engine, tmp_path / "staging")

        # 旧库被迁到 head，4 张新表被补齐（空表），因此不会被"缺少数据表"拒收。
        assert preview["database"]["alembic_revision"] == HEAD_REVISION
        for name in APPLY_TABLES:
            assert preview["database"]["tables"][name] == 0
    finally:
        head_engine.dispose()


def test_head_declared_backup_missing_apply_tables_is_rejected(real_db_copy, tmp_path):
    """反向对照：库声称在 head、却真的缺表，必须被拒收，否则这道校验形同虚设。"""
    head_engine = create_engine(f"sqlite:///{tmp_path / 'head2.db'}")
    command.upgrade(build_alembic_config(head_engine), "head")
    try:
        tampered = tmp_path / "tampered.db"
        shutil.copy2(real_db_copy, tampered)
        with sqlite3.connect(tampered) as connection:
            connection.execute("DELETE FROM alembic_version")
            connection.execute(
                "INSERT INTO alembic_version VALUES (?)", (HEAD_REVISION,)
            )
        with zipfile.ZipFile(tmp_path / "tampered.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(tampered, DATABASE_MEMBER)
            archive.writestr(MANIFEST_MEMBER, json.dumps(build_manifest(head_engine)))
        with pytest.raises(BackupError, match="缺少数据表"):
            inspect_archive(tmp_path / "tampered.zip", head_engine, tmp_path / "staging2")
    finally:
        head_engine.dispose()
