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


    # 软删除时间戳：NULL 表示「没删」。列表查询一律加 `deleted_at IS NULL`，
    # 回收站里则只看非 NULL 的行（见 ``services/trash.py``）。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    # 采集任务透传的岗位类型（校招/实习/社招）；空串 = 不限。**仅做入库标注**：
    # 不入去重判据、不参与站点筛选（与薪资/经验/学历"采集后本地筛选"口径一致）。
    job_type: Mapped[str] = mapped_column(String(32), default="", server_default="")
    # 采集多带出来的字段：粘贴文本拿不到城市与薪资，而采集能拿到（迁移 0015）。
    location: Mapped[str] = mapped_column(String(64), default="", server_default="")
    salary: Mapped[str] = mapped_column(String(64), default="", server_default="")
    # 原始岗位链接：既用于**与正式岗位双向去重**（同一链接不再重复采集），
    # 也是"回原站看这条岗位"的入口。
    source_url: Mapped[str] = mapped_column(String(512), default="", server_default="")
    # 采集带回来的 JD 正文与任职要求。**必须与 ``raw_text`` 分开存**：``raw_text`` 是
    # "粘贴进来的原始文本"（手动链路用），而采集已经在服务端把两者按小标题切分好了——
    # 塞进 raw_text 会把这份结构丢掉，导入岗位时又变回"描述与要求混在一起"。
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    requirements: Mapped[str] = mapped_column(Text, default="", server_default="")
    # 产生这条候选的采集批次（``apply_task.id``）。**不建外键**：批次记录被清理掉时
    # 不该连带删掉用户还没处理的候选岗位（与 ``claim_record`` 同样的取舍）。
    collect_task_id: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=CANDIDATE_JOB_PENDING, index=True)
    # 导入成功后指向正式岗位；岗位被删除时置空，备选记录仍保留。
    imported_job_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
