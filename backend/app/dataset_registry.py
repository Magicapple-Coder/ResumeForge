"""数据集注册表：活动数据库的指针，以及各数据集文件的路径约定。

刻意不依赖 SQLAlchemy：``app.database`` 需要在建引擎之前就知道该连哪个文件，
而 :mod:`app.services.datasets` 又依赖 ``app.database`` 的重绑能力，放在这里
可以避免二者互相导入。

布局（全部相对 DATABASE_URL 所在目录，因此测试用临时库时天然隔离）：

    data/
      resume_forge.db        <- DATABASE_URL 指向的文件，即「主数据」
      active.json            <- {"dataset_id": "..."}；缺失表示主数据
      datasets/<id>.db       <- 导入产生的数据集
      datasets/<id>.json     <- 其元信息
      datasets/.trash/       <- 删除的数据集移到这里，不做永久删除
"""

from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path

from .config import get_settings

logger = logging.getLogger(__name__)

DATASETS_DIRNAME = "datasets"
TRASH_DIRNAME = ".trash"
POINTER_FILENAME = "active.json"
METADATA_SUFFIX = ".json"

MAIN_DATASET_ID = "main"
MAIN_DATASET_NAME = "主数据"

# 数据集/临时包的 id 由本模块生成，拼进路径前严格校验，避免路径穿越。
_ID_LENGTH = 16


class DatasetError(Exception):
    """对外暴露的数据集错误，message 可直接展示给用户。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def new_dataset_id() -> str:
    return secrets.token_hex(_ID_LENGTH // 2)


def is_valid_dataset_id(dataset_id: str) -> bool:
    return (
        isinstance(dataset_id, str)
        and len(dataset_id) == _ID_LENGTH
        and all(character in "0123456789abcdef" for character in dataset_id)
    )


def configured_database_file() -> Path:
    """DATABASE_URL 指向的 SQLite 文件；内存库等情况抛 DatasetError。"""
    database_url = get_settings().database_url
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise DatasetError("当前数据库不是本地 SQLite 文件，无法使用数据集功能", status_code=409)
    database = database_url.removeprefix(prefix)
    if database == ":memory:" or database.startswith("file:"):
        raise DatasetError("当前数据库不是本地 SQLite 文件，无法使用数据集功能", status_code=409)
    return Path(database).resolve()


def data_directory() -> Path:
    return configured_database_file().parent


def datasets_directory() -> Path:
    return data_directory() / DATASETS_DIRNAME


def trash_directory() -> Path:
    return datasets_directory() / TRASH_DIRNAME


def pointer_path() -> Path:
    return data_directory() / POINTER_FILENAME


def dataset_database_file(dataset_id: str) -> Path:
    if dataset_id == MAIN_DATASET_ID:
        return configured_database_file()
    if not is_valid_dataset_id(dataset_id):
        raise DatasetError("数据集标识无效")
    return datasets_directory() / f"{dataset_id}.db"


def dataset_metadata_file(dataset_id: str) -> Path:
    if not is_valid_dataset_id(dataset_id):
        raise DatasetError("数据集标识无效")
    return datasets_directory() / f"{dataset_id}{METADATA_SUFFIX}"


def read_active_dataset_id() -> str:
    """返回当前激活的数据集 id；指针缺失或损坏时回落到主数据。"""
    pointer = pointer_path()
    if not pointer.exists():
        return MAIN_DATASET_ID
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        dataset_id = payload.get("dataset_id")
    except (OSError, ValueError, AttributeError) as exc:
        # 指针损坏时保持主数据而不是静默换库：宁可停下，也不要让用户以为
        # 自己在数据集 A 里，实际读写的却是 B。
        logger.warning("数据集指针无法解析，已回落到主数据：%s", exc)
        return MAIN_DATASET_ID
    if dataset_id == MAIN_DATASET_ID or is_valid_dataset_id(dataset_id):
        return dataset_id
    logger.warning("数据集指针内容无效，已回落到主数据：%r", dataset_id)
    return MAIN_DATASET_ID


def write_active_dataset_id(dataset_id: str) -> None:
    if dataset_id != MAIN_DATASET_ID and not is_valid_dataset_id(dataset_id):
        raise DatasetError("数据集标识无效")
    pointer = pointer_path()
    if dataset_id == MAIN_DATASET_ID:
        # 主数据是默认状态，用「没有指针」表示，避免多一个需要维护的文件。
        pointer.unlink(missing_ok=True)
        return
    pointer.parent.mkdir(parents=True, exist_ok=True)
    temporary = pointer.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"dataset_id": dataset_id}, ensure_ascii=False), encoding="utf-8"
    )
    temporary.replace(pointer)


def active_database_file() -> Path:
    """当前应连接的数据库文件；指针指向的文件不存在时报错而不是静默建空库。"""
    dataset_id = read_active_dataset_id()
    database = dataset_database_file(dataset_id)
    if not database.exists():
        raise DatasetError(
            f"当前激活的数据集（{dataset_id}）文件已不存在，请检查 data/datasets 目录后重新选择",
            status_code=409,
        )
    return database


def read_metadata(dataset_id: str) -> dict:
    path = dataset_metadata_file(dataset_id)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("数据集元信息无法解析：%s", path)
        return {}
    return payload if isinstance(payload, dict) else {}


def write_metadata(dataset_id: str, payload: dict) -> None:
    path = dataset_metadata_file(dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
