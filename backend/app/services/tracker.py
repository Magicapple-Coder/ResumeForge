"""求职进度的服务层：合并、增删改查、漏斗统计与导出。

**合并是这里唯一有判断的地方，所以只写了一遍**：:func:`plan_merges` 算出"每条会新增
还是更新、为什么"，预览接口把它原样返回，确认接口再执行同一份计划。两处各写一遍判断
是这类功能最容易出的错——预览说"会更新"，点了确认却没更新（或反过来），用户再也不会
相信那个预览。

状态取舍规则见 ``models/tracker.py`` 的 :func:`resolve_status`：只能前进，拒信除外。
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from . import trash
from ..models.tracker import (
    MERGE_CREATED,
    MERGE_LABELS,
    MERGE_UNCHANGED,
    MERGE_UPDATED,
    SOURCE_APPLY,
    SOURCE_MANUAL,
    STATUSES,
    STATUS_APPLIED,
    STATUS_OFFER,
    STATUS_REJECTED,
    ApplicationTrack,
    is_active,
    normalize_key,
    resolve_status,
    status_label,
)
from ..schemas.tracker import (
    TrackApplyItemResult,
    TrackApplyOut,
    TrackCreate,
    TrackMergePreview,
    TrackOut,
    TrackRecordIn,
    TrackUpdate,
)

logger = logging.getLogger(__name__)

MAX_LIST_LIMIT = 500


# ===== 读取 =====


def track_or_none(db: Session, track_id: int) -> ApplicationTrack | None:
    """取一条投递记录；**已在回收站里的当作不存在**（见 ``claim_or_none`` 的说明）。"""
    record = db.get(ApplicationTrack, track_id)
    if record is None or trash.is_deleted(record):
        return None
    return record


def list_tracks(db: Session, *, status: str = "", keyword: str = "") -> list[ApplicationTrack]:
    """按状态 / 关键词检索。

    默认排序刻意是"进行中的排在前面、越靠后的阶段越靠前"：用户打开这一页最想先看到的是
    还在推进的那几家，而不是三个月前就结束了的。
    """
    query = db.query(ApplicationTrack).filter(trash.live_only(ApplicationTrack))
    if status:
        query = query.filter(ApplicationTrack.status == status)
    target = (keyword or "").strip()
    if target:
        like = f"%{target}%"
        query = query.filter(
            ApplicationTrack.company.like(like)
            | ApplicationTrack.title.like(like)
            | ApplicationTrack.note.like(like)
            | ApplicationTrack.next_action.like(like)
        )
    records = query.all()
    return sorted(records, key=_sort_key)


_STATUS_ORDER = {
    "interview": 0,
    "offer": 1,
    "assessment": 2,
    "screening": 3,
    "applied": 4,
    # 终态排最后：结束了的不该占着视线，但也不能藏起来（复盘要看）。
    "rejected": 5,
    "unknown": 6,
}


def _sort_key(record: ApplicationTrack) -> tuple:
    """先按阶段、再按最近更新倒序。

    第二项取负的时间戳不能用 ``-timestamp``（datetime 不支持取负），所以用
    ``datetime.max`` 减它得到"越小越新"的等效键。
    """
    from datetime import datetime

    updated = record.updated_at or datetime.min
    return (
        _STATUS_ORDER.get(record.status, 9),
        datetime.max - updated,
        -record.id,
    )


def summarize(records: list[ApplicationTrack]) -> dict[str, Any]:
    """列表接口的统计部分：漏斗各阶段计数 + 几个一眼要看到的数字。"""
    counts = {status: 0 for status in STATUSES}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
    # 「本月投递」按**用户本地的自然月**算：applied_at 是用户自己填的日期，
    # 拿 UTC 去比会让月初的头八个小时落在上个月里，和用户看到的日历对不上。
    month_prefix = date.today().strftime("%Y-%m")
    return {
        "total": len(records),
        "status_counts": counts,
        "active_count": sum(1 for item in records if is_active(item.status)),
        "offer_count": counts.get(STATUS_OFFER, 0),
        "rejected_count": counts.get(STATUS_REJECTED, 0),
        "month_count": sum(
            1 for item in records if (item.applied_at or "").startswith(month_prefix)
        ),
    }


# ===== 写入 =====


def _apply_payload(record: ApplicationTrack, payload: TrackCreate | TrackUpdate) -> None:
    record.company = payload.company
    record.title = payload.title
    record.company_key = normalize_key(payload.company)
    record.title_key = normalize_key(payload.title)
    record.status = payload.status
    record.stage_note = payload.stage_note
    # **这里刻意没有"默认今天"**：手工录入不可能知道投递日期（可能投递当天录，也可能
    # 三周后照着一封通知补录），替他填今天会把记录钉在错误的月份上，在投递趋势里造出
    # 一个从未发生过的尖峰。投递台的 :func:`record_applied` 默认今天是对的——那条路径
    # 叫"刚投出去"，日期是确知的。两条路径的差异是正当的，别顺手"统一"掉。
    # 表单那一侧用一键「填今天」降低留空的摩擦（见 TrackFormModal）。
    record.applied_at = payload.applied_at
    record.status_date = payload.status_date
    record.next_action = payload.next_action
    record.next_action_date = payload.next_action_date
    record.note = payload.note
    record.evidence = payload.evidence
    record.job_id = payload.job_id
    record.resume_id = payload.resume_id


def create_track(db: Session, payload: TrackCreate, *, source: str = SOURCE_MANUAL) -> ApplicationTrack:
    record = ApplicationTrack(source=source)
    _apply_payload(record, payload)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_track(db: Session, record: ApplicationTrack, payload: TrackUpdate) -> ApplicationTrack:
    _apply_payload(record, payload)
    db.commit()
    db.refresh(record)
    return record


def delete_track(db: Session, track_id: int) -> bool:
    """移入回收站（软删除）。

    **不再真删**：投递记录是用户一条条维护起来的（进度、下次动作、备注），误删的代价远大于
    多留一行。彻底删除在「回收站」里单独提供，且必须二次确认。
    """
    record = db.get(ApplicationTrack, track_id)
    if record is None or trash.is_deleted(record):
        return False
    trash.soft_delete(db, "track", record)
    db.commit()
    return True


# ===== 合并 =====


def _find_by_key(db: Session, record: TrackRecordIn) -> ApplicationTrack | None:
    return (
        db.query(ApplicationTrack)
        .filter(
            ApplicationTrack.company_key == normalize_key(record.company),
            ApplicationTrack.title_key == normalize_key(record.title),
        )
        .one_or_none()
    )


class _Plan:
    """一条记录的处理计划：预览与确认执行的是同一份。"""

    def __init__(
        self,
        record: TrackRecordIn,
        action: str,
        reason: str,
        existing: ApplicationTrack | None,
        current_status: str,
    ) -> None:
        self.record = record
        self.action = action
        self.reason = reason
        self.existing = existing
        self.current_status = current_status


def _fold_batch(records: list[TrackRecordIn]) -> list[tuple[TrackRecordIn, int]]:
    """按合并键折叠同一批里的多条通知，返回 ``(代表记录, 合并了几条)`` 并保序。

    一次粘贴一整段邮箱记录时，同一个岗位往往连着出现好几封（已投递 → 筛选 → 面试）。
    不折叠的话，后一条会相对前一条（还没落库的那条）判成"更新"，而库里的原记录并不
    存在——计划里的"更新"找不到可更新的对象。

    折叠时以**进展最靠后的那条**为代表，其余字段也取它的：这条记录表达的是"目前到哪
    一步了"，就该用走到最远的那封通知里的下一步和备注。
    """
    order: list[tuple[str, str]] = []
    folded: dict[tuple[str, str], TrackRecordIn] = {}
    counts: dict[tuple[str, str], int] = {}

    for record in records:
        key = (normalize_key(record.company), normalize_key(record.title))
        current = folded.get(key)
        if current is None:
            order.append(key)
            folded[key] = record
            counts[key] = 1
            continue
        counts[key] += 1
        if resolve_status(current.status, record.status) == record.status:
            folded[key] = record

    return [(folded[key], counts[key]) for key in order]


def plan_merges(db: Session, records: list[TrackRecordIn]) -> list[_Plan]:
    """算出每条记录会新增还是更新，并给出面向用户的原因。**不写库。**"""
    plans: list[_Plan] = []

    for record, folded_count in _fold_batch(records):
        existing = _find_by_key(db, record)
        merged_note = f"（本次识别有 {folded_count} 条通知指向这个岗位，已按进展合并）"

        if existing is None:
            plans.append(
                _Plan(
                    record,
                    MERGE_CREATED,
                    f"新增「{record.company} · {record.title}」"
                    + (merged_note if folded_count > 1 else ""),
                    None,
                    "",
                )
            )
            continue

        resolved = resolve_status(existing.status, record.status)
        if resolved == existing.status:
            reason = (
                f"已有记录处于「{status_label(existing.status)}」，这条通知更早，保留现有进度"
                if record.status != existing.status
                else f"状态本来就是「{status_label(existing.status)}」，没有新变化"
            )
            plans.append(_Plan(record, MERGE_UNCHANGED, reason, existing, existing.status))
            continue

        plans.append(
            _Plan(
                record,
                MERGE_UPDATED,
                f"「{status_label(existing.status)}」推进为「{status_label(resolved)}」"
                + (merged_note if folded_count > 1 else ""),
                existing,
                existing.status,
            )
        )

    return plans


def _merge_into(record: ApplicationTrack, incoming: TrackRecordIn) -> None:
    """把一条通知合并进已有记录。

    只覆盖这次通知确实带来的字段，不清空用户自己填过的东西：一封只写了"进入面试"的邮件
    不该把用户记的下一步或备注抹掉。
    """
    record.status = resolve_status(record.status, incoming.status)
    if incoming.stage_note:
        record.stage_note = incoming.stage_note
    if incoming.status_date:
        record.status_date = incoming.status_date
    if incoming.applied_at and not record.applied_at:
        record.applied_at = incoming.applied_at
    if incoming.next_action:
        record.next_action = incoming.next_action
        record.next_action_date = incoming.next_action_date
    if incoming.note:
        # 备注是追加而不是替换：一条通知里的一句话不该让之前的备注消失。
        merged = f"{record.note}\n{incoming.note}".strip() if record.note else incoming.note
        record.note = merged[:4_000]
    if incoming.evidence:
        record.evidence = incoming.evidence[:500]


def apply_merges(
    db: Session, records: list[TrackRecordIn], *, source: str = "recognized"
) -> TrackApplyOut:
    """执行合并计划；预览说什么，这里就做什么。"""
    plans = plan_merges(db, records)
    items: list[TrackApplyItemResult] = []
    created = updated = unchanged = 0

    for plan in plans:
        if plan.action == MERGE_CREATED:
            created_record = ApplicationTrack(source=source)
            _apply_payload(
                created_record,
                TrackCreate(**plan.record.model_dump(), job_id=None, resume_id=None),
            )
            db.add(created_record)
            created += 1
            status = plan.record.status
        elif plan.action == MERGE_UPDATED:
            assert plan.existing is not None  # 计划里说更新，就一定找得到原记录
            _merge_into(plan.existing, plan.record)
            updated += 1
            status = plan.existing.status
        else:
            # 未改变也要把来源摘录留下来：用户可能正是为了留下这封通知的原文才导入的。
            if plan.existing is not None and plan.record.evidence:
                plan.existing.evidence = plan.record.evidence[:500]
            unchanged += 1
            status = plan.current_status
        items.append(
            TrackApplyItemResult(
                company=plan.record.company,
                title=plan.record.title,
                action=MERGE_LABELS.get(plan.action, plan.action),
                status=status,
                reason=plan.reason,
            )
        )

    db.commit()
    return TrackApplyOut(items=items, created=created, updated=updated, unchanged=unchanged)


def preview_merges(db: Session, records: list[TrackRecordIn]) -> list[TrackMergePreview]:
    return [
        TrackMergePreview(
            record=plan.record,
            action=plan.action,
            reason=plan.reason,
            current_status=plan.current_status,
        )
        for plan in plan_merges(db, records)
    ]


# ===== 与投递台的接合点 =====


def record_applied(
    db: Session, *, company: str, title: str, applied_on: str = "", job_id: int | None = None
) -> None:
    """投递成功后落一条「已投递」。

    刻意**不**覆盖已有记录的更靠后状态：用户可能已经手动把这家推到「面试」了，
    而投递台的批量任务又跑了一次同一个岗位——那时把状态打回「已投递」是错的。
    """
    if not company.strip() or not title.strip():
        # 快照字段为空时无从合并，宁可不记也不要造一条"(空) · (空)"。
        return
    payload = TrackRecordIn(
        company=company,
        title=title,
        status=STATUS_APPLIED,
        applied_at=applied_on or date.today().isoformat(),
    )
    existing = _find_by_key(db, payload)
    if existing is None:
        record = ApplicationTrack(source=SOURCE_APPLY)
        _apply_payload(
            record, TrackCreate(**payload.model_dump(), job_id=job_id, resume_id=None)
        )
        db.add(record)
        return
    if not existing.applied_at:
        existing.applied_at = payload.applied_at
    if existing.job_id is None and job_id is not None:
        existing.job_id = job_id
    # 状态交给 resolve_status：已经在面试的不会被这一次投递拉回「已投递」。


# ===== 导出 =====


_CSV_HEADER = (
    "公司",
    "岗位",
    "状态",
    "阶段说明",
    "投递日期",
    "状态日期",
    "下一步",
    "下一步日期",
    "备注",
)


def export_rows(records: list[ApplicationTrack]) -> list[list[str]]:
    return [
        [
            item.company,
            item.title,
            status_label(item.status),
            item.stage_note,
            item.applied_at,
            item.status_date,
            item.next_action,
            item.next_action_date,
            item.note.replace("\n", " "),
        ]
        for item in records
    ]


def to_csv(records: list[ApplicationTrack]) -> str:
    """导出 CSV。

    ``\\ufeff`` 是 BOM：Excel 打开不带 BOM 的 UTF-8 CSV 会把中文显示成乱码，
    而这份文件最常见的用途恰恰是用 Excel 打开看看。
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_HEADER)
    writer.writerows(export_rows(records))
    return "﻿" + buffer.getvalue()


def to_json(records: list[ApplicationTrack]) -> str:
    payload = {
        "说明": "求职进度导出；状态取值与合并规则见 models/tracker.py",
        "总数": len(records),
        "记录": [
            {
                "公司": item.company,
                "岗位": item.title,
                "状态": status_label(item.status),
                "阶段说明": item.stage_note,
                "投递日期": item.applied_at,
                "状态日期": item.status_date,
                "下一步": item.next_action,
                "下一步日期": item.next_action_date,
                "备注": item.note,
                "来源": item.source,
            }
            for item in records
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def track_out(record: ApplicationTrack) -> TrackOut:
    return TrackOut.model_validate(record)


__all__ = [
    "MAX_LIST_LIMIT",
    "apply_merges",
    "create_track",
    "delete_track",
    "export_rows",
    "list_tracks",
    "plan_merges",
    "preview_merges",
    "record_applied",
    "summarize",
    "to_csv",
    "to_json",
    "track_or_none",
    "track_out",
    "update_track",
]
