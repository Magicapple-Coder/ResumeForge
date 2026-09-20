"""数据集接口：列出、导入、切换、重命名、删除与导出。

一份数据集就是一整份数据库（岗位、资料、简历、助手会话、设置全在里面）。导入一个
备份包会**新建**一份数据集而不触碰当前正在使用的数据，用户随后自行决定是否切过去，
所以这条路径本身是可撤销的。

导入与切换都会改写用户的数据归属，因此都要求请求来自本机回环；导入还要求
``Content-Type: application/zip``——它不在 CORS 简单请求允许的类型里，跨站页面必须
先发预检，而预检只放行本机前端。
"""
import logging
import re
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from .. import database
from ..services.datasets import (
    activate_dataset,
    create_dataset,
    delete_dataset,
    export_dataset,
    import_dataset,
    list_datasets,
    rename_dataset,
)
from ..services.data_backup import (
    BackupError,
    export_directory,
    purge_stale_restores,
    restore_directory,
)
from ..services.exporter import sanitize_filename
from . import settings as settings_api

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings/datasets", tags=["settings"])

# 中间件按这个常量放宽请求体上限；路由改名时必须同步，否则豁免会静默失效。
IMPORT_PATH = f"{router.prefix}/import"

# 数据集 id 由后端生成，拼进路径前严格校验，避免路径穿越。
_ID_PATTERN = re.compile(r"\A(?:main|[0-9a-f]{16})\Z")
# Windows 把 .zip 映射成 application/x-zip-compressed，两种都接受。
_ZIP_CONTENT_TYPES = frozenset({"application/zip", "application/x-zip-compressed"})


def _require_loopback(request: Request) -> None:
    # 复用设置接口里的判定，保持两处口径一致（测试也会替换那一个函数）。
    if not settings_api._is_loopback_request(request):  # noqa: SLF001
        raise HTTPException(status_code=403, detail="数据集管理只允许在本机操作")


def _require_valid_id(dataset_id: str) -> str:
    if not _ID_PATTERN.match(dataset_id):
        raise HTTPException(status_code=400, detail="数据集标识无效")
    return dataset_id


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, BackupError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    # DatasetError 与 BackupError 同构（都有 status_code / 中文 message）。
    status = getattr(exc, "status_code", 400)
    return HTTPException(status_code=status, detail=str(exc))


@router.get("")
def read_datasets(request: Request) -> list[dict]:
    _require_loopback(request)
    return list_datasets()


class _DatasetCreateIn(BaseModel):
    """新建空数据集的请求体：只收一个自定义名称。"""

    name: str = Field(min_length=1, max_length=64)


@router.post("")
def create(request: Request, payload: _DatasetCreateIn) -> dict:
    """新建一份空数据集（自定义名称），返回描述；创建后可激活（激活后为空视图）。"""
    _require_loopback(request)
    try:
        return create_dataset(payload.name, database.engine)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/import")
async def import_archive(request: Request) -> dict:
    """流式接收备份包并落成一份新数据集，不触碰当前数据。"""
    _require_loopback(request)
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in _ZIP_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="请上传 ResumeForge 导出的 .zip 备份文件")

    from ..config import get_settings

    settings = get_settings()
    limit = settings.max_backup_upload_mb * 1024 * 1024
    directory = restore_directory(database.engine)
    directory.mkdir(parents=True, exist_ok=True)
    purge_stale_restores(database.engine)

    staging = directory / f"{uuid4().hex}.zip"
    received = 0
    try:
        with staging.open("wb") as target:
            async for chunk in request.stream():
                received += len(chunk)
                if received > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"备份文件过大，最大允许 {settings.max_backup_upload_mb} MB",
                    )
                target.write(chunk)
        created = import_dataset(
            staging, request.query_params.get("name", ""), database.engine, directory
        )
    except HTTPException:
        staging.unlink(missing_ok=True)
        raise
    except Exception as exc:
        staging.unlink(missing_ok=True)
        raise _translate(exc) from exc
    finally:
        staging.unlink(missing_ok=True)

    logger.info("已导入数据集 id=%s size=%s", created["id"], received)
    return created


@router.post("/{dataset_id}/activate")
def activate(request: Request, dataset_id: str) -> dict:
    """切换当前使用的数据集。

    刻意不使用 ``Depends(get_db)``：切换要释放连接池再换引擎，本请求自己持有的
    会话会在 Windows 上锁住文件。
    """
    _require_loopback(request)
    try:
        return activate_dataset(_require_valid_id(dataset_id), database.engine)
    except Exception as exc:
        raise _translate(exc) from exc


@router.patch("/{dataset_id}")
def rename(request: Request, dataset_id: str) -> dict:
    _require_loopback(request)
    name = request.query_params.get("name", "")
    try:
        return rename_dataset(_require_valid_id(dataset_id), name)
    except Exception as exc:
        raise _translate(exc) from exc


@router.delete("/{dataset_id}", status_code=204)
def remove(request: Request, dataset_id: str) -> None:
    _require_loopback(request)
    try:
        delete_dataset(_require_valid_id(dataset_id))
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/{dataset_id}/export")
def export(request: Request, dataset_id: str) -> FileResponse:
    """把指定数据集导出为备份包。"""
    _require_loopback(request)
    staging = export_directory(database.engine)
    try:
        archive_path = export_dataset(_require_valid_id(dataset_id), database.engine, staging)
    except Exception as exc:
        raise _translate(exc) from exc

    logger.info("已导出数据集 id=%s file=%s", dataset_id, archive_path.name)
    return FileResponse(
        archive_path,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(sanitize_filename(archive_path.name), safe='')}"
            ),
            # 备份包含全部个人数据，禁止浏览器与中间层缓存。
            "Cache-Control": "no-store",
        },
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )
