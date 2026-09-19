"""内推管理：一条记录对应一次"找人内推"的动作。

内推和"投递台自动投递"是两件事：投递台记录的是**系统替用户发出的申请**，内推记录的是
**用户通过人脉拿到的一次推荐机会**——内推人、联系方式、关系这些只有人脉才有，自动投递
路径里不存在。两者通过 ``track_id`` 关联：内推成功后若能落到求职进度（``application_track``）
里的某条记录，就算"已转化"。

设计要点：

- **状态四类**（``active``/``submitted``/``closed``/``invalid``）：记录一次内推从"已联系、
  等人推"到"已提交""已关闭（没戏）""无效（联系不上/对方拒绝）"的完整生命周期。
- **岗位被删不连坐**：``job_id`` 用 ``SET NULL`` + ``job_title``/``company`` 快照，删了岗位
  记录仍可读；``track_id`` 同理，删除进度记录不清掉内推历史。
- **转化口径由关联的 ``ApplicationTrack`` 派生，不读表里的 ``converted`` 列**：`converted`
  是迁移 `0018` 留下的**历史占位列**（写入侧不接受、读取侧用 `referral_service._is_converted`
  覆盖），`services/referral_service.py` 是转化口径的唯一来源。
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow

# ===== 内推状态（前后端共用一份取值）=====
REFERRAL_STATUS_ACTIVE = "active"
REFERRAL_STATUS_SUBMITTED = "submitted"
REFERRAL_STATUS_CLOSED = "closed"
REFERRAL_STATUS_INVALID = "invalid"
REFERRAL_STATUSES = (
    REFERRAL_STATUS_ACTIVE,
    REFERRAL_STATUS_SUBMITTED,
    REFERRAL_STATUS_CLOSED,
    REFERRAL_STATUS_INVALID,
)


class Referral(Base):
    """一条内推记录。"""

    __tablename__ = "referral"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 岗位删除后记录仍可读（SET NULL + 快照）。
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_title: Mapped[str] = mapped_column(String(128), default="")
    company: Mapped[str] = mapped_column(String(128), default="")
    # 内推人信息：姓名、联系方式、关系（朋友/前同事/网友…）。
    referrer_name: Mapped[str] = mapped_column(String(128), default="")
    referrer_contact: Mapped[str] = mapped_column(String(128), default="")
    relation: Mapped[str] = mapped_column(String(64), default="")
    # 内推岗位与渠道（官网内推码 / 牛客 / 脉脉 / 熟人直接递…）。
    position: Mapped[str] = mapped_column(String(128), default="")
    channel: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default=REFERRAL_STATUS_ACTIVE, index=True)
    # 转化关联的求职进度：内推成功后落到哪条漏斗记录。删除进度记录不连坐。
    track_id: Mapped[int | None] = mapped_column(
        ForeignKey("application_track.id", ondelete="SET NULL"), nullable=True
    )
    # 历史占位列（迁移 0018 引入）：转化口径现由关联 ApplicationTrack 派生，
    # 写入侧不接受该字段、读取侧也不读它（见 services/referral_service._is_converted）。
    # 保留列是为了不破坏既有表结构与旧数据，不新增迁移。
    converted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # YYYY-MM-DD；未知为空串（与资料库既有的日期字段保持一致）。
    submitted_at: Mapped[str] = mapped_column(String(16), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    # 内推码（第 6 批业务代码落地，这里先建列）。
    referral_code: Mapped[str] = mapped_column(String(64), default="")
    # 备注图片路径列表（第 6 批业务代码落地，这里先建列）。
    note_images: Mapped[list[str]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # 软删除时间戳：NULL 表示「没删」。列表查询一律复用 ``services/trash.live_only``。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


__all__ = [
    "REFERRAL_STATUSES",
    "REFERRAL_STATUS_ACTIVE",
    "REFERRAL_STATUS_CLOSED",
    "REFERRAL_STATUS_INVALID",
    "REFERRAL_STATUS_SUBMITTED",
    "Referral",
]
