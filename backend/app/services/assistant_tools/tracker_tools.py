"""求职进度的查询与安全写入工具。

进度记录属于用户明确维护的数据：助手可以在用户要求时新增或修改，但不提供删除工具；
删除仍由用户在「求职进度」或「回收站」页面完成。
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ...models.tracker import STATUSES, ApplicationTrack, status_label
from ...schemas.tracker import TrackCreate, TrackUpdate
from ..tracker import create_track, list_tracks, track_or_none, update_track
from ._shared import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT
from ._types import ToolResult

_TRACK_FIELDS = {
    "company",
    "title",
    "status",
    "stage_note",
    "applied_at",
    "status_date",
    "next_action",
    "next_action_date",
    "note",
    "evidence",
    "job_id",
    "resume_id",
}


def _track_brief(record: ApplicationTrack) -> dict:
    return {
        "id": record.id,
        "company": record.company,
        "title": record.title,
        "status": record.status,
        "status_label": status_label(record.status),
        "stage_note": record.stage_note,
        "applied_at": record.applied_at,
        "status_date": record.status_date,
        "next_action": record.next_action,
        "next_action_date": record.next_action_date,
        "note": record.note,
        "evidence": record.evidence,
        "job_id": record.job_id,
        "resume_id": record.resume_id,
        "source": record.source,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _track_or_error(db: Session, arguments: dict) -> ApplicationTrack:
    try:
        track_id = int(arguments.get("track_id"))
    except (TypeError, ValueError):
        raise ValueError("需要提供求职进度 id（可以先用 list_application_tracks 查）") from None
    record = track_or_none(db, track_id)
    if record is None:
        raise ValueError(f"求职进度 {track_id} 不存在")
    return record


def _tool_list_application_tracks(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    status = str(arguments.get("status") or "").strip()
    if status and status not in STATUSES:
        raise ValueError(f"未知的进度状态「{status}」")
    records = list_tracks(
        db,
        status=status,
        keyword=str(arguments.get("keyword") or "").strip(),
    )
    shown = records[:limit]
    payload = {
        "总数": len(records),
        "返回": len(shown),
        "求职进度": [_track_brief(item) for item in shown],
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了 {len(shown)} 条求职进度",
        link="/tracker",
    )


def _tool_get_application_track(db: Session, arguments: dict) -> ToolResult:
    record = _track_or_error(db, arguments)
    return ToolResult(
        text=json.dumps(_track_brief(record), ensure_ascii=False),
        summary=f"读取了「{record.company} · {record.title}」的求职进度",
        link="/tracker",
    )


def _track_payload(arguments: dict, existing: ApplicationTrack | None = None) -> dict:
    current = _track_brief(existing) if existing is not None else {}
    current.update({key: value for key, value in arguments.items() if key in _TRACK_FIELDS})
    payload = {key: current.get(key, "") for key in _TRACK_FIELDS}
    # Optional foreign keys must stay ``None``; an empty string would fail Pydantic's integer
    # validation even though it is the natural default for the text fields.
    payload["job_id"] = current.get("job_id")
    payload["resume_id"] = current.get("resume_id")
    return payload


def _tool_create_application_track(db: Session, arguments: dict) -> ToolResult:
    payload = TrackCreate.model_validate(_track_payload(arguments))
    record = create_track(db, payload)
    return ToolResult(
        text=json.dumps(_track_brief(record), ensure_ascii=False),
        summary=f"新增了「{record.company} · {record.title}」的求职进度",
        link="/tracker",
        changed=True,
    )


def _tool_update_application_track(db: Session, arguments: dict) -> ToolResult:
    record = _track_or_error(db, arguments)
    if not any(key in arguments for key in _TRACK_FIELDS):
        raise ValueError("没有给出要修改的进度字段")
    payload = TrackUpdate.model_validate(_track_payload(arguments, record))
    updated = update_track(db, record, payload)
    changed = sorted(key for key in _TRACK_FIELDS if key in arguments)
    return ToolResult(
        text=json.dumps({"id": updated.id, "updated": changed, **_track_brief(updated)}, ensure_ascii=False),
        summary=f"更新了「{updated.company} · {updated.title}」的求职进度",
        link="/tracker",
        changed=True,
    )


__all__ = [
    "_tool_create_application_track",
    "_tool_get_application_track",
    "_tool_list_application_tracks",
    "_tool_update_application_track",
]
