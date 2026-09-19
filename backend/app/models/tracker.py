"""求职进度：一家公司一个岗位一条记录，随通知往前推进。

投递台记录的是**动作**（这个岗位投出去了、失败了），本模块记录的是**结果**（对方走到哪一步了）。
两者刻意分开：一次投递成功只写一条「已投递」记录，之后的状态变化来自对方发来的通知，
而不是投递行为本身。

设计要点：

- **合并键是归一化后的「公司 + 岗位」**，同一组合只有一条记录，后来的通知覆盖早期的
  「已投递」——这正是漏斗视图成立的前提。归一化只做去空白、统一大小写与全角转半角，
  不做模糊匹配：把两家不同公司合并到一起比留两条重复要糟糕得多。
- **状态只能前进，除非是拒信**。乱序粘贴旧通知（先贴了面试邀请、又贴了三个月前的
  「申请已收到」）不该把进度打回去；而拒信是决定性的，任何时候都覆盖当前状态。
  这条规则收口在 :func:`resolve_status`，界面与接口都从这里取结论。
- **不做推断**：普通自动回执只能落到「已投递」，不能推断出面试或 Offer。识别不出来就
  是「待确认」，由用户自己判断——这是本模块唯一会误导用户的失误来源。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow

# ===== ① 状态：秋招漏斗的六个阶段 =====
STATUS_UNKNOWN = "unknown"
STATUS_APPLIED = "applied"
STATUS_SCREENING = "screening"
STATUS_ASSESSMENT = "assessment"
STATUS_INTERVIEW = "interview"
STATUS_OFFER = "offer"
STATUS_REJECTED = "rejected"

STATUSES = (
    STATUS_APPLIED,
    STATUS_SCREENING,
    STATUS_ASSESSMENT,
    STATUS_INTERVIEW,
    STATUS_OFFER,
    STATUS_REJECTED,
    STATUS_UNKNOWN,
)

STATUS_LABELS = {
    STATUS_APPLIED: "已投递",
    STATUS_SCREENING: "筛选中",
    STATUS_ASSESSMENT: "测评/笔试",
    STATUS_INTERVIEW: "面试",
    STATUS_OFFER: "Offer",
    STATUS_REJECTED: "已结束",
    STATUS_UNKNOWN: "待确认",
}

# 漏斗推进顺序。**已结束不参与排序**——它不是"比 Offer 更进一步"，而是另一条分支，
# 所以单独走 :func:`resolve_status` 里的判定。
STATUS_RANK = {
    STATUS_UNKNOWN: 0,
    STATUS_APPLIED: 1,
    STATUS_SCREENING: 2,
    STATUS_ASSESSMENT: 3,
    STATUS_INTERVIEW: 4,
    STATUS_OFFER: 5,
}

# 「进行中」的定义：还没走到终态，界面上要突出显示。
ACTIVE_STATUSES = frozenset(
    {STATUS_APPLIED, STATUS_SCREENING, STATUS_ASSESSMENT, STATUS_INTERVIEW}
)

# ===== ② 记录来源 =====
SOURCE_APPLY = "apply"
SOURCE_MANUAL = "manual"
SOURCE_RECOGNIZED = "recognized"
SOURCES = (SOURCE_APPLY, SOURCE_MANUAL, SOURCE_RECOGNIZED)

SOURCE_LABELS = {
    SOURCE_APPLY: "投递台自动记录",
    SOURCE_MANUAL: "手动添加",
    SOURCE_RECOGNIZED: "识别导入",
}

# ===== ③ 合并结论：让"这次识别改变了什么"能被如实回报 =====
# 只有三种。没有"跳过"——用户取消勾选的条目根本不会进入请求，让服务层再去区分
# "没被选中"和"选中了但没变化"只会把两件不同的事混成一个字段。
MERGE_CREATED = "created"
MERGE_UPDATED = "updated"
MERGE_UNCHANGED = "unchanged"
MERGE_RESULTS = (MERGE_CREATED, MERGE_UPDATED, MERGE_UNCHANGED)

MERGE_LABELS = {
    MERGE_CREATED: "新增记录",
    MERGE_UPDATED: "更新进度",
    MERGE_UNCHANGED: "已是最新，未改动",
}


def status_label(status: str) -> str:
    """面向用户的状态名；未知取值给出中性描述，不猜成「已投递」。"""
    return STATUS_LABELS.get(status, "未知状态")


def resolve_status(current: str, incoming: str) -> str:
    """合并时的状态取舍：**只能前进，拒信除外**。

    - 收到拒信：无条件覆盖（流程已经结束了，之后不该再有任何推送把它复活）。
    - 其它情况：只有不比当前更早的阶段才采纳。乱序粘贴旧通知时保留较新的结论，
      调用方据此把这次识别标成「未改变」而不是当作更新。
    - 当前是「待确认」时任何明确状态都能覆盖它（包括已结束）。
    """
    if incoming == STATUS_REJECTED:
        return incoming
    if incoming not in STATUS_RANK:
        return current
    if current not in STATUS_RANK:
        # 当前是待确认或未知：收到的第一个明确状态就是最新结论。
        return incoming
    if STATUS_RANK[incoming] >= STATUS_RANK[current]:
        return incoming
    return current


def is_active(status: str) -> bool:
    """是否仍在流程中（用于统计与高亮）。"""
    return status in ACTIVE_STATUSES


def normalize_key(value: str) -> str:
    """归一化合并键：去空白、统一大小写、全角转半角。

    只做这几件事是因为它们**不会把不同的东西变成同一个**。加"去掉「有限公司」后缀"
    之类的规则看着聪明，实际会把「XX科技」和「XX科技有限公司」合并——同一家还好，
    但「XX科技」和「XX科技有限公司（上海）」就是两家了，而用户没法撤销一次错误合并。
    """
    text = (value or "").strip()
    # 全角字符（！到～）映射回 ASCII，中文标点不在这个区间，不受影响。
    text = "".join(chr(ord(ch) - 0xFEE0) if "！" <= ch <= "～" else ch for ch in text)
    text = "".join(text.split()).casefold()
    return text[:128]


class ApplicationTrack(Base):
    """一家公司一个岗位的求职进度。"""

    __tablename__ = "application_track"
    __table_args__ = (
        UniqueConstraint("company_key", "title_key", name="uq_application_track_company_title"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(128), default="")
    # 归一化后的合并键：空白/大小写/全角差异不该产生第二条记录。
    company_key: Mapped[str] = mapped_column(String(128), default="", index=True)
    title_key: Mapped[str] = mapped_column(String(128), default="", index=True)

    status: Mapped[str] = mapped_column(String(24), default=STATUS_APPLIED, index=True)
    # 状态补充说明，例如「二面」「HR 面」「技术面挂了」。状态本身只有六种，
    # 具体到第几轮放在这里，避免状态枚举无限膨胀。
    stage_note: Mapped[str] = mapped_column(String(64), default="")

    # 日期统一用 YYYY-MM-DD 字符串，与资料库既有的日期字段保持一致。
    applied_at: Mapped[str] = mapped_column(String(16), default="")
    # 当前状态对应的日期（通知里写的日期，没有则留空）。
    status_date: Mapped[str] = mapped_column(String(16), default="")

    next_action: Mapped[str] = mapped_column(String(255), default="")
    next_action_date: Mapped[str] = mapped_column(String(16), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    # 状态来源摘录（来自哪封通知/哪句话）。只存简短片段，不存整封邮件。
    evidence: Mapped[str] = mapped_column(Text, default="")

    # 关联的岗位与简历：删掉之后记录仍要可读，所以 SET NULL + 保留快照字段。
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume_record.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(16), default=SOURCE_MANUAL)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # 软删除时间戳：NULL 表示「没删」。列表查询一律加 `deleted_at IS NULL`，
    # 回收站里则只看非 NULL 的行（见 ``services/trash.py``）。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


__all__ = [
    "ACTIVE_STATUSES",
    "ApplicationTrack",
    "MERGE_CREATED",
    "MERGE_LABELS",
    "MERGE_RESULTS",
    "MERGE_UNCHANGED",
    "MERGE_UPDATED",
    "SOURCE_APPLY",
    "SOURCE_LABELS",
    "SOURCE_MANUAL",
    "SOURCE_RECOGNIZED",
    "SOURCES",
    "STATUSES",
    "STATUS_APPLIED",
    "STATUS_ASSESSMENT",
    "STATUS_INTERVIEW",
    "STATUS_LABELS",
    "STATUS_OFFER",
    "STATUS_RANK",
    "STATUS_REJECTED",
    "STATUS_SCREENING",
    "STATUS_UNKNOWN",
    "is_active",
    "normalize_key",
    "resolve_status",
    "status_label",
]
