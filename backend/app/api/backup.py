"""数据备份接口：导出全部数据、上传备份包、把备份包恢复回来。

恢复会整体替换用户数据，因此两个写入端点都要求请求来自本机回环，与「读取密钥
明文」同级防护。上传还要求 ``Content-Type: application/zip``：它不在 CORS 简单
请求允许的类型里，跨站页面必须先发预检，而预检只放行本机前端；这条比 loopback
更贴近真实的 CSRF 场景。上传与恢复分成两步，中间用一次性 token 关联，用户可以在
真正覆盖数据之前先看到备份包里有什么。
"""
import logging
import re
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ..config import get_settings
from ..database import engine
from ..schemas.backup import BackupApplyRequest
from ..services.data_backup import (
    BackupError,
    apply_archive,
    create_backup_archive,
    export_directory,
    inspect_archive,
    purge_stale_restores,
    restore_directory,
)
from ..services.exporter import sanitize_filename
from . import settings as settings_api

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings/backup", tags=["settings"])

# 中间件按这个常量放宽请求体上限；路由改名时必须同步，否则豁免会静默失效。
UPLOAD_PATH = f"{router.prefix}/upload"

# token 由本模块生成，严格限定为 32 位十六进制，避免被拼成路径读到目录外的文件。
_TOKEN_PATTERN = re.compile(r"\A[0-9a-f]{32}\Z")
# Windows 把 .zip 映射成 application/x-zip-compressed，两种都接受。
_ZIP_CONTENT_TYPES = frozenset({"application/zip", "application/x-zip-compressed"})


def _require_loopback(request: Request) -> None:
    # 复用设置接口里的判定，保持两处口径一致（测试也会替换那一个函数）。
    if not settings_api._is_loopback_request(request):  # noqa: SLF001
        raise HTTPException(status_code=403, detail="备份的导出与恢复只允许在本机操作")


def _archive_path_for(token: str):
    if not _TOKEN_PATTERN.match(token):
        raise HTTPException(status_code=400, detail="备份标识无效，请重新选择文件")
    path = restore_directory(engine) / f"{token}.zip"
    if not path.is_file():
        raise HTTPException(status_code=400, detail="备份文件已失效，请重新选择文件")
    return path


@router.get("/export")
def export_backup(request: Request) -> FileResponse:
    """把全部用户数据打成一个压缩包返回。"""
    _require_loopback(request)
    try:
        archive_path = create_backup_archive(engine, export_directory(engine))
    except BackupError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    logger.info("已导出用户数据备份 file=%s", archive_path.name)
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
        # 正常情况下响应结束即删；客户端中断时由下次启动的目录清理兜底。
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )


@router.post("/upload")
async def upload_backup(request: Request) -> dict:
    """流式接收备份包并返回预览信息，不改动当前数据。"""
    _require_loopback(request)
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in _ZIP_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="请上传 ResumeForge 导出的 .zip 备份文件")

    settings = get_settings()
    limit = settings.max_backup_upload_mb * 1024 * 1024
    directory = restore_directory(engine)
    directory.mkdir(parents=True, exist_ok=True)
    purge_stale_restores(engine)

    token = uuid4().hex
    archive_path = directory / f"{token}.zip"
    received = 0
    try:
        with archive_path.open("wb") as target:
            async for chunk in request.stream():
                received += len(chunk)
                if received > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"备份文件过大，最大允许 {settings.max_backup_upload_mb} MB",
                    )
                target.write(chunk)
        preview = inspect_archive(archive_path, engine, directory)
    except BackupError as exc:
        archive_path.unlink(missing_ok=True)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except BaseException:
        archive_path.unlink(missing_ok=True)
        raise

    return {"token": token, "size_bytes": received, **preview}


@router.post("/apply")
def apply_backup(payload: BackupApplyRequest, request: Request) -> dict:
    """用已上传的备份包覆盖当前数据。

    这里刻意不使用 ``Depends(get_db)``：恢复要先释放连接池再替换数据库文件，
    本请求自己持有的会话会在 Windows 上锁住文件，让替换失败。
    """
    _require_loopback(request)
    archive_path = _archive_path_for(payload.token)
    try:
        return apply_archive(archive_path, engine, restore_directory(engine))
    except BackupError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    finally:
        archive_path.unlink(missing_ok=True)
