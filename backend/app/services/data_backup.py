"""用户数据备份：导出为可迁移的压缩包，以及从压缩包恢复。

ResumeForge 的用户数据都在 SQLite 文件里——照片、经历参考文件和助手图片附件都以
base64 存在数据库列中，磁盘上没有其它用户文件。所以一次备份就是「一份一致性快照 +
一份元信息」，用标准库 zipfile 即可，不需要搬运目录。

**但"一份数据"未必只有一个文件**：应用支持多份数据集，每份各占一个数据库文件，而
一次导出默认只带走**当前活动**的那一份。所以导出分两档：只导活动数据集（格式 1，
老版本照常可读）与连同其余数据集一并导出（格式 2，老版本会明确拒收而不是安静地
只恢复一份）。见 ``create_backup_archive`` 与 ``ExtraDatabase``。

导出物**不包含**大模型 API Key：用户可能长期保存或转发这个包。SECURITY: 清空
密钥必须配合 ``VACUUM`` 重建文件，只 UPDATE 是不够的——见 ``_strip_api_keys``；
随包带走的**每一份**数据集都要各做一次，不能只做活动的那份。
"""

from __future__ import annotations

import json
import logging
import secrets
import shutil
import sqlite3
import time
import zipfile
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from ..config import get_settings
from ..database_migrations import (
    _APPLICATION_TABLES,
    backup_sqlite_database,
    build_alembic_config,
    run_database_migrations,
    snapshot_sqlite_file,
)
from .settings_service import API_KEY_MASK, _LLM_CONFIG_KEY

logger = logging.getLogger(__name__)

BACKUP_FORMAT_VERSION = 2
DATABASE_MEMBER = "resume_forge.db"
MANIFEST_MEMBER = "manifest.json"
# 归档里"其余数据集"的存放前缀。
#
# 当前活动的那份**仍然叫 ``resume_forge.db``**（格式 1 的位置不变），其余数据集按
# ``datasets/<id>.db`` 另放。这样即使有人拿格式 2 的包去喂老版本，老版本也至少能按老位置
# 拿到活动数据集——不过清单里的 ``format`` 会被标成 2，老版本会**明确拒收**而不是安静地
# 只恢复一份（见 ``_read_manifest`` 的前向兼容守卫）。
ARCHIVE_DATASETS_DIRNAME = "datasets"

# 临时文件放在数据库同级目录：Windows 上跨盘 os.replace 失败，而恢复正是要做
# 一次原子替换。上传的待恢复包与导出产物分开放，避免启动清理时误删用户刚上传、
# 还没确认的包。
RESTORE_DIRNAME = "restore"
EXPORT_DIRNAME = "exports"
_STALE_TEMP_SECONDS = 1800


@dataclass(frozen=True)
class ExtraDatabase:
    """随包一起带走的**其余数据集**。

    ``data_backup`` 刻意不认识"数据集注册表"：它只管把一个数据库快照塞进包里，
    "哪些数据集要带走、它们叫什么"由 ``services/datasets`` 决定。备份格式因此与
    数据集的文件布局解耦。
    """

    dataset_id: str
    name: str
    source: Path
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def member(self) -> str:
        return f"{ARCHIVE_DATASETS_DIRNAME}/{self.dataset_id}.db"

    @property
    def metadata_member(self) -> str:
        return f"{ARCHIVE_DATASETS_DIRNAME}/{self.dataset_id}.json"

    def manifest_entry(self, size_bytes: int) -> dict[str, Any]:
        """备份清单里的一条数据集条目。"""
        return {
            "id": self.dataset_id,
            "name": self.name,
            "file": self.member,
            "metadata_file": self.metadata_member,
            "size_bytes": size_bytes,
        }


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


def build_manifest(
    bind: Engine, *, datasets: Sequence[dict[str, Any]] = ()
) -> dict[str, Any]:
    """生成包内清单。

    **格式号随"包里有没有其余数据集"变化**：只有活动数据集时仍是格式 1，老版本照常可读；
    一旦带上了其余数据集就标成 2，老版本会明确拒收。这是刻意的——老版本读不懂
    ``datasets/`` 这一段，若还按格式 1 放行，用户会以为"恢复成功"，实际上那几份数据集
    根本没被恢复，而**这类故障通常要到很久以后翻旧记录时才发现**。
    """
    settings = get_settings()
    extras = list(datasets)
    manifest: dict[str, Any] = {
        "format": BACKUP_FORMAT_VERSION if extras else 1,
        "app": settings.app_name,
        "app_version": settings.app_version,
        "alembic_revision": current_head_revision(bind),
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tables": _table_counts(bind),
        "api_key_included": False,
    }
    if extras:
        manifest["datasets"] = extras
    return manifest


def _plaintext_api_keys(bind: Engine) -> list[str]:
    """收集当前库里真实存在的明文密钥，用于导出后的残留校验。"""
    return _plaintext_api_keys_in(database_path(bind))


def _plaintext_api_keys_in(database: Path) -> list[str]:
    """从**一个数据库文件**里收集明文密钥。

    按文件而不是按 Engine 取，是因为"导出全部数据集"要为**每一份**数据集各做一次
    密钥剥离——否则随包带走的第二份数据集会把它的明文 Key 一起送出去，而这个包正是
    用户会长期保存或转发的东西。

    ``********`` 开头的是记录引用占位符而不是密钥本身，不参与校验。
    """
    found: list[str] = []
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "app_setting" in tables:
            row = connection.execute(
                "SELECT value FROM app_setting WHERE key = ?", (_LLM_CONFIG_KEY,)
            ).fetchone()
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
                for (key,) in connection.execute("SELECT api_key FROM llm_config_record")
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


def create_backup_archive(
    bind: Engine,
    staging_dir: Path,
    *,
    extra_databases: Sequence[ExtraDatabase] = (),
) -> Path:
    """生成导出用的压缩包并返回其路径；调用方负责在响应结束后删除。

    ``extra_databases`` 非空时会把那些数据集一并装进包里，并把清单的 ``format`` 标成 2。
    **格式号是要紧的**：它让老版本遇到这种包时明确拒收（"请先升级应用再导入"），而不是
    只恢复活动数据集、把其余几份安静地丢掉。
    """
    database_path(bind)  # 内存库等无文件情况在此给出明确错误
    staging_dir.mkdir(parents=True, exist_ok=True)

    snapshot = backup_sqlite_database(bind, output_dir=staging_dir)
    if snapshot is None:
        raise BackupError("无法创建数据库快照，请确认数据目录可写", status_code=500)

    archive_path = staging_dir / f"resumeforge-backup-{datetime.now():%Y%m%d-%H%M%S}.zip"
    extras: list[tuple[ExtraDatabase, Path]] = []
    try:
        # **每一份数据库各剥离一次密钥**：把不同数据集的明文 Key 收集到一起再统一校验，
        # 是为了让"包内任何位置都不该出现明文密钥"成为一条可断言的性质，而不是逐份靠自觉。
        secrets_to_find = _plaintext_api_keys_in(snapshot)
        _strip_api_keys(snapshot)
        for item in extra_databases:
            if not item.source.exists():
                raise BackupError(
                    f"数据集「{item.name}」的文件已不存在，无法一并导出；"
                    "请先在列表里把它移除或改名后重试",
                    status_code=404,
                )
            copy = staging_dir / f"{secrets.token_hex(8)}.db"
            snapshot_sqlite_file(item.source, copy)
            secrets_to_find.extend(_plaintext_api_keys_in(copy))
            _strip_api_keys(copy)
            extras.append((item, copy))
        _assert_no_plaintext_key(snapshot, secrets_to_find)
        for _, copy in extras:
            _assert_no_plaintext_key(copy, secrets_to_find)

        manifest = build_manifest(
            bind,
            datasets=[
                item.manifest_entry(copy.stat().st_size) for item, copy in extras
            ],
        )
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, DATABASE_MEMBER)
            for item, copy in extras:
                archive.write(copy, item.member)
                archive.writestr(
                    item.metadata_member,
                    json.dumps(
                        {"name": item.name, **item.metadata}, ensure_ascii=False, indent=2
                    ),
                )
            archive.writestr(MANIFEST_MEMBER, json.dumps(manifest, ensure_ascii=False, indent=2))
    except (OSError, sqlite3.Error) as exc:
        archive_path.unlink(missing_ok=True)
        raise BackupError(f"生成备份文件失败：{exc}", status_code=500) from exc
    finally:
        snapshot.unlink(missing_ok=True)
        for _, copy in extras:
            copy.unlink(missing_ok=True)
    return archive_path


def extract_database(archive_path: Path, destination: Path) -> Path:
    """把压缩包里的数据库成员写到 destination 并返回该路径。"""
    return extract_member(archive_path, DATABASE_MEMBER, destination)


def extract_member(archive_path: Path, member: str, destination: Path) -> Path:
    """把压缩包里指定的成员写到 destination 并返回该路径。

    用 ``ZipFile.open`` 逐块写出，不经过 ``extractall``，从结构上排除了 zip-slip；
    调用方仍需自行校验 ``member`` 是不是自己期望的那一个。
    """
    with zipfile.ZipFile(archive_path) as archive:
        with archive.open(member) as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target)
    return destination


def declared_datasets(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """清单里声明的"其余数据集"。格式 1 的包没有这一段，返回空列表。"""
    entries = manifest.get("datasets")
    if not isinstance(entries, list):
        return []
    return [item for item in entries if isinstance(item, dict)]


def _assert_member_is_a_dataset(entry: dict[str, Any]) -> str:
    """校验清单里那条记录指向的成员路径**确实落在 datasets/ 之下且是 .db**。

    包内的路径是可以被构造的：一个改过的备份包可以在这里写 ``../../`` 或指向主数据库
    成员，让导入过程把别的东西当成数据集写盘。因此路径只认
    ``datasets/<合法的 id>.db`` 这一种形状，别的一律拒收。
    """
    member = str(entry.get("file") or "")
    prefix = f"{ARCHIVE_DATASETS_DIRNAME}/"
    if not member.startswith(prefix) or not member.endswith(".db"):
        raise BackupError(f"备份包里有一份数据集的路径不合法（{member or '空'}），已停止导入")
    stem = member[len(prefix) : -len(".db")]
    if not stem or "/" in stem or "\\" in stem or stem.startswith("."):
        raise BackupError(f"备份包里有一份数据集的路径不合法（{member}），已停止导入")
    return member


def inspect_extra_dataset(
    archive_path: Path, entry: dict[str, Any], bind: Engine, staging_dir: Path
) -> Path:
    """解出包里的一份"其余数据集"并做与主库同样的校验，返回临时文件路径。

    校验链与活动数据集**完全一致**（先核对 revision、再迁移、最后查表结构）：随包带走的
    那几份也是用户的数据，不能因为"它是附带的"就降低标准。调用方负责把它落盘并在用完后
    删除临时文件。
    """
    member = _assert_member_is_a_dataset(entry)
    staging_dir.mkdir(parents=True, exist_ok=True)
    candidate = staging_dir / f"dataset-{secrets.token_hex(8)}.db"
    try:
        extract_member(archive_path, member, candidate)
        # 顺序不能调换：先按原始 revision 核对版本，再迁移，最后才校验表结构。
        _check_candidate_revision(candidate, bind, {"alembic_revision": None})
        _upgrade_candidate(candidate)
        _database_info(candidate, bind)
    except BaseException:
        candidate.unlink(missing_ok=True)
        raise
    return candidate


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        manifest = json.loads(archive.read(MANIFEST_MEMBER))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackupError("备份包的元信息已损坏，无法读取") from exc
    if not isinstance(manifest, dict):
        raise BackupError("备份包的元信息已损坏，无法读取")
    format_version = manifest.get("format")
    # 只拒收"比当前代码更新"的格式。这里曾是 `!=`，等于把每一次导出格式升级都变成
    # 用户历史备份的全部失效——用户升级一次应用后就再也导不回旧包了。
    if not isinstance(format_version, int) or isinstance(format_version, bool) or format_version < 1:
        raise BackupError("备份包格式不受支持，可能来自其它版本的 ResumeForge")
    if format_version > BACKUP_FORMAT_VERSION:
        raise BackupError(
            "备份来自更新版本的 ResumeForge，当前版本无法恢复；请先升级应用再导入"
        )
    # fail-closed：只有清单明确声明不含密钥才继续，避免将来格式变更后静默放行。
    if manifest.get("api_key_included") is not False:
        raise BackupError("备份包可能包含明文 API Key，为安全起见已拒绝恢复")
    return manifest


def _read_candidate_revision(database: Path) -> str | None:
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "alembic_version" not in tables:
            return None
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else None


def _check_candidate_revision(database: Path, bind: Engine, manifest: dict[str, Any]) -> None:
    """迁移**之前**核对版本：既挡住来自更新版本的备份，也挡住被改过清单的包。

    这一步必须排在 ``_upgrade_candidate`` 前面。迁移会把候选库的 revision 改写成当前
    head，之后再比就永远对不上——一份完全合法的旧备份会被判成"清单与实际内容不一致"
    而拒收，等于把新增数据表这件事重新变成一次不兼容改动。
    """
    revision = _read_candidate_revision(database)
    if revision is not None and revision not in _revision_chain(bind):
        raise BackupError(
            "备份来自更新版本的 ResumeForge，当前版本无法恢复；请先升级应用再导入"
        )
    declared = manifest.get("alembic_revision")
    if declared and revision and declared != revision:
        raise BackupError("备份包的清单与实际数据库内容不一致，已拒绝恢复")


def _upgrade_candidate(database: Path) -> None:
    """把解出来的候选库升到当前 head，再交给表结构校验。

    旧版本导出的备份不含后来新增的表，而校验要求表集合与代码一致——不先迁移的话，
    一份完全合法的旧备份会被判成"不是 ResumeForge 的备份"而拒收。切换数据集的路径
    本来就会重跑迁移，这里保持一致。

    迁移前不生成备份：候选库只是压缩包解出来的一次性副本，原始压缩包还在手上，
    而预迁移备份会落在 restore 目录里越积越多。
    """
    from ..database import build_engine, database_url_for

    engine = build_engine(database_url_for(database))
    try:
        run_database_migrations(engine, backup=False)
    finally:
        engine.dispose()


def _database_info(database: Path, bind: Engine) -> dict[str, Any]:
    """校验解出来的数据库，返回其中的 revision 与各表行数。

    版本与清单的一致性由 ``_check_candidate_revision`` 在迁移前核对过了；走到这里
    候选库已经在当前 head 上，再比一次只会是永远成立的空检查。
    """
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
        # sqlite_sequence 由 SQLite 的 AUTOINCREMENT 隐式维护，不是业务表。
        unexpected = sorted(tables - set(_APPLICATION_TABLES) - {"alembic_version", "sqlite_sequence"})
        if unexpected:
            raise BackupError(
                f"备份包中含有当前版本不认识的数据表（{unexpected[0]}），"
                "可能来自更新版本的 ResumeForge；请先升级应用再导入"
            )

        revision = None
        if "alembic_version" in tables:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = row[0] if row else None

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
        # 顺序不能调换：先按原始 revision 核对版本，再迁移，最后才校验表结构。
        _check_candidate_revision(candidate, bind, manifest)
        _upgrade_candidate(candidate)
        info = _database_info(candidate, bind)
    finally:
        candidate.unlink(missing_ok=True)

    return {
        "manifest": manifest,
        "database": info,
        "current_tables": _table_counts(bind),
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
