"""回收站：十三类内容的软删除、恢复与彻底删除。

**为什么是软删除**（一个 ``deleted_at`` 时间戳）而不是把行搬到另一张表：搬表意味着外键、快照
字段、去重判据全部要重建一遍，而这些现在都是好的。软删除只多一句"什么时候删的"，列表查询加
``IS NULL``、回收站看非 NULL、恢复就是清空时间戳——三处都极难写错。

**范围克制**：只覆盖用户真正会心疼的十三类——岗位、简历记录、投递记录、事实台账条目、资料箱
材料、助手会话、面经、内推、提醒、分享包、题库历史、复盘历史、知识库。列级别、模板副本、
数据集这类要么有明确的沿用关系、要么本来就能重建，不做回收站；每个可删项都进回收站，只会让
回收站自己变成垃圾场。

**完整性红线**：凡是模型里带 ``deleted_at`` 列的表，都必须在这里登记（``TRASH_SPECS``），否则
就会出现"半软删"——列表里消失、回收站里也找不到、既不能恢复也无法彻底删除，形成永久僵尸行。
``tests/test_trash.py::test_every_deleted_at_table_is_registered`` 用 ``Base.metadata`` 扫全库钉住
这层一一对应。

**三个最容易漏的接合点**（都在调用方，这里负责提供正确的判据）：

1. **去重必须把回收站里的也算"已存在"**。否则"删掉 → 再采集一次"会造出第二条同一岗位，
   而用户以为自己只是删了一条。判据 `job_service.find_by_job_identity` **刻意不过滤**
   ``deleted_at``，调用方据此给出「在回收站里」的提示。
2. **列表 / 匹配分析 / 投递准入 / 数据集导出都不该看到已删除内容**，统一用 ``live_only()``。
3. **彻底删除是真删、不可恢复**，所以它是唯一需要用户二次确认的动作；`restore` 与 `purge`
   分开两个接口，不允许一个"删除"按钮同时具备两种语义。

删除某条内容时**不连带删除它的关联对象**（岗位删除 → 投递记录保留快照字段并按既有约定
``SET NULL``），这条行为回收站前后完全一致——回收站只改变"这条还在不在列表里"。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..models.assistant import ChatConversation
from ..models.claim import ClaimRecord
from ..models.interview_experience import InterviewExperience
from ..models.interview_review_record import InterviewReviewRecord
from ..models.job import Job
from ..models.knowledge_entry import KnowledgeEntry
from ..models.material import Material
from ..models.profile import utcnow
from ..models.question_bank_record import QuestionBankRecord
from ..models.referral import Referral
from ..models.reminder import Reminder
from ..models.resume import ResumeRecord
from ..models.share_package import SharePackage
from ..models.tracker import ApplicationTrack

logger = logging.getLogger(__name__)

# 一次最多列多少条。回收站是"最近删了什么"的地方，不是归档区；
# 给上限也让"我不小心清空了"不至于变成一次巨大的响应。
MAX_TRASH_ITEMS = 500


@dataclass(frozen=True)
class TrashSpec:
    """一类可回收内容的描述。新增一类只需要在这里加一行。

    大多数类型的标题就是某个字段（``title_field``）；个别类型（如内推）的标题由多个字段拼成，
    用 ``title_builder`` 给一个纯函数即可（优先于 ``title_field``）。
    """

    key: str
    label: str
    model: Any
    title_field: str
    subtitle_field: str = ""
    title_builder: Callable[[Any], str] | None = None


def _referral_title(item: Any) -> str:
    """内推的展示标题：内推人 · 岗位（缺项时逐段省略）。"""
    parts = [
        str(getattr(item, "referrer_name", "") or "").strip(),
        str(getattr(item, "position", "") or "").strip(),
    ]
    return " · ".join(part for part in parts if part) or "（无标题）"


# 顺序即回收站的展示顺序（越靠前越常用）。
# 前六类来自迁移 0016，中四类来自迁移 0018，后三类来自迁移 0019——**全部含 ``deleted_at`` 列**，
# 缺一类就是"半软删"。
TRASH_SPECS: tuple[TrashSpec, ...] = (
    TrashSpec("job", "岗位", Job, "title", "company"),
    TrashSpec("resume", "简历记录", ResumeRecord, "title", "company"),
    TrashSpec("track", "投递记录", ApplicationTrack, "title", "company"),
    TrashSpec("claim", "事实台账", ClaimRecord, "title", "category"),
    TrashSpec("material", "资料箱材料", Material, "title", "category"),
    TrashSpec("conversation", "助手会话", ChatConversation, "title"),
    TrashSpec("interview_experience", "面经", InterviewExperience, "title", "company"),
    TrashSpec(
        "referral", "内推", Referral, "referrer_name", "company", title_builder=_referral_title
    ),
    TrashSpec("reminder", "提醒", Reminder, "title"),
    TrashSpec("share_package", "分享包", SharePackage, "title"),
    TrashSpec("question_bank_record", "题库历史", QuestionBankRecord, "resume_title", "company"),
    TrashSpec(
        "interview_review_record",
        "复盘历史",
        InterviewReviewRecord,
        "resume_title",
        "company",
    ),
    TrashSpec("knowledge_entry", "知识库", KnowledgeEntry, "title"),
)

TRASH_SPEC_BY_KEY: dict[str, TrashSpec] = {spec.key: spec for spec in TRASH_SPECS}

# 六张表的表名。**由注册表推导**而不是再写一份清单：迁移（``0016``）也要声明"给哪些表加了
# deleted_at"，两处各写一份必然漂移——漂移的后果是某张表有列却没进回收站（删了就直接消失），
# 或者进了回收站却没有列（一删就报错）。有测试把两边对齐。
TRASHED_TABLES: tuple[str, ...] = tuple(spec.model.__tablename__ for spec in TRASH_SPECS)


def spec_or_none(key: str) -> TrashSpec | None:
    return TRASH_SPEC_BY_KEY.get((key or "").strip())


def live_only(model: Any) -> Any:
    """查询条件：只取**未被软删除**的行。

    抽成一个函数是为了让"哪张表用哪个列名"只写一次——六张表各写一遍 ``deleted_at.is_(None)``，
    总有一次会写成 ``is_(True)`` 或漏掉，而那种错**不会报错**，只会让回收站里的东西继续出现在
    列表里（用户以为删除失败）。
    """
    return model.deleted_at.is_(None)


def trash_only(model: Any) -> Any:
    """查询条件：只取**已被软删除**的行。"""
    return model.deleted_at.is_not(None)


def is_deleted(item: Any) -> bool:
    return getattr(item, "deleted_at", None) is not None


def get_live(db: Session, model: Any, item_id: Any) -> Any | None:
    """按 id 取一条内容；**已在回收站里的当作不存在**（返回 None）。

    给"单条读取 / 单条修改"用。``db.get`` 会绕过查询过滤，所以直接用它取单条等于开了一个
    后门：列表里看不到、但知道 id 就能打开甚至继续编辑。P5 已经在 API 层与几个服务访问器上
    堵住了，这里是**同一套语义的共用实现**——写一次，比每个工具各写一遍 ``is_deleted`` 可靠。
    """
    item = db.get(model, item_id)
    if item is None or is_deleted(item):
        return None
    return item


def soft_delete(db: Session, key: str, item: Any) -> None:
    """把一条内容移入回收站（**不 commit**，由调用方决定事务边界）。

    幂等：已经在回收站里的记录不会被刷新删除时间——否则"重复点删除"会让它在回收站里的
    位置不断上浮，看起来像刚删的。
    """
    if getattr(item, "deleted_at", None) is None:
        item.deleted_at = utcnow()
    logger.info("已移入回收站 type=%s id=%s", key, getattr(item, "id", None))


def _brief(spec: TrashSpec, item: Any) -> dict[str, Any]:
    deleted_at = getattr(item, "deleted_at", None)
    subtitle = getattr(item, spec.subtitle_field, "") if spec.subtitle_field else ""
    title = (
        spec.title_builder(item)
        if spec.title_builder is not None
        else str(getattr(item, spec.title_field, "") or "")
    )
    return {
        "type": spec.key,
        "type_label": spec.label,
        "id": item.id,
        "title": title,
        "subtitle": str(subtitle or ""),
        "deleted_at": deleted_at.isoformat() if isinstance(deleted_at, datetime) else None,
    }


def counts(db: Session) -> dict[str, int]:
    """各类内容的回收站条数（界面用它显示"回收站 (3)"这样的角标）。"""
    return {
        spec.key: db.query(spec.model).filter(trash_only(spec.model)).count()
        for spec in TRASH_SPECS
    }


def list_trashed(db: Session, *, key: str = "", limit: int = MAX_TRASH_ITEMS) -> list[dict[str, Any]]:
    """列出回收站内容，**按删除时间倒序**（最近的先看到）。

    ``key`` 留空表示不限类型——界面用一张表混排所有类型，带类型标签与筛选，
    比六个页签更省事也更好找。
    """
    spec = spec_or_none(key)
    specs = (spec,) if spec else TRASH_SPECS
    items: list[dict[str, Any]] = []
    for one in specs:
        rows = (
            db.query(one.model)
            .filter(trash_only(one.model))
            .order_by(one.model.deleted_at.desc())
            .limit(max(1, limit))
            .all()
        )
        items.extend(_brief(one, row) for row in rows)
    items.sort(key=lambda item: item["deleted_at"] or "", reverse=True)
    return items[: max(1, limit)]


def restore(db: Session, key: str, item_id: int) -> bool:
    """把一条内容从回收站恢复（清空时间戳）。找不到返回 False。"""
    spec = spec_or_none(key)
    if spec is None:
        return False
    item = db.get(spec.model, item_id)
    if item is None or not is_deleted(item):
        return False
    item.deleted_at = None
    db.commit()
    logger.info("已从回收站恢复 type=%s id=%s", key, item_id)
    return True


def purge(db: Session, key: str, item_id: int) -> bool:
    """**彻底删除**一条内容（真删，不可恢复）。

    只允许删除**已经在回收站里**的记录：这样"删除"永远先经过可恢复的一步，
    不会出现"点了删除就没了"的路径。找不到或不在回收站里都返回 False。
    """
    spec = spec_or_none(key)
    if spec is None:
        return False
    item = db.get(spec.model, item_id)
    if item is None or not is_deleted(item):
        return False
    db.delete(item)
    db.commit()
    logger.info("已彻底删除 type=%s id=%s", key, item_id)
    return True


def empty(db: Session, *, key: str = "") -> int:
    """清空回收站（``key`` 留空表示全部类型）。返回彻底删除的条数。"""
    spec = spec_or_none(key)
    specs = (spec,) if spec else TRASH_SPECS
    removed = 0
    for one in specs:
        rows = db.query(one.model).filter(trash_only(one.model)).all()
        for row in rows:
            db.delete(row)
            removed += 1
    db.commit()
    logger.info("已清空回收站 type=%s，彻底删除 %s 条", key or "全部", removed)
    return removed


__all__ = [
    "MAX_TRASH_ITEMS",
    "get_live",
    "TRASHED_TABLES",
    "TRASH_SPECS",
    "TRASH_SPEC_BY_KEY",
    "TrashSpec",
    "counts",
    "empty",
    "is_deleted",
    "list_trashed",
    "live_only",
    "purge",
    "restore",
    "soft_delete",
    "spec_or_none",
    "trash_only",
]
