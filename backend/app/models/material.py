"""资料箱与备选岗位模型。

两者都是"暂时还没归档进正式流程的原始材料"：

- ``Material``（资料箱）：证书、作品、链接、笔记等零散资料，供用户集中管理与
  助手按需检索；文件内容与助手技能包一样存在数据库列里，磁盘上没有单独副本。
- ``CandidateJob``（备选岗位）：还没核对的招聘信息（粘贴文本或截图），确认后
  再走识别流程导入成正式岗位。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow

# 备选岗位的状态：待处理 / 已导入正式岗位
CANDIDATE_JOB_PENDING = "pending"
CANDIDATE_JOB_IMPORTED = "imported"
CANDIDATE_JOB_STATUSES = (CANDIDATE_JOB_PENDING, CANDIDATE_JOB_IMPORTED)

# 资料箱分类：给用户一个起点，仍允许自定义文本。
MATERIAL_CATEGORIES = (
    "证书",
    "作品",
    "链接",
    "笔记",
    "实习材料",
    "校园材料",
    "其他",
)


class Material(Base):
    __tablename__ = "material"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    category: Mapped[str] = mapped_column(String(64), default="其他")
    content: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1024), default="")
    # [{"name": "证书.pdf", "mime_type": "application/pdf", "size_bytes": 1234,
    #   "text": "提取出的文字", "data_url": "图片缩略图（可选）"}]
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CandidateJob(Base):
    __tablename__ = "candidate_job"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    company: Mapped[str] = mapped_column(String(128), default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    # 招聘截图（受限于与岗位备注相同的图片校验），存 base64 data URL。
    images: Mapped[list[str]] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="手动添加")
    status: Mapped[str] = mapped_column(String(16), default=CANDIDATE_JOB_PENDING, index=True)
    # 导入成功后指向正式岗位；岗位被删除时置空，备选记录仍保留。
    imported_job_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
