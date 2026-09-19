"""离线分享包（R-18）的请求/响应结构。

分享包是一份**生成那一刻的只读快照**：脱敏 HTML / PDF 文件清单 + 只读
``ResumeContent`` 快照 + 脱敏配置快照 + 一个本地离线 token。权限只有两态
（``read_only`` / ``comment``），且**只做标记**——离线包里没有在线鉴权，权限决定的是
是否额外生成一份评论回传文件。

``redact_options`` 直接复用 ``schemas/export.RedactionOptions``：脱敏规则仍只有
``services/privacy.redact`` 一份实现，这里只是把 HTTP 请求的字段白名单化。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models.share_package import SHARE_PERMISSIONS
from .export import RedactionOptions

SharePermission = Literal["read_only", "comment"]

MAX_COMMENT_CHARS = 200_000


class SharePackageCreate(BaseModel):
    """生成分享包的请求体：指定源简历、权限与脱敏范围。"""

    model_config = ConfigDict(extra="forbid")

    resume_id: int = Field(ge=1)
    permission: SharePermission = "read_only"
    redact_options: RedactionOptions = Field(default_factory=RedactionOptions)

    @field_validator("permission")
    @classmethod
    def permission_must_be_supported(cls, value: str) -> str:
        if value not in SHARE_PERMISSIONS:
            raise ValueError(f"无效的分享权限，可选值：{'、'.join(SHARE_PERMISSIONS)}")
        return value


class ShareFileOut(BaseModel):
    """分享包里的一个产物文件。``download_url`` 是下载用的相对链接。"""

    name: str
    path: str
    format: str
    size: int
    sha256: str
    download_url: str = ""


class SharePackageBrief(BaseModel):
    """列表项：不带文件清单与快照，避免大 JSON 反复传输。"""

    id: int
    title: str
    resume_id: int | None = None
    job_id: int | None = None
    permission: str
    file_count: int = 0
    created_at: datetime
    updated_at: datetime


class SharePackageOut(BaseModel):
    """详情：文件清单、只读快照、脱敏配置与本地 token。"""

    id: int
    title: str
    resume_id: int | None = None
    job_id: int | None = None
    permission: str
    files: list[ShareFileOut] = Field(default_factory=list)
    snapshot: dict = Field(default_factory=dict)
    comments_file: str = ""
    share_token: str = ""
    redaction_config: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ShareCommentsOut(BaseModel):
    """评论回传文件的内容与格式。"""

    filename: str
    format: Literal["markdown", "json"] = "markdown"
    content: str = ""


class ShareCommentsImport(BaseModel):
    """导入收件人回传的评论（Markdown 或 JSON）。"""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(default="", max_length=MAX_COMMENT_CHARS)
    format: Literal["markdown", "json"] = "markdown"


class ShareRevealOut(BaseModel):
    """「打开所在文件夹」的结果：只返回该分享包自己的目录，不接受任意路径。"""

    directory: str


__all__ = [
    "MAX_COMMENT_CHARS",
    "ShareCommentsImport",
    "ShareCommentsOut",
    "ShareFileOut",
    "SharePackageBrief",
    "SharePackageCreate",
    "SharePackageOut",
    "SharePermission",
    "ShareRevealOut",
]
