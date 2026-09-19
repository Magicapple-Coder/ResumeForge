"""离线分享包：把一份**脱敏后**的简历打包成一个可离线交付、可回收评论的产物。

分享包不是一份实时视图，而是**生成那一刻的只读快照**：脱敏后的 HTML/PDF 文件清单 +
``ResumeContent`` 只读快照 + 脱敏配置快照，外加一个本地离线 token。对方拿到目录就能
离线打开；想回传评论时，把 Markdown/JSON 评论文件交回来，路径记在 ``comments_file``。

设计要点：

- **权限两态**（read_only/comment）：``read_only`` 只能看，``comment`` 允许回传评论。
- **快照而非引用**：``snapshot`` 存只读 ResumeContent JSON，``redaction_config`` 存当时
  生效的脱敏配置——源简历之后怎么改都不影响已发出的分享包。
- **源简历/岗位删除不连坐**：``resume_id``/``job_id`` 用 ``SET NULL``；快照与文件清单
  已经独立成包，删了源头分享包仍完整。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow

# ===== 分享权限（前后端共用一份取值）=====
SHARE_PERMISSION_READ_ONLY = "read_only"
SHARE_PERMISSION_COMMENT = "comment"
SHARE_PERMISSIONS = (
    SHARE_PERMISSION_READ_ONLY,
    SHARE_PERMISSION_COMMENT,
)


class SharePackage(Base):
    """一个离线分享包。"""

    __tablename__ = "share_package"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    # 源简历与关联岗位：删除后置空，快照与文件清单仍完整。
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume_record.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True
    )
    # 文件清单：[{"name","path","format","size","sha256"}]
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    permission: Mapped[str] = mapped_column(String(16), default=SHARE_PERMISSION_READ_ONLY)
    # 只读 ResumeContent 快照（生成那一刻的内容）。
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # 评论回传文件路径（Markdown/JSON）。
    comments_file: Mapped[str] = mapped_column(String(512), default="")
    # 本地离线 token：唯一，用于校验"这个目录确实是发给某人的那一份"。
    share_token: Mapped[str] = mapped_column(String(64), unique=True)
    # 脱敏配置快照（生成时的 redaction options）。
    redaction_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # 软删除时间戳：NULL 表示「没删」。列表查询一律复用 ``services/trash.live_only``。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


__all__ = [
    "SHARE_PERMISSIONS",
    "SHARE_PERMISSION_COMMENT",
    "SHARE_PERMISSION_READ_ONLY",
    "SharePackage",
]
