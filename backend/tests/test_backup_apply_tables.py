"""旧备份仍可导入的回归闸门（PRD P0-12）。

背景：备份校验要求包里**包含全部应用表**，所以每加一张表都会悄悄拒收所有旧备份——
一次加表就等于一次不兼容改动。``data_backup.inspect_archive`` 的顺序是
「按原始 revision 核对 → 迁移到 head → 校验表集合」，因此一份停在 ``0009`` 的旧备份
被迁到 head 后会自动补上本次新增的 4 张投递表，不该被拒。这里把这件事钉死。
"""
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.database import engine
from app.models.job import Job
from app.services.data_backup import (
    DATABASE_MEMBER,
    MANIFEST_MEMBER,
    BackupError,
    create_backup_archive,
    inspect_archive,
)

# 投递功能出现之前的那一版 revision，用来伪造一份"旧版本导出的备份"。
PREVIOUS_REVISION = "0009_templates_and_interview"
HEAD_REVISION = "0019_interview_history_knowledge_referral_fields"
APPLY_TABLES = ("job_match_analysis", "apply_queue_item", "apply_task", "apply_task_item")


def _database_bytes(archive_path: Path) -> bytes:
    with zipfile.ZipFile(archive_path) as archive:
        return archive.read(DATABASE_MEMBER)


def _manifest(archive_path: Path) -> dict:
    with zipfile.ZipFile(archive_path) as archive:
        return json.loads(archive.read(MANIFEST_MEMBER))


def _rebuild_archive(archive: Path, destination: Path, replacements: dict[str, bytes]) -> Path:
    """一次成型重建压缩包，避免出现重名成员。"""
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(destination, "w") as target:
        for name in source.namelist():
            target.writestr(name, replacements.get(name, source.read(name)))
    return destination


def _set_revision(database: Path, revision: str) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        connection.execute("DELETE FROM alembic_version")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))


def test_inspect_accepts_a_backup_exported_before_the_apply_tables(db_session, tmp_path):
    """旧备份必须仍然能导入：少 4 张投递表、revision 与清单一起退回 0009。"""
    db_session.add(Job(title="旧数据里的岗位", description="职责", requirements="要求"))
    db_session.commit()
    archive = create_backup_archive(engine, tmp_path / "staging")

    old_database = tmp_path / "old.db"
    old_database.write_bytes(_database_bytes(archive))
    with sqlite3.connect(old_database) as connection:
        for name in APPLY_TABLES:
            connection.execute(f"DROP TABLE {name}")
    _set_revision(old_database, PREVIOUS_REVISION)

    manifest = _manifest(archive)
    manifest["alembic_revision"] = PREVIOUS_REVISION
    for name in APPLY_TABLES:
        manifest["tables"].pop(name)
    old_archive = _rebuild_archive(
        archive,
        tmp_path / "old.zip",
        {
            DATABASE_MEMBER: old_database.read_bytes(),
            MANIFEST_MEMBER: json.dumps(manifest).encode(),
        },
    )

    preview = inspect_archive(old_archive, engine, tmp_path / "staging")

    assert preview["database"]["tables"]["job"] == 1
    # 4 张新表由迁移补齐（空的），否则表集合校验会把它判成"不是 ResumeForge 的备份"。
    for name in APPLY_TABLES:
        assert preview["database"]["tables"][name] == 0


def test_inspect_rejects_a_head_revision_backup_missing_the_apply_tables(db_session, tmp_path):
    """反向对照：清单/库都声称在 head、却缺投递表，说明包被改过，必须拒收。"""
    archive = create_backup_archive(engine, tmp_path / "staging")

    tampered_database = tmp_path / "head-but-missing.db"
    tampered_database.write_bytes(_database_bytes(archive))
    with sqlite3.connect(tampered_database) as connection:
        for name in APPLY_TABLES:
            connection.execute(f"DROP TABLE {name}")
    # 声明自己已经在 head：这样迁移不会补表，缺表就会被表集合校验抓到。
    _set_revision(tampered_database, HEAD_REVISION)

    tampered = _rebuild_archive(
        archive,
        tmp_path / "head-but-missing.zip",
        {DATABASE_MEMBER: tampered_database.read_bytes()},
    )

    with pytest.raises(BackupError, match="缺少数据表"):
        inspect_archive(tampered, engine, tmp_path / "staging")
