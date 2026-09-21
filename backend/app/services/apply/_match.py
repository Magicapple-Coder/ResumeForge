"""匹配结论的读取、准入判断与持久化。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ...models.apply import (
    ADMISSION_BLOCK,
    ADMISSION_NEEDS_CONFIRM,
    ADMISSIONS,
    HARD_GATE_UNMET,
    JobMatchAnalysis,
)
from ...models.job import Job
from ...models.profile import utcnow
from ...schemas.job_match import JobMatchResult
from ..job.job_match import match_requires_confirmation
def latest_match(db: Session, job_id: int | None) -> JobMatchAnalysis | None:
    """取某岗位最近一次匹配结论。"""
    if job_id is None:
        return None
    return (
        db.query(JobMatchAnalysis)
        .filter(JobMatchAnalysis.job_id == job_id)
        .one_or_none()
    )


def _admission_of_match(match: JobMatchAnalysis) -> str | None:
    result = match.result if isinstance(match.result, dict) else {}
    admission = result.get("admission")
    if admission in ADMISSIONS:
        return admission
    # 结果里没有可用 admission 时，退回按硬门槛/需确认字段推断（保守）。
    if match.hard_gate == HARD_GATE_UNMET:
        return ADMISSION_BLOCK
    if match.requires_confirm:
        return ADMISSION_NEEDS_CONFIRM
    # 读不出可用结论（空结果 / 未知取值 / hard_gate=unknown 且无标记）时返回 None。
    # **不要在这里兜底成 ADMISSION_ALLOW**：准入是安全闸门，未知方向必须是"需确认"，
    # 由 `_match_requires_confirm` 统一按需确认处理，绝不默认放行。
    return None


def _match_requires_confirm(match: JobMatchAnalysis) -> bool:
    """该岗位的匹配结论是否要求用户逐条确认（队列与展示共用同一判定）。

    保守规则：只要准入结论是「需确认」，或行上标记了 ``requires_confirm``，**或根本读不出
    可用结论**（``_admission_of_match`` 返回 ``None``），都必须逐条确认。最后一条是纵深防御——
    正常链路 ``persist_match`` 经 ``finalize_match_result`` 必然写合法值，但准入是安全闸门，
    任何一次回归或历史脏数据出现空结论时都不应被当成 ALLOWED 放行自动投递。
    """
    admission = _admission_of_match(match)
    return (
        admission is None
        or admission == ADMISSION_NEEDS_CONFIRM
        or bool(match.requires_confirm)
    )


def _blocking_gaps(result: dict[str, Any]) -> list[str]:
    """列出命中"真实缺口"的条件标签，供二次确认时展示缺口项。"""
    gaps: list[str] = []
    for section in ("hard_conditions", "core_abilities", "bonus_items"):
        items = result.get(section) if isinstance(result, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("status") == "real_gap":
                label = str(item.get("label", "")).strip()
                if label:
                    gaps.append(label)
    return gaps

def persist_match(
    db: Session, job: Job, result: JobMatchResult, *, model: str = ""
) -> JobMatchAnalysis:
    """写入/覆盖某岗位最近一次匹配结论（job_id 唯一）。"""
    requires_confirm = match_requires_confirmation(result)
    row = (
        db.query(JobMatchAnalysis)
        .filter(JobMatchAnalysis.job_id == job.id)
        .one_or_none()
    )
    payload = result.model_dump()
    if row is None:
        row = JobMatchAnalysis(
            job_id=job.id,
            job_title=job.title,
            company=job.company,
            result=payload,
            hard_gate=result.hard_gate,
            requires_confirm=requires_confirm,
            model=model,
        )
        db.add(row)
    else:
        row.job_title = job.title
        row.company = job.company
        row.result = payload
        row.hard_gate = result.hard_gate
        row.requires_confirm = requires_confirm
        row.model = model
        row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return row


def delete_match(db: Session, job_id: int) -> None:
    row = latest_match(db, job_id)
    if row is not None:
        db.delete(row)
        db.commit()

