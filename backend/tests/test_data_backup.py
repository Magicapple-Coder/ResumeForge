"""备份导出与备份包校验测试。

导入/切换数据集的往返验证在 ``test_datasets.py``；这里只管"导出物是否安全"和
"坏包是否被挡住"。
"""
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
    extracted.write_bytes(_database_bytes(archive_path))
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


def test_inspect_rejects_a_payload_that_is_not_a_zip(tmp_path):
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"this is not a zip archive")

    with pytest.raises(BackupError, match="不是有效的压缩包"):
        inspect_archive(broken, engine, tmp_path / "staging")


def test_inspect_rejects_an_archive_without_a_manifest(db_session, tmp_path):
    stripped = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(stripped, "w") as archive:
        archive.writestr(DATABASE_MEMBER, b"sqlite")

    with pytest.raises(BackupError, match="缺少必要内容"):
        inspect_archive(stripped, engine, tmp_path / "staging")


def test_inspect_rejects_a_manifest_that_claims_to_include_api_keys(db_session, tmp_path):
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


def test_inspect_rejects_a_database_with_unknown_tables(db_session, tmp_path):
    archive = _export(tmp_path)
    foreign = tmp_path / "foreign.db"
    foreign.write_bytes(_database_bytes(archive))
    with sqlite3.connect(foreign) as connection:
        connection.execute("CREATE TABLE cookies (value TEXT)")

    tampered = _replace_member(archive, DATABASE_MEMBER, foreign.read_bytes(), tmp_path / "foreign.zip")

    with pytest.raises(BackupError, match="未识别的数据表"):
        inspect_archive(tampered, engine, tmp_path / "staging")


def test_inspect_rejects_a_newer_revision(db_session, tmp_path):
    archive = _export(tmp_path)
    database = tmp_path / "newer.db"
    database.write_bytes(_database_bytes(archive))
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32))")
        connection.execute("DELETE FROM alembic_version")
        connection.execute("INSERT INTO alembic_version VALUES ('9999_from_the_future')")

    tampered = _replace_member(archive, DATABASE_MEMBER, database.read_bytes(), tmp_path / "newer.zip")

    with pytest.raises(BackupError, match="更新版本"):
        inspect_archive(tampered, engine, tmp_path / "staging")


def test_export_rejects_a_memory_database(tmp_path):
    from sqlalchemy import create_engine

    memory_engine = create_engine("sqlite://")
    try:
        with pytest.raises(BackupError, match="不是本地 SQLite 文件"):
            create_backup_archive(memory_engine, tmp_path / "staging")
    finally:
        memory_engine.dispose()


def _replace_member(archive: Path, member: str, payload: bytes, destination: Path) -> Path:
    """一次成型重建压缩包，避免出现重名成员。"""
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(destination, "w") as target:
        for name in source.namelist():
            target.writestr(name, payload if name == member else source.read(name))
    return destination
