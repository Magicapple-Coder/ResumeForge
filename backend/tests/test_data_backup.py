"""用户数据备份的导出与恢复测试。"""
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.database import engine
from app.models.job import Job
from app.models.setting import LLMConfigRecord
from app.schemas.setting import LLMConfig
from app.services.data_backup import (
    BACKUP_FORMAT_VERSION,
    DATABASE_MEMBER,
    MANIFEST_MEMBER,
    BackupError,
    apply_archive,
    create_backup_archive,
    inspect_archive,
)
from app.services.settings_service import get_llm_config, save_llm_config

# 足够长，保证在几 MB 的文件里做子串搜索不会误命中。
SECRET = "sk-backup-canary-0123456789abcdef"


def _database_bytes(archive_path: Path) -> bytes:
    with zipfile.ZipFile(archive_path) as archive:
        return archive.read(DATABASE_MEMBER)


def _manifest(archive_path: Path) -> dict:
    with zipfile.ZipFile(archive_path) as archive:
        return json.loads(archive.read(MANIFEST_MEMBER))


def _config_api_key(archive_path: Path, tmp_path: Path) -> str:
    extracted = tmp_path / "read-config.db"
    with zipfile.ZipFile(archive_path) as archive:
        extracted.write_bytes(archive.read(DATABASE_MEMBER))
    with sqlite3.connect(extracted) as connection:
        row = connection.execute(
            "SELECT value FROM app_setting WHERE key = 'llm_config'"
        ).fetchone()
    return "" if row is None else json.loads(row[0]).get("api_key", "")


def _export(tmp_path: Path) -> Path:
    return create_backup_archive(engine, tmp_path / "staging")


def _settings_with_key(session, api_key: str = SECRET) -> None:
    save_llm_config(
        session,
        LLMConfig(base_url="https://api.example.com/v1", api_key=api_key, model="test-model"),
    )


def test_export_excludes_the_saved_api_key(db_session, tmp_path):
    _settings_with_key(db_session)
    archive = _export(tmp_path)

    assert SECRET.encode() not in _database_bytes(archive)
    # 导出的副本被清空不能影响本机正在用的配置。
    db_session.expire_all()
    assert get_llm_config(db_session).api_key == SECRET


def test_export_excludes_a_key_left_by_a_deleted_config_record(db_session, tmp_path):
    """删除配置记录后，密钥会残留在 SQLite 空闲页里；只 UPDATE 清不掉。

    这是「备份不含密钥」这条承诺的回归闸门：清空必须配合 VACUUM 重建文件。
    """
    record = LLMConfigRecord(name="临时记录", base_url="https://api.example.com/v1", api_key=SECRET)
    db_session.add(record)
    db_session.commit()
    db_session.delete(record)
    db_session.commit()

    archive = _export(tmp_path)

    assert SECRET.encode() not in _database_bytes(archive)


def test_export_blanks_a_masked_record_reference(db_session, tmp_path):
    """配置里保存的是记录引用占位符时，导出应落成空串而不是把占位符带走。"""
    record = LLMConfigRecord(name="引用", base_url="https://api.example.com/v1", api_key="")
    db_session.add(record)
    db_session.commit()
    _settings_with_key(db_session, api_key=f"********:record:{record.id}")

    archive = _export(tmp_path)

    assert _config_api_key(archive, tmp_path) == ""


def test_export_writes_a_manifest_describing_the_data(db_session, tmp_path):
    db_session.add(Job(title="后端开发", description="职责", requirements="要求"))
    db_session.commit()

    manifest = _manifest(_export(tmp_path))

    assert manifest["format"] == BACKUP_FORMAT_VERSION
    assert manifest["api_key_included"] is False
    assert manifest["tables"]["job"] == 1
    assert manifest["alembic_revision"]


def test_backup_round_trip_restores_the_exported_data(db_session, tmp_path):
    db_session.add(Job(title="导出时的岗位", description="职责", requirements="要求"))
    db_session.commit()
    archive = _export(tmp_path)

    db_session.add(Job(title="导出之后新增的岗位", description="职责", requirements="要求"))
    db_session.commit()
    assert db_session.query(Job).count() == 2

    # 恢复要替换数据库文件，必须先释放本进程持有的连接（真实应用里 apply 端点
    # 刻意不使用 get_db 就是这个原因）。
    db_session.close()
    result = apply_archive(archive, engine, tmp_path / "staging")

    with engine.connect() as connection:
        titles = {
            row[0] for row in connection.exec_driver_sql("SELECT title FROM job").fetchall()
        }
    assert titles == {"导出时的岗位"}
    assert result["previous_backup"] is not None
    assert (Path(engine.url.database).parent / "backups" / result["previous_backup"]).exists()


def test_restore_rejects_a_payload_that_is_not_a_zip(tmp_path):
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"this is not a zip archive")

    with pytest.raises(BackupError, match="不是有效的压缩包"):
        inspect_archive(broken, engine, tmp_path / "staging")


def test_restore_rejects_an_archive_without_a_manifest(db_session, tmp_path):
    stripped = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(stripped, "w") as archive:
        archive.writestr(DATABASE_MEMBER, b"sqlite")

    with pytest.raises(BackupError, match="缺少必要内容"):
        inspect_archive(stripped, engine, tmp_path / "staging")


def test_restore_rejects_a_manifest_that_claims_to_include_api_keys(db_session, tmp_path):
    archive = _export(tmp_path)
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(tampered, "w") as target:
        for name in source.namelist():
            if name == MANIFEST_MEMBER:
                manifest = json.loads(source.read(name))
                manifest["api_key_included"] = True
                target.writestr(name, json.dumps(manifest))
            else:
                target.writestr(name, source.read(name))

    with pytest.raises(BackupError, match="可能包含明文 API Key"):
        inspect_archive(tampered, engine, tmp_path / "staging")


def test_restore_rejects_a_database_with_unknown_tables(db_session, tmp_path):
    archive = _export(tmp_path)
    foreign = tmp_path / "foreign.db"
    foreign.write_bytes(_database_bytes(archive))
    with sqlite3.connect(foreign) as connection:
        connection.execute("CREATE TABLE cookies (value TEXT)")

    tampered = tmp_path / "foreign.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(tampered, "w") as target:
        for name in source.namelist():
            if name == DATABASE_MEMBER:
                target.writestr(name, foreign.read_bytes())
            else:
                target.writestr(name, source.read(name))

    with pytest.raises(BackupError, match="未识别的数据表"):
        inspect_archive(tampered, engine, tmp_path / "staging")


def test_restore_rejects_a_newer_revision(db_session, tmp_path):
    archive = _export(tmp_path)
    # 改写库里的 revision 模拟「备份来自更新版本」；一次成型重建压缩包，
    # 避免出现重名成员。
    database = tmp_path / "newer.db"
    database.write_bytes(_database_bytes(archive))
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32))")
        connection.execute("DELETE FROM alembic_version")
        connection.execute("INSERT INTO alembic_version VALUES ('9999_from_the_future')")

    newer = tmp_path / "newer.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(newer, "w") as target:
        for name in source.namelist():
            if name == DATABASE_MEMBER:
                target.writestr(name, database.read_bytes())
            else:
                target.writestr(name, source.read(name))

    with pytest.raises(BackupError, match="更新版本"):
        inspect_archive(newer, engine, tmp_path / "staging")


def test_restore_rolls_back_when_the_migration_fails(db_session, tmp_path, monkeypatch):
    db_session.add(Job(title="恢复前的岗位", description="职责", requirements="要求"))
    db_session.commit()
    archive = tmp_path / "old.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr(MANIFEST_MEMBER, json.dumps({
            "format": BACKUP_FORMAT_VERSION,
            "app": "ResumeForge",
            "app_version": "0.2.0",
            "alembic_revision": None,
            "exported_at": "2026-01-01T00:00:00+08:00",
            "tables": {},
            "api_key_included": False,
        }))
        target.writestr(DATABASE_MEMBER, Path(engine.url.database).read_bytes())

    def fail_migration(_bind):
        raise RuntimeError("迁移失败")

    monkeypatch.setattr("app.services.data_backup.run_database_migrations", fail_migration)
    db_session.close()

    with pytest.raises(BackupError, match="已回滚"):
        apply_archive(archive, engine, tmp_path / "staging")

    # 回滚后用户数据仍在，不会停在半升级状态。
    with engine.connect() as connection:
        count = connection.exec_driver_sql("SELECT COUNT(*) FROM job").scalar_one()
    assert count == 1


def test_backup_rejects_a_memory_database(tmp_path):
    from sqlalchemy import create_engine

    memory_engine = create_engine("sqlite://")
    try:
        with pytest.raises(BackupError, match="不是本地 SQLite 文件"):
            create_backup_archive(memory_engine, tmp_path / "staging")
    finally:
        memory_engine.dispose()
