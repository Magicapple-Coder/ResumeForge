"""离线分享包接口（prefix ``/api/share-packages``）。

生成一份分享包 = 脱敏 HTML / PDF + 只读快照 + 评论回传文件 + 本地 token，全部落在
本地目录；列表 / 详情 / 评论读取 / 评论导入 / 文件下载都走这里。权限只做标记，
不做在线鉴权（离线包本来就是发出去给别人看的）。
"""
import logging
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.share_package import (
    ShareCommentsImport,
    ShareCommentsOut,
    SharePackageBrief,
    SharePackageCreate,
    SharePackageOut,
    ShareRevealOut,
)
from ..services import trash
from ..services.privacy import RedactionOptions as PrivacyRedactionOptions
from ..services.share_package import (
    SharePackageError,
    create_share_package,
    import_comments,
    list_share_packages,
    package_directory,
    read_comments,
    share_package_brief,
    share_package_or_none,
    share_package_out,
    share_root,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/share-packages", tags=["share-packages"])

_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".pdf": "application/pdf",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def _package_or_404(db: Session, share_id: int):
    package = share_package_or_none(db, share_id)
    if package is None:
        raise HTTPException(status_code=404, detail="分享包不存在或已被删除")
    return package


def _is_windows() -> bool:
    """是否 Windows 桌面环境：只有 Windows 能直接调 ``explorer`` 打开目录。"""
    return os.name == "nt"


@router.post("", response_model=SharePackageOut, status_code=201)
def create_share_package_entry(payload: SharePackageCreate, db: Session = Depends(get_db)):
    """生成分享包：脱敏 HTML/PDF + 只读快照 + 评论回传文件 + 本地 token。"""
    options = PrivacyRedactionOptions(**payload.redact_options.model_dump())
    try:
        package = create_share_package(
            db,
            resume_id=payload.resume_id,
            permission=payload.permission,
            redact_options=options,
        )
    except SharePackageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return share_package_out(package)


@router.get("", response_model=list[SharePackageBrief])
def read_share_packages(
    keyword: str = Query(default=""),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return [share_package_brief(item) for item in list_share_packages(db, keyword=keyword, limit=limit)]


@router.get("/{share_id}", response_model=SharePackageOut)
def read_share_package(share_id: int, db: Session = Depends(get_db)):
    return share_package_out(_package_or_404(db, share_id))


@router.delete("/{share_id}", status_code=204)
def remove_share_package(share_id: int, db: Session = Depends(get_db)):
    """移入回收站（软删除）。

    只清 DB 行（``deleted_at``），**不清理磁盘产物**——文件清单已独立成包，恢复后仍可
    继续使用；彻底删除在「回收站」里另做。
    """
    package = _package_or_404(db, share_id)
    trash.soft_delete(db, "share_package", package)
    db.commit()


@router.post("/{share_id}/reveal", response_model=ShareRevealOut)
def reveal_share_package_directory(share_id: int, db: Session = Depends(get_db)):
    """打开该分享包所在的本地目录。

    只接受分享包 id、由服务端解析目录，**绝不接受前端传任意路径**；目录必须落在分享根
    目录内（``share_root``），否则按不存在处理，防越界。仅 Windows 支持自动打开。
    """
    package = _package_or_404(db, share_id)
    directory = package_directory(db.get_bind(), package.id).resolve()
    root = share_root(db.get_bind()).resolve()
    # ``package_directory`` 恒为 ``<root>/<id>``，这里再校验一次兜底：只要不是 root 的直接
    # 子目录、或目录不存在，都当不存在——绝不打开分享根目录之外的任意路径。
    if directory.parent != root or not directory.is_dir():
        raise HTTPException(status_code=404, detail="分享包目录不存在")
    if not _is_windows():
        raise HTTPException(
            status_code=409,
            detail="当前系统不支持自动打开文件夹，请手动进入上方「本地目录」查看",
        )
    subprocess.Popen(["explorer", str(directory)])
    return ShareRevealOut(directory=str(directory))


@router.get("/{share_id}/comments", response_model=ShareCommentsOut)
def read_share_package_comments(share_id: int, db: Session = Depends(get_db)):
    return read_comments(_package_or_404(db, share_id))


@router.post("/{share_id}/comments/import", response_model=ShareCommentsOut)
def import_share_package_comments(
    share_id: int, payload: ShareCommentsImport, db: Session = Depends(get_db)
):
    """导入收件人回传的评论（Markdown 或 JSON），写回分享包目录。"""
    package = _package_or_404(db, share_id)
    try:
        return import_comments(db, package, content=payload.content, format=payload.format)
    except SharePackageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{share_id}/files/{filename}")
def download_share_package_file(share_id: int, filename: str, db: Session = Depends(get_db)):
    """下载分享包里的某个产物文件（只允许目录内的文件，防路径穿越）。"""
    package = _package_or_404(db, share_id)
    directory = package_directory(db.get_bind(), package.id).resolve()
    # 只取 basename，并拒绝任何仍逃逸到目录外的路径。
    safe_name = Path(filename).name
    path = (directory / safe_name).resolve()
    if path.parent != directory or not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=safe_name)
