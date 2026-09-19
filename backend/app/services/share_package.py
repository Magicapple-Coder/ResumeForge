"""离线分享包（R-18）的生成、检索、评论回传与 token 校验。

分享包 = 一份**脱敏后**的简历产物目录，包含：

- ``resume.html`` / ``resume.pdf``：脱敏后的 HTML 与 PDF（复用导出管线）；
- ``resume_snapshot.json``：只读 ``ResumeContent`` 快照（不含照片，与 ``export_json`` 一致）；
- ``manifest.json``：本地离线 token + 权限 + 生成时间（token 落本地目录、可离线校验）；
- ``comments.md``：仅 ``comment`` 权限生成，收件人写评论后交回，导入写回本目录。

权限（``read_only`` / ``comment``）**只做标记**：离线包没有在线鉴权，它决定的是
"是否附带评论回传文件"。源简历 / 岗位删除后 ``SET NULL``，快照与文件清单独立成包，
不连坐。脱敏唯一复用 ``privacy.redact``，导出唯一复用 ``export_pipeline.build_export``。
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import DATA_DIR
from ..models.profile import utcnow
from ..models.resume import ResumeRecord
from ..models.share_package import (
    SHARE_PERMISSION_COMMENT,
    SHARE_PERMISSIONS,
    SharePackage,
)
from ..schemas.resume import ResumeContent
from ..schemas.share_package import (
    ShareCommentsOut,
    ShareFileOut,
    SharePackageBrief,
    SharePackageOut,
)
from . import trash
from .export_pipeline import ExportRequest, RenderContext, build_export
from .pdf_exporter import ResumePDFError
from .privacy import RedactionOptions, redact
from .resume_template_store import resolve_format_config, resolve_style_template
from .resume_templates import DEFAULT_FONT_SCALE, DEFAULT_PAGE_LIMIT, validated_format_config

logger = logging.getLogger(__name__)

# 分享包落在数据目录下（与 captures 同级），天然不进仓库、不进备份。文件型 SQLite
# 时进一步落到数据库同目录：测试库（临时目录）自动隔离，不会写进仓库的 backend/data。
SHARE_PACKAGES_DIR = DATA_DIR / "share_packages"

MAX_SHARE_PACKAGE_LIST = 500

_HTML_FILE = "resume.html"
_PDF_FILE = "resume.pdf"
_SNAPSHOT_FILE = "resume_snapshot.json"
_MANIFEST_FILE = "manifest.json"
_COMMENTS_FILE = "comments.md"


class SharePackageError(Exception):
    """对外暴露的分享包错误，message 为可直接展示给用户的中文提示。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def share_root(bind) -> Path:
    """分享包根目录：文件型 SQLite 落在数据库同目录，其余回退到数据目录。"""
    url = getattr(bind, "url", None)
    database = getattr(url, "database", None)
    if database and database != ":memory:" and Path(database).is_absolute():
        return Path(database).resolve().parent / "share_packages"
    return SHARE_PACKAGES_DIR


def package_directory(bind, share_id: int) -> Path:
    """某个分享包的本地目录：``<数据库目录>/share_packages/<id>``。"""
    return share_root(bind) / str(share_id)


def create_share_token() -> str:
    """生成本地离线 token（32 个十六进制字符，落在 ``share_token`` 的 64 长度内）。"""
    return secrets.token_hex(16)


def verify_share_token(package: SharePackage, token: str) -> bool:
    """校验 token 是否属于这份分享包（常数时间比较，防时序侧信道）。"""
    return bool(token) and secrets.compare_digest(package.share_token or "", token)


def _record_format_config(db: Session, record: ResumeRecord) -> dict:
    """与 ``api/resumes.py`` 同口径：具名格式模板 + 只属于这份简历的覆盖。"""
    config = dict(resolve_format_config(db, record.format_name))
    config.update(validated_format_config(record.format_config))
    return config


def _build_title(resume: ResumeContent) -> str:
    name = (resume.name or "简历").strip() or "简历"
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    return f"{name}-分享包-{timestamp}"[:200]


def _file_entry(directory: Path, name: str, content: bytes, fmt: str) -> dict:
    """把一段字节写入目录并返回 ``files`` 里的条目。"""
    path = directory / name
    path.write_bytes(content)
    return {
        "name": name,
        "path": str(path),
        "format": fmt,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _text_file_entry(directory: Path, name: str, content: str, fmt: str) -> dict:
    return _file_entry(directory, name, content.encode("utf-8"), fmt)


def _initial_comments_text(package: SharePackage) -> str:
    return (
        "# 评论回传\n\n"
        f"分享包：{package.title}\n"
        f"分享码：{package.share_token}\n\n"
        "请在下方写下你的评论，保存后把此文件交回给分享人。\n\n"
        "## 评论\n\n"
    )


def create_share_package(
    db: Session,
    *,
    resume_id: int,
    permission: str,
    redact_options: RedactionOptions | None = None,
) -> SharePackage:
    """生成一份分享包：脱敏 → 渲染 HTML/PDF → 写目录 → 记录文件清单与 token。"""
    record = trash.get_live(db, ResumeRecord, resume_id)
    if record is None:
        raise SharePackageError("简历不存在或已被删除", 404)
    if permission not in SHARE_PERMISSIONS:
        raise SharePackageError(f"无效的分享权限，可选值：{'、'.join(SHARE_PERMISSIONS)}", 422)

    resume = ResumeContent.model_validate(record.content)
    options = redact_options or RedactionOptions()
    # 脱敏唯一复用 privacy.redact：分享包与导出、脱敏预览用同一套掩码规则。
    redacted_resume = redact(resume, options)
    # 快照与 export_json 同口径：不带照片 data URL，避免大字段与无意义的个人影像残留。
    snapshot = redacted_resume.model_dump(exclude={"photo"})

    template_name, template_html = resolve_style_template(db, record.template)
    context = RenderContext(
        template=template_name,
        template_html=template_html,
        page_limit=record.page_limit or DEFAULT_PAGE_LIMIT,
        font_scale=record.font_scale or DEFAULT_FONT_SCALE,
        format_config=_record_format_config(db, record),
    )

    # 导出唯一复用 export_pipeline：HTML 与 PDF 都从这里出，不另写渲染逻辑。
    html_artifact = build_export(ExportRequest(format="html"), redacted_resume, context)
    try:
        pdf_artifact = build_export(ExportRequest(format="pdf"), redacted_resume, context)
    except ResumePDFError as exc:
        # 没有中文字体时无法直出 PDF，与导出接口给出一致的可读提示。
        raise SharePackageError(str(exc), 409) from exc

    package = SharePackage(
        title=_build_title(resume),
        resume_id=record.id,
        job_id=record.job_id,
        files=[],
        permission=permission,
        snapshot=snapshot,
        comments_file="",
        share_token=create_share_token(),
        redaction_config=asdict(options),
    )
    db.add(package)
    db.flush()  # 先拿到自增 id，目录用它命名。

    directory = package_directory(db.get_bind(), package.id)
    directory.mkdir(parents=True, exist_ok=True)

    manifest = {
        "share_token": package.share_token,
        "permission": permission,
        "title": package.title,
        "created_at": utcnow().isoformat(),
    }
    files = [
        _file_entry(directory, _HTML_FILE, html_artifact.content, "html"),
        _file_entry(directory, _PDF_FILE, pdf_artifact.content, "pdf"),
        _text_file_entry(
            directory,
            _SNAPSHOT_FILE,
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            "json",
        ),
        _text_file_entry(
            directory,
            _MANIFEST_FILE,
            json.dumps(manifest, ensure_ascii=False, indent=2),
            "json",
        ),
    ]
    if permission == SHARE_PERMISSION_COMMENT:
        files.append(
            _text_file_entry(directory, _COMMENTS_FILE, _initial_comments_text(package), "markdown")
        )
        package.comments_file = str(directory / _COMMENTS_FILE)

    package.files = files
    db.commit()
    db.refresh(package)
    logger.info("已生成分享包 id=%s resume_id=%s permission=%s", package.id, resume_id, permission)
    return package


def list_share_packages(
    db: Session, *, keyword: str = "", limit: int = 200
) -> list[SharePackage]:
    """列出未软删除的分享包，最近的在前。"""
    query = db.query(SharePackage).filter(trash.live_only(SharePackage))
    if keyword.strip():
        query = query.filter(SharePackage.title.like(f"%{keyword.strip()}%"))
    return (
        query.order_by(SharePackage.created_at.desc(), SharePackage.id.desc())
        .limit(max(1, min(limit, MAX_SHARE_PACKAGE_LIST)))
        .all()
    )


def share_package_or_none(db: Session, share_id: int) -> SharePackage | None:
    """取一条分享包；已在回收站里的当作不存在。"""
    return trash.get_live(db, SharePackage, share_id)


def _download_url(package: SharePackage, name: str) -> str:
    return f"/api/share-packages/{package.id}/files/{name}"


def share_package_brief(package: SharePackage) -> SharePackageBrief:
    return SharePackageBrief(
        id=package.id,
        title=package.title,
        resume_id=package.resume_id,
        job_id=package.job_id,
        permission=package.permission,
        file_count=len(package.files or []),
        created_at=package.created_at,
        updated_at=package.updated_at,
    )


def share_package_out(package: SharePackage) -> SharePackageOut:
    files = [
        ShareFileOut(
            name=str(item.get("name", "")),
            path=str(item.get("path", "")),
            format=str(item.get("format", "")),
            size=int(item.get("size", 0)),
            sha256=str(item.get("sha256", "")),
            download_url=_download_url(package, str(item.get("name", ""))),
        )
        for item in (package.files or [])
    ]
    return SharePackageOut(
        id=package.id,
        title=package.title,
        resume_id=package.resume_id,
        job_id=package.job_id,
        permission=package.permission,
        files=files,
        snapshot=package.snapshot or {},
        comments_file=package.comments_file or "",
        share_token=package.share_token or "",
        redaction_config=package.redaction_config or {},
        created_at=package.created_at,
        updated_at=package.updated_at,
    )


def read_comments(package: SharePackage) -> ShareCommentsOut:
    """读取评论回传文件；没有（或文件缺失）时返回空内容。"""
    if not package.comments_file:
        return ShareCommentsOut(filename=_COMMENTS_FILE, format="markdown", content="")
    path = Path(package.comments_file)
    if not path.exists() or not path.is_file():
        return ShareCommentsOut(filename=path.name, format="markdown", content="")
    content = path.read_text(encoding="utf-8")
    fmt = "json" if path.suffix.lower() == ".json" else "markdown"
    return ShareCommentsOut(filename=path.name, format=fmt, content=content)


def import_comments(
    db: Session, package: SharePackage, *, content: str, format: str
) -> ShareCommentsOut:
    """把收件人回传的评论写回分享包目录，并更新 ``comments_file`` 与文件清单。"""
    if format == "json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise SharePackageError("评论内容不是有效的 JSON", 422) from exc
        filename = "comments.json"
    else:
        filename = _COMMENTS_FILE

    directory = package_directory(db.get_bind(), package.id)
    directory.mkdir(parents=True, exist_ok=True)

    files = [item for item in (package.files or []) if not str(item.get("name", "")).startswith("comments.")]
    files.append(_text_file_entry(directory, filename, content, "json" if format == "json" else "markdown"))
    package.files = files
    package.comments_file = str(directory / filename)
    db.commit()
    db.refresh(package)
    logger.info("已导入评论分享包 id=%s format=%s", package.id, format)
    return read_comments(package)


__all__ = [
    "MAX_SHARE_PACKAGE_LIST",
    "SHARE_PACKAGES_DIR",
    "SharePackageError",
    "create_share_package",
    "create_share_token",
    "import_comments",
    "list_share_packages",
    "package_directory",
    "read_comments",
    "share_package_brief",
    "share_package_or_none",
    "share_package_out",
    "share_root",
    "verify_share_token",
]
