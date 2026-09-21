"""数据集管理：把多份完整数据库作为可切换的数据集来维护。

每份数据集就是一个 SQLite 文件，并且它们是**真实的活动文件**（不是副本）——切换
只是把引擎指过去，不搬运数据，因此也不存在"忘记把改动写回去"的隐患。

指针与目录始终相对 **DATABASE_URL 所在的目录**（见 :mod:`app.dataset_registry`），
所以切换只影响"连哪个文件"，不会让数据集列表本身跟着漂移。
"""

from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from .. import database
from ..database import Base, ensure_sqlite_columns
from ..database_compat import SQLITE_REQUIRED_COLUMNS
from ..database_migrations import is_unversioned_legacy_database, run_database_migrations
from ..dataset_registry import (
    MAIN_DATASET_ID,
    MAIN_DATASET_NAME,
    DatasetError,
    dataset_database_file,
    dataset_metadata_file,
    datasets_directory,
    is_valid_dataset_id,
    new_dataset_id,
    read_active_dataset_id,
    read_metadata,
    trash_directory,
    write_active_dataset_id,
    write_metadata,
)
from .data_backup import (
    ExtraDatabase,
    cleanup_temp_directories,
    create_backup_archive,
    declared_datasets,
    extract_database,
    inspect_archive,
    inspect_extra_dataset,
)

logger = logging.getLogger(__name__)

# 切换前最多等这么久，等正在进行的请求把手里的连接还回池子。
_DRAIN_TIMEOUT_SECONDS = 3.0


def _describe(dataset_id: str, path: Path) -> dict[str, Any]:
    metadata = read_metadata(dataset_id) if dataset_id != MAIN_DATASET_ID else {}
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {
        "id": dataset_id,
        "name": metadata.get("name") or (MAIN_DATASET_NAME if dataset_id == MAIN_DATASET_ID else "未命名数据集"),
        "source": metadata.get("source") or ("本机" if dataset_id == MAIN_DATASET_ID else "导入"),
        "size_bytes": size,
        "created_at": metadata.get("created_at"),
        "is_active": dataset_id == read_active_dataset_id(),
        "exists": path.exists(),
    }


def list_datasets() -> list[dict[str, Any]]:
    """主数据 + datasets 目录下的各份数据集；当前激活的排在最前。"""
    items = [_describe(MAIN_DATASET_ID, dataset_database_file(MAIN_DATASET_ID))]
    directory = datasets_directory()
    if directory.exists():
        for path in sorted(directory.glob("*.db")):
            if is_valid_dataset_id(path.stem):
                items.append(_describe(path.stem, path))
    items.sort(key=lambda item: (not item["is_active"], item["name"]))
    return items


def import_dataset(archive_path: Path, name: str, bind: Engine, staging_dir: Path) -> dict[str, Any]:
    """把上传的备份包校验后落成一份**新数据集**，不触碰当前正在使用的数据。

    **先把整包里所有东西都验完，再开始写盘。** 一份包可能带好几份数据集，若边写边验，
    后面某份不合法时前面几份已经落盘了——用户看到的是一次失败，列表里却多出几份半截的
    数据集，还得自己分辨哪几份能用。校验全部前置之后，这条路径才是"要么全成、要么不动"。
    """
    preview = inspect_archive(archive_path, bind, staging_dir)
    manifest = preview.get("manifest", {})

    staged: list[tuple[dict[str, Any], Path]] = []
    try:
        # 阶段一：只校验，不落盘。
        for entry in declared_datasets(manifest):
            staged.append((entry, inspect_extra_dataset(archive_path, entry, bind, staging_dir)))

        # 阶段二：全部通过之后才开始写。
        dataset_id = new_dataset_id()
        target = dataset_database_file(dataset_id)
        target.parent.mkdir(parents=True, exist_ok=True)

        # 先写临时文件再原子改名：中途失败不会留下一个半截的数据集被列表看到。
        partial = target.with_suffix(".partial")
        try:
            extract_database(archive_path, partial)
            partial.replace(target)
        except OSError as exc:
            partial.unlink(missing_ok=True)
            raise DatasetError(f"写入数据集失败：{exc}", status_code=500) from exc

        write_metadata(
            dataset_id,
            {
                "name": name.strip() or f"导入于 {datetime.now():%Y-%m-%d %H:%M}",
                "source": "导入",
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "manifest": manifest,
            },
        )
        logger.info("已导入新数据集 id=%s name=%s", dataset_id, name)

        result = _describe(dataset_id, target)
        restored = _place_packaged_datasets(staged)
        if restored:
            # 随包带走的其余数据集各落成一份新数据集。**用新 id**：包里的 id 在本机可能早就
            # 存在（那是另一份数据），沿用会覆盖它——而覆盖用户的另一份数据集是不可逆的。
            result["restored_datasets"] = restored
        return result
    finally:
        for _, candidate in staged:
            candidate.unlink(missing_ok=True)


def _place_packaged_datasets(staged: list[tuple[dict[str, Any], Path]]) -> list[dict[str, Any]]:
    """把已经校验过的其余数据集逐个落盘（校验在 ``import_dataset`` 里已经做完了）。"""
    restored: list[dict[str, Any]] = []
    for entry, candidate in staged:
        dataset_id = new_dataset_id()
        target = dataset_database_file(dataset_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".partial")
        try:
            # 同盘内改名是原子的：中途失败不会在列表里留下半截的数据集。
            candidate.replace(partial)
            partial.replace(target)
        except OSError as exc:
            partial.unlink(missing_ok=True)
            raise DatasetError(f"写入数据集失败：{exc}", status_code=500) from exc
        write_metadata(
            dataset_id,
            {
                # 名字沿用包里的：用户就是靠它在列表里认出这是哪一份。
                "name": str(entry.get("name") or "导入的数据集"),
                "source": "随备份包导入",
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
        )
        restored.append(_describe(dataset_id, target))
        logger.info("随包恢复了数据集 id=%s name=%s", dataset_id, entry.get("name"))
    return restored


def create_dataset(name: str, bind: Engine) -> dict[str, Any]:
    """新建一份**空数据集**：全新 SQLite 文件 + 迁移到当前 head + 写元信息。

    空库直接跑迁移（``0001`` → head），不必先 ``create_all``：create_all + stamp + upgrade
    会把 ``0002`` 起的加索引/加列动作在已经建好的表上重复执行一遍而失败。
    """
    cleaned = name.strip()
    if not cleaned:
        raise DatasetError("名称不能为空")
    if len(cleaned) > 64:
        raise DatasetError("名称过长（最多 64 个字符）")

    dataset_id = new_dataset_id()
    target = dataset_database_file(dataset_id)
    target.parent.mkdir(parents=True, exist_ok=True)

    new_engine = database.build_engine(database.database_url_for(target))
    try:
        run_database_migrations(new_engine)
    finally:
        new_engine.dispose()

    write_metadata(
        dataset_id,
        {
            "name": cleaned,
            "source": "新建",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )
    logger.info("已新建空数据集 id=%s name=%s", dataset_id, cleaned)
    return _describe(dataset_id, target)


def _wait_for_idle(bind: Engine) -> None:
    """等正在进行的请求把手里的连接还回池子。

    切换会换掉引擎：若此刻有请求（尤其是助手的 SSE 流）仍持有旧库连接，它后续打开的
    会话会落到**新**数据集上，等于把这次的数据写进了别处。宁可让用户重试一次。
    """
    deadline = time.monotonic() + _DRAIN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not getattr(bind.pool, "checkedout", lambda: 0)():
            return
        time.sleep(0.1)
    raise DatasetError("有正在进行的请求（例如 AI 生成中），请稍候再切换数据集", status_code=409)


def activate_dataset(dataset_id: str, bind: Engine) -> dict[str, Any]:
    """把应用切换到指定数据集。"""
    if dataset_id != MAIN_DATASET_ID and not is_valid_dataset_id(dataset_id):
        raise DatasetError("数据集标识无效")
    target = dataset_database_file(dataset_id)
    if not target.exists():
        raise DatasetError("数据集文件已不存在，请刷新列表后重试", status_code=404)

    _wait_for_idle(bind)
    write_active_dataset_id(dataset_id)
    new_engine = database.rebind(target)
    # 数据集可能来自更早的版本：建表/补列/迁移要在这里补跑，否则旧表缺列会直接 500。
    if is_unversioned_legacy_database(new_engine):
        Base.metadata.create_all(bind=new_engine)
        ensure_sqlite_columns(new_engine, SQLITE_REQUIRED_COLUMNS)
    run_database_migrations(new_engine)
    cleanup_temp_directories(new_engine)

    logger.info("已切换到数据集 id=%s path=%s", dataset_id, target.name)
    return _describe(dataset_id, target)


def rename_dataset(dataset_id: str, name: str) -> dict[str, Any]:
    """重命名数据集（写元信息；主数据不支持重命名，缺失/空名/过长均报错）。"""
    if dataset_id == MAIN_DATASET_ID:
        raise DatasetError("主数据不支持重命名")
    path = dataset_database_file(dataset_id)
    if not path.exists():
        raise DatasetError("数据集文件已不存在", status_code=404)
    cleaned = name.strip()
    if not cleaned:
        raise DatasetError("名称不能为空")
    if len(cleaned) > 64:
        raise DatasetError("名称过长（最多 64 个字符）")
    metadata = read_metadata(dataset_id)
    metadata["name"] = cleaned
    metadata.setdefault("source", "导入")
    metadata.setdefault("created_at", datetime.now().astimezone().isoformat(timespec="seconds"))
    write_metadata(dataset_id, metadata)
    return _describe(dataset_id, path)


def delete_dataset(dataset_id: str) -> None:
    """移入 datasets/.trash/ 而不是删除，与项目「不做永久删除」的约定一致。"""
    if dataset_id == MAIN_DATASET_ID:
        raise DatasetError("主数据不支持删除")
    if dataset_id == read_active_dataset_id():
        raise DatasetError("不能删除当前正在使用的数据集，请先切换到其它数据集")
    path = dataset_database_file(dataset_id)
    if not path.exists():
        raise DatasetError("数据集文件已不存在", status_code=404)

    trash = trash_directory()
    trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        shutil.move(str(path), str(trash / f"{dataset_id}-{stamp}.db"))
        metadata = dataset_metadata_file(dataset_id)
        if metadata.exists():
            shutil.move(str(metadata), str(trash / f"{dataset_id}-{stamp}.json"))
    except OSError as exc:
        raise DatasetError(f"移动到回收目录失败：{exc}", status_code=500) from exc
    logger.info("数据集已移入回收目录 id=%s", dataset_id)


def export_all_datasets(bind: Engine, staging_dir: Path) -> Path:
    """导出**全部数据集**：活动的那份 + 其余每一份都在包里。

    为什么需要它：默认的导出只带**当前活动**的那一份，其余数据集（用户可能有好几份，
    例如给不同求职方向各开一套）不会进包。一个用户"备份了"却丢了几份数据集，通常要到
    很久以后翻旧记录时才发现，那时原始文件可能早就不在了。
    """
    active = read_active_dataset_id()
    extras: list[ExtraDatabase] = []
    for item in list_datasets():
        if item["id"] == active or not item.get("exists"):
            continue
        extras.append(
            ExtraDatabase(
                dataset_id=item["id"],
                name=item["name"],
                source=dataset_database_file(item["id"]),
                metadata=dict(read_metadata(item["id"]) or {}),
            )
        )
    return create_backup_archive(bind, staging_dir, extra_databases=extras)


def export_dataset(dataset_id: str, bind: Engine, staging_dir: Path) -> Path:
    """导出指定数据集为备份包。"""
    target = dataset_database_file(dataset_id)
    if not target.exists():
        raise DatasetError("数据集文件已不存在", status_code=404)
    if dataset_id == read_active_dataset_id():
        return create_backup_archive(bind, staging_dir)
    # 非活动数据集：临时建一个引擎取一致快照，用完立即释放（Windows 文件句柄）。
    temporary = database.build_engine(database.database_url_for(target))
    try:
        return create_backup_archive(temporary, staging_dir)
    finally:
        temporary.dispose()
