"""日历提醒（R-12）的持久化与检索。

提醒不自己发明时机，只记录用户或流程明确给出的时点。三个绑定对象（漏斗/岗位/简历）
都走 ``SET NULL``：被删对象不连坐，提醒仍保留、只是失去关联。

- 列表与 ``upcoming`` 都按 ``remind_at`` 升序——"接下来要做什么"先看到最近的那条。
- ``upcoming`` 只看 pending，作为"下一步"的轻量日程。
- 删除走软删除（``trash.live_only`` 列表里不再出现），彻底删除在回收站另做。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import trash
from ..models.job import Job
from ..models.profile import utcnow
from ..models.reminder import REMINDER_STATUS_PENDING, Reminder
from ..models.resume import ResumeRecord
from ..models.tracker import ApplicationTrack
from ..schemas.reminder import ReminderCreate, ReminderUpdate, ReminderUpcomingOut

logger = logging.getLogger(__name__)

MAX_REMINDER_LIST = 500

# ===== 首页紧急度（前后端共用一份取值）=====
REMINDER_URGENCY_OVERDUE = "overdue"
REMINDER_URGENCY_SOON = "soon"
REMINDER_URGENCY_UPCOMING = "upcoming"
REMINDER_URGENCY_LATER = "later"
REMINDER_URGENCIES = (
    REMINDER_URGENCY_OVERDUE,
    REMINDER_URGENCY_SOON,
    REMINDER_URGENCY_UPCOMING,
    REMINDER_URGENCY_LATER,
)

# 排序优先级：逾期最靠前，其次 24 小时内，再是 3 天内，最后更远。
_URGENCY_RANK = {
    REMINDER_URGENCY_OVERDUE: 0,
    REMINDER_URGENCY_SOON: 1,
    REMINDER_URGENCY_UPCOMING: 2,
    REMINDER_URGENCY_LATER: 3,
}


def _naive_utc(value: datetime) -> datetime:
    """统一成无时区 UTC，避免带时区与无时区比较抛 TypeError。"""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _due_label(remind_at: datetime, now: datetime) -> str:
    """非逾期提醒的展示标签：今天 / 明天 / N 天后。"""
    days_until = (remind_at.date() - now.date()).days
    if days_until <= 0:
        return "今天"
    if days_until == 1:
        return "明天"
    return f"{days_until} 天后"


def reminder_urgency(remind_at: datetime, now: datetime) -> tuple[str, str]:
    """计算紧急度与展示标签。**紧急度口径只在这里实现一处**。

    口径：overdue=``remind_at < now``；soon≤24h；upcoming≤3 天；later 更远。
    """
    remind_at = _naive_utc(remind_at)
    now = _naive_utc(now)
    delta = remind_at - now
    if delta < timedelta(0):
        days = max(1, (now - remind_at).days)
        return REMINDER_URGENCY_OVERDUE, f"已逾期 {days} 天"
    label = _due_label(remind_at, now)
    if delta <= timedelta(hours=24):
        return REMINDER_URGENCY_SOON, label
    if delta <= timedelta(days=3):
        return REMINDER_URGENCY_UPCOMING, label
    return REMINDER_URGENCY_LATER, label


def reminder_urgency_counts(db: Session, now: datetime | None = None) -> dict[str, int]:
    """待办提醒按紧急度分档计数（含 ``total``）。

    口径**必须**走 :func:`reminder_urgency`——四档阈值只在那里有一份实现，看板再写
    一遍就会与首页的紧急度标签对不上。只统计 ``pending``：已完成/已忽略的提醒不再是
    "接下来要做什么"。用 ``remind_at`` 单列查询，不为一个计数把正文一起读进内存。
    """
    moment = now or utcnow()
    counts: dict[str, int] = {urgency: 0 for urgency in REMINDER_URGENCIES}
    rows = (
        db.query(Reminder.remind_at)
        .filter(trash.live_only(Reminder), Reminder.status == REMINDER_STATUS_PENDING)
        .all()
    )
    for (remind_at,) in rows:
        urgency, _label = reminder_urgency(remind_at, moment)
        counts[urgency] = counts.get(urgency, 0) + 1
    counts["total"] = len(rows)
    return counts


def list_reminders(
    db: Session, *, kind: str = "", status: str = "", limit: int = 200
) -> list[Reminder]:
    """按类型/状态过滤；只取未软删除的行，按提醒时间升序。"""
    query = db.query(Reminder).filter(trash.live_only(Reminder))
    if kind.strip():
        query = query.filter(Reminder.kind == kind.strip())
    if status.strip():
        query = query.filter(Reminder.status == status.strip())
    return (
        query.order_by(Reminder.remind_at.asc(), Reminder.id.asc())
        .limit(max(1, min(limit, MAX_REMINDER_LIST)))
        .all()
    )


def upcoming_reminders(db: Session, *, limit: int = 50) -> list[Reminder]:
    """待办提醒：只返回 pending，按提醒时间升序。"""
    return (
        db.query(Reminder)
        .filter(trash.live_only(Reminder), Reminder.status == REMINDER_STATUS_PENDING)
        .order_by(Reminder.remind_at.asc(), Reminder.id.asc())
        .limit(max(1, min(limit, MAX_REMINDER_LIST)))
        .all()
    )


def upcoming_reminder_out(reminder: Reminder, now: datetime) -> ReminderUpcomingOut:
    """把一条待办提醒转成首页回显结构，补上紧急度与展示标签。"""
    out = ReminderUpcomingOut.model_validate(reminder)
    out.urgency, out.due_label = reminder_urgency(reminder.remind_at, now)
    return out


def upcoming_reminders_out(db: Session, *, limit: int = 50) -> list[ReminderUpcomingOut]:
    """待办提醒的首页回显：只返回 pending，按紧急度+时间升序。"""
    rows = upcoming_reminders(db, limit=limit)
    now = utcnow()
    items = [upcoming_reminder_out(row, now) for row in rows]
    items.sort(key=lambda item: (_URGENCY_RANK[item.urgency], item.remind_at, item.id))
    return items


def reminder_or_none(db: Session, reminder_id: int) -> Reminder | None:
    """取一条提醒；已在回收站里的当作不存在。"""
    return trash.get_live(db, Reminder, reminder_id)


def _resolve_bindings(db: Session, values: dict) -> dict:
    """校验三个绑定对象：不存在或已软删则置空（SET NULL 语义）。"""
    if values.get("track_id") is not None:
        if trash.get_live(db, ApplicationTrack, values["track_id"]) is None:
            values["track_id"] = None
    if values.get("job_id") is not None:
        if trash.get_live(db, Job, values["job_id"]) is None:
            values["job_id"] = None
    if values.get("resume_id") is not None:
        if trash.get_live(db, ResumeRecord, values["resume_id"]) is None:
            values["resume_id"] = None
    return values


def create_reminder(db: Session, payload: ReminderCreate) -> Reminder:
    """新增一条提醒。"""
    reminder = Reminder(**_resolve_bindings(db, payload.model_dump()))
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    logger.info("已新增提醒 id=%s kind=%s", reminder.id, reminder.kind)
    return reminder


def update_reminder(db: Session, reminder: Reminder, payload: ReminderUpdate) -> Reminder:
    """PATCH：只覆盖显式给出的字段，绑定对象同样做 SET NULL 校验。"""
    values = _resolve_bindings(db, payload.model_dump(exclude_unset=True))
    for field, value in values.items():
        setattr(reminder, field, value)
    db.commit()
    db.refresh(reminder)
    return reminder


def delete_reminder(db: Session, reminder_id: int) -> bool:
    """移入回收站（软删除）；彻底删除在「回收站」里单独提供。"""
    reminder = db.get(Reminder, reminder_id)
    if reminder is None or trash.is_deleted(reminder):
        return False
    trash.soft_delete(db, "reminder", reminder)
    db.commit()
    return True


__all__ = [
    "MAX_REMINDER_LIST",
    "REMINDER_URGENCIES",
    "REMINDER_URGENCY_LATER",
    "REMINDER_URGENCY_OVERDUE",
    "REMINDER_URGENCY_SOON",
    "REMINDER_URGENCY_UPCOMING",
    "create_reminder",
    "delete_reminder",
    "list_reminders",
    "reminder_or_none",
    "reminder_urgency",
    "reminder_urgency_counts",
    "upcoming_reminder_out",
    "upcoming_reminders",
    "upcoming_reminders_out",
    "update_reminder",
]

