"""用户数据备份：导出为可迁移的压缩包，以及从压缩包恢复。

ResumeForge 的全部用户数据都在这一个 SQLite 文件里——照片、经历参考文件和助手
图片附件都以 base64 存在数据库列中，磁盘上没有其它用户文件。所以一次备份就是
「一份一致性快照 + 一份元信息」，用标准库 zipfile 即可，不需要搬运目录。

导出物**不包含**大模型 API Key：用户可能长期保存或转发这个包。SECURITY: 清空
密钥必须配合 ``VACUUM`` 重建文件，只 UPDATE 是不够的——见 ``_strip_api_keys``。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import sqlite3
import time
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from ..config import get_settings
from ..database_migrations import (
    _APPLICATION_TABLES,
    backup_sqlite_database,
    build_alembic_config,
    run_database_migrations,
)
from .settings_service import API_KEY_MASK, _LLM_CONFIG_KEY

logger = logging.getLogger(__name__)

BACKUP_FORMAT_VERSION = 1
DATABASE_MEMBER = "resume_forge.db"
MANIFEST_MEMBER = "manifest.json"

# 临时文件放在数据库同级目录：Windows 上跨盘 os.replace 失败，而恢复正是要做
# 一次原子替换。上传的待恢复包与导出产物分开放，避免启动清理时误删用户刚上传、
# 还没确认的包。
RESTORE_DIRNAME = "restore"
EXPORT_DIRNAME = "exports"
_STALE_TEMP_SECONDS = 1800


class BackupError(Exception):
    """对外暴露的备份错误，message 为可直接展示给用户的中文提示。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def database_path(bind: Engine) -> Path:
    """返回 SQLite 文件路径；内存库等无文件的情况抛出 BackupError。"""
    database = bind.url.database
    if bind.dialect.name != "sqlite" or not database or database == ":memory:":
        raise BackupError("当前数据库不是本地 SQLite 文件，无法备份或恢复", status_code=409)
    return Path(database).resolve()


def restore_directory(bind: Engine) -> Path:
    return database_path(bind).parent / RESTORE_DIRNAME


def export_directory(bind: Engine) -> Path:
    return database_path(bind).parent / EXPORT_DIRNAME


def current_head_revision(bind: Engine) -> str | None:
    return ScriptDirectory.from_config(build_alembic_config(bind)).get_current_head()


def _revision_chain(bind: Engine) -> list[str]:
    """从当前 head 到最初版本的 revision 列表（本项目是线性链路）。"""
    scripts = ScriptDirectory.from_config(build_alembic_config(bind))
    head = scripts.get_current_head()
    if head is None:
        return []
    return [revision.revision for revision in scripts.iterate_revisions(head, "base")]


def _table_counts(bind: Engine) -> dict[str, int]:
    quote = bind.dialect.identifier_preparer.quote
    with bind.connect() as connection:
        return {
            name: connection.execute(text(f"SELECT COUNT(*) FROM {quote(name)}")).scalar_one()
            for name in _APPLICATION_TABLES
        }


def build_manifest(bind: Engine) -> dict[str, Any]:
    settings = get_settings()
    return {
        "format": BACKUP_FORMAT_VERSION,
        "app": settings.app_name,
        "app_version": settings.app_version,
        "alembic_revision": current_head_revision(bind),
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tables": _table_counts(bind),
        "api_key_included": False,
    }


def _plaintext_api_keys(bind: Engine) -> list[str]:
    """收集当前库里真实存在的明文密钥，用于导出后的残留校验。

    ``********`` 开头的是记录引用占位符而不是密钥本身，不参与校验。
    """
    found: list[str] = []
    tables = set(inspect(bind).get_table_names())
    with bind.connect() as connection:
        if "app_setting" in tables:
            row = connection.execute(
                text("SELECT value FROM app_setting WHERE key = :key"), {"key": _LLM_CONFIG_KEY}
            ).first()
            if row and row[0]:
                try:
                    value = json.loads(row[0]).get("api_key", "")
                except (json.JSONDecodeError, AttributeError):
                    value = ""
                if value and not value.startswith(API_KEY_MASK):
                    found.append(value)
        if "llm_config_record" in tables:
            found.extend(
                key
                for (key,) in connection.execute(text("SELECT api_key FROM llm_config_record"))
                if key and not key.startswith(API_KEY_MASK)
            )
    # 太短的值会在几 MB 的文件里随机命中，只校验长度像密钥的内容。
    return [item for item in found if len(item) >= 8]


def _strip_api_keys(database: Path) -> None:
    """把备份副本里的模型密钥置空，并抹掉已释放页面中的残留。

    ``UPDATE`` 只改活着的行：用户删除过的配置记录、或历史版本被覆盖的取值，都会
    把明文密钥留在 SQLite 的空闲页里，而 ``sqlite3.Connection.backup()`` 是逐页
    复制的，会把这些页一起带进备份。所以先开 ``secure_delete`` 让删除操作就地清零，
    再用 ``VACUUM`` 按存活数据重建整个文件。只做其一都清不干净。
    """
    with closing(sqlite3.connect(database, timeout=30)) as connection:
        connection.execute("PRAGMA secure_delete = ON")
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "llm_config_record" in tables:
            connection.execute("UPDATE llm_config_record SET api_key = ''")
        if "app_setting" in tables:
            row = connection.execute(
                "SELECT value FROM app_setting WHERE key = ?", (_LLM_CONFIG_KEY,)
            ).fetchone()
            if row is not None:
                try:
                    config = json.loads(row[0])
                except (TypeError, json.JSONDecodeError):
                    config = None
                if isinstance(config, dict):
                    config["api_key"] = ""
                    connection.execute(
                        "UPDATE app_setting SET value = ? WHERE key = ?",
                        (json.dumps(config, ensure_ascii=False), _LLM_CONFIG_KEY),
                    )
                else:
                    # 配置本身已损坏时读取端本来就会退回默认值，直接删掉等价。
                    connection.execute("DELETE FROM app_setting WHERE key = ?", (_LLM_CONFIG_KEY,))
        connection.commit()
        # VACUUM 必须独立于事务之外执行。
        connection.execute("VACUUM")


def _assert_no_plaintext_key(database: Path, secrets_to_find: list[str]) -> None:
    """导出前的最后一道闸：确认快照里再也找不到任何明文密钥。"""
    if not secrets_to_find:
        return
    content = database.read_bytes()
    if any(secret.encode("utf-8") in content for secret in secrets_to_find):
        raise BackupError(
            "导出已取消：备份中仍能匹配到明文 API Key，请联系维护者",
            status_code=500,
        )


def create_backup_archive(bind: Engine, staging_dir: Path) -> Path:
    """生成导出用的压缩包并返回其路径；调用方负责在响应结束后删除。"""
    database_path(bind)  # 内存库等无文件情况在此给出明确错误
    staging_dir.mkdir(parents=True, exist_ok=True)
    secrets_to_find = _plaintext_api_keys(bind)

    snapshot = backup_sqlite_database(bind, output_dir=staging_dir)
    if snapshot is None:
        raise BackupError("无法创建数据库快照，请确认数据目录可写", status_code=500)

    archive_path = staging_dir / f"resumeforge-backup-{datetime.now():%Y%m%d-%H%M%S}.zip"
    try:
        _strip_api_keys(snapshot)
        _assert_no_plaintext_key(snapshot, secrets_to_find)
        manifest = build_manifest(bind)
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, DATABASE_MEMBER)
            archive.writestr(MANIFEST_MEMBER, json.dumps(manifest, ensure_ascii=False, indent=2))
    except (OSError, sqlite3.Error) as exc:
        archive_path.unlink(missing_ok=True)
        raise BackupError(f"生成备份文件失败：{exc}", status_code=500) from exc
    finally:
        snapshot.unlink(missing_ok=True)
    return archive_path


def extract_database(archive_path: Path, destination: Path) -> Path:
    """把压缩包里的数据库成员写到 destination 并返回该路径。

    用 ``ZipFile.open`` 逐块写出，不经过 ``extractall``，从结构上排除了 zip-slip。
    """
    with zipfile.ZipFile(archive_path) as archive:
        with archive.open(DATABASE_MEMBER) as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target)
    return destination


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        manifest = json.loads(archive.read(MANIFEST_MEMBER))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackupError("备份包的元信息已损坏，无法读取") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != BACKUP_FORMAT_VERSION:
        raise BackupError("备份包格式不受支持，可能来自其它版本的 ResumeForge")
    # fail-closed：只有清单明确声明不含密钥才继续，避免将来格式变更后静默放行。
    if manifest.get("api_key_included") is not False:
        raise BackupError("备份包可能包含明文 API Key，为安全起见已拒绝恢复")
    return manifest


def _database_info(database: Path, bind: Engine, manifest: dict[str, Any]) -> dict[str, Any]:
    """校验解出来的数据库，返回其中的 revision 与各表行数。"""
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("备份包中的数据库未通过完整性校验")
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        except sqlite3.DatabaseError as exc:
            raise BackupError("备份包中的数据库已损坏") from exc

        missing = [name for name in _APPLICATION_TABLES if name not in tables]
        if missing:
            raise BackupError(
                f"备份包中的数据库缺少数据表（{missing[0]} 等），可能不是 ResumeForge 的备份"
            )
        unexpected = sorted(tables - set(_APPLICATION_TABLES) - {"alembic_version"})
        if unexpected:
            raise BackupError(f"备份包中含有未识别的数据表（{unexpected[0]}），已拒绝恢复")

        revision = None
        if "alembic_version" in tables:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = row[0] if row else None

        if revision is not None and revision not in _revision_chain(bind):
            raise BackupError(
                "备份来自更新版本的 ResumeForge，当前版本无法恢复；请先升级应用再导入"
            )
        declared = manifest.get("alembic_revision")
        if declared and revision and declared != revision:
            raise BackupError("备份包的清单与实际数据库内容不一致，已拒绝恢复")

        counts = {
            name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in _APPLICATION_TABLES
        }
    return {"alembic_revision": revision, "tables": counts}


def inspect_archive(archive_path: Path, bind: Engine, staging_dir: Path) -> dict[str, Any]:
    """只读校验备份包并返回预览信息，不触碰当前数据库。"""
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise BackupError("备份文件不是有效的压缩包") from exc

    with archive:
        names = set(archive.namelist())
        if DATABASE_MEMBER not in names or MANIFEST_MEMBER not in names:
            raise BackupError("备份包缺少必要内容，可能不是 ResumeForge 的备份")
        manifest = _read_manifest(archive)

    staging_dir.mkdir(parents=True, exist_ok=True)
    candidate = staging_dir / f"inspect-{secrets.token_hex(8)}.db"
    try:
        extract_database(archive_path, candidate)
        info = _database_info(candidate, bind, manifest)
    finally:
        candidate.unlink(missing_ok=True)

    return {
        "manifest": manifest,
        "database": info,
        "current_tables": _table_counts(bind),
    }


def _replace_database(bind: Engine, source: Path, target: Path) -> None:
    """释放连接池后用 source 原子替换 target。

    ``dispose()`` 会换上一个新的空连接池，引擎对象继续可用；被本进程持有的连接
    会锁住数据库文件，所以替换前必须先释放。
    """
    bind.dispose()
    os.replace(source, target)


def apply_archive(archive_path: Path, bind: Engine, staging_dir: Path) -> dict[str, Any]:
    """用备份包替换当前数据库。

    替换前先给当前库做一次备份（用户可据此回滚）。若恢复后的库升级失败，会把
    数据库换回恢复前的内容，而不是把用户留在半升级状态。
    """
    preview = inspect_archive(archive_path, bind, staging_dir)
    target = database_path(bind)

    staging_dir.mkdir(parents=True, exist_ok=True)
    candidate = staging_dir / f"restore-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    extract_database(archive_path, candidate)

    previous = backup_sqlite_database(bind)
    try:
        _replace_database(bind, candidate, target)
    except OSError as exc:
        candidate.unlink(missing_ok=True)
        raise BackupError(
            f"数据库文件正被占用，请关闭其它页面或正在进行的 AI 请求后重试：{exc}",
            status_code=409,
        ) from exc

    try:
        upgraded = run_database_migrations(bind)
    except Exception as exc:
        logger.exception("恢复后的数据库升级失败，正在回滚到恢复前的数据")
        if previous is not None and previous.exists():
            rollback = target.parent / f"{target.name}.rollback"
            shutil.copyfile(previous, rollback)
            try:
                _replace_database(bind, rollback, target)
            except OSError:  # pragma: no cover - 回滚也失败时保留原样并上报
                logger.exception("回滚失败，数据库停留在恢复后的状态")
        raise BackupError("备份中的数据库无法升级，已回滚到恢复前的数据", status_code=500) from exc

    logger.info("已从备份恢复数据库 path=%s 回滚备份=%s", target, previous or "无")
    return {
        "manifest": preview["manifest"],
        "tables": preview["database"]["tables"],
        "previous_backup": previous.name if previous else None,
        "upgraded_backup": upgraded.name if upgraded else None,
    }


def _purge_stale(directory: Path) -> None:
    """删除上一轮遗留的临时文件；仍在使用的包按修改时间保留。"""
    if not directory.exists():
        return
    deadline = time.time() - _STALE_TEMP_SECONDS
    for item in directory.iterdir():
        if item.is_file() and item.stat().st_mtime < deadline:
            item.unlink(missing_ok=True)


def purge_stale_restores(bind: Engine) -> None:
    _purge_stale(restore_directory(bind))


def cleanup_temp_directories(bind: Engine) -> None:
    """启动时清空临时目录：上一轮未应用的备份包与导出产物都不会再用到。"""
    for directory in (restore_directory(bind), export_directory(bind)):
        if not directory.exists():
            continue
        for item in directory.iterdir():
            if item.is_file():
                item.unlink(missing_ok=True)
