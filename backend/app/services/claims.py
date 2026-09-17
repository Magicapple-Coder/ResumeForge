"""事实台账的服务层：增删改查、改进建议、以及给生成链路用的事实基线。

三件事在这里收口：

- **CRUD**：只做存取与排序，不做判断。
- **改进建议**（:func:`claim_warnings`）：把"这样写会在面试里出问题"的规则集中在一处，
  由接口随条目一起下发。它是**建议不是拦截**——硬拦会让用户放弃维护台账，反而拿不到
  这套规则的好处；唯一被硬拦的是"已确认却带占位符"那种自相矛盾（在 schema 里挡）。
- **事实基线**（:func:`build_baseline`）：生成简历时注入的已确认事实，以及必须避开
  的未确认说法。台账为空时返回空基线，整条生成链路的行为与以前完全一致。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from ..models.claim import (
    CLAIM_CATEGORIES,
    RESPONSIBILITY_PARTICIPATED,
    STRONG_RESPONSIBILITY_LEVELS,
    VERIFICATION_CONFIRMED,
    VERIFICATION_EXPIRED,
    VERIFICATION_PENDING,
    VERIFICATION_REJECTED,
    ClaimRecord,
    can_enter_final,
    has_placeholder,
    verification_label,
)
from ..schemas.claim import ClaimCreate, ClaimDigestOut, ClaimOut, ClaimUpdate

logger = logging.getLogger(__name__)

MAX_BASELINE_CHARS = 12_000
# 助手读取单条台账时的返回上限：它的长文本是给模型看追问依据用的，
# 不是让它把整条主张原文复述给用户。
MAX_CLAIM_TOOL_CHARS = 6_000
# 表述强度检查：这些词把一条经历的"份量"抬高，如果承担程度只是"参与"，两者不一致
# 会在面试里第一个被追问。只在候选表述里找，不去猜原始事实的口气。
_STRONG_WORDING_MARKERS = (
    "主导",
    "独立完成",
    "从 0 到 1",
    "从0到1",
    "从零到一",
    "牵头",
    "架构设计",
    "负责人",
    "owner",
    "显著提升",
    "大幅提升",
)


def claim_or_none(db: Session, claim_id: int) -> ClaimRecord | None:
    return db.get(ClaimRecord, claim_id)


def list_claims(
    db: Session,
    *,
    category: str = "",
    status: str = "",
    keyword: str = "",
) -> list[ClaimRecord]:
    """按分类 / 核实状态 / 关键词检索；默认按最近更新排序。"""
    query = db.query(ClaimRecord)
    if category:
        query = query.filter(ClaimRecord.category == category)
    if status:
        query = query.filter(ClaimRecord.verification_status == status)
    target = (keyword or "").strip()
    if target:
        like = f"%{target}%"
        query = query.filter(
            ClaimRecord.title.like(like)
            | ClaimRecord.subject.like(like)
            | ClaimRecord.source_fact.like(like)
            | ClaimRecord.candidate_wording.like(like)
        )
    return query.order_by(ClaimRecord.updated_at.desc(), ClaimRecord.id.desc()).all()


def _apply_payload(record: ClaimRecord, payload: ClaimCreate | ClaimUpdate) -> None:
    record.title = payload.title.strip() or payload.subject.strip()
    record.category = payload.category
    record.subject = payload.subject.strip()
    record.source_fact = payload.source_fact
    record.candidate_wording = payload.candidate_wording
    record.sources = [item.model_dump() for item in payload.sources]
    record.responsibility_level = payload.responsibility_level
    record.verification_status = payload.verification_status
    record.allowed_uses = list(payload.allowed_uses)
    record.interview_details = dict(payload.interview_details)
    record.boundary = payload.boundary
    record.risk_notes = list(payload.risk_notes)
    record.last_verified = payload.last_verified


def create_claim(db: Session, payload: ClaimCreate) -> ClaimRecord:
    record = ClaimRecord()
    _apply_payload(record, payload)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_claim(db: Session, record: ClaimRecord, payload: ClaimUpdate) -> ClaimRecord:
    _apply_payload(record, payload)
    db.commit()
    db.refresh(record)
    return record


def delete_claim(db: Session, claim_id: int) -> bool:
    record = db.get(ClaimRecord, claim_id)
    if record is None:
        return False
    db.delete(record)
    db.commit()
    return True


def _has_interview_details(details: dict[str, Any] | None) -> bool:
    if not details:
        return False
    if str(details.get("result") or "").strip():
        return True
    return any(
        isinstance(details.get(key), list) and details[key]
        for key in ("decisions", "difficulties", "verification")
    )


def _wording_strength_conflict(record: ClaimRecord) -> bool:
    wording = (record.candidate_wording or "").casefold()
    if not wording:
        return False
    if not any(marker.casefold() in wording for marker in _STRONG_WORDING_MARKERS):
        return False
    return record.responsibility_level == RESPONSIBILITY_PARTICIPATED


def claim_warnings(record: ClaimRecord) -> list[str]:
    """把"这样写会在面试里出问题"的规则集中在这里。返回面向用户的中文建议。"""
    warnings: list[str] = []
    status = record.verification_status

    if record.responsibility_level in STRONG_RESPONSIBILITY_LEVELS and not _has_interview_details(
        record.interview_details
    ):
        warnings.append(
            f"承担程度是「{record.responsibility_level}」，这类强主张面试时一定会被追问；"
            "建议补上当时的决策、难点、怎么验证和结果"
        )
    if status == VERIFICATION_CONFIRMED and not (record.boundary or "").strip():
        warnings.append(
            "这条会进入正式简历，但没写个人边界；"
            "建议写清团队做了什么、你做了什么，避免把团队成果说成个人成果"
        )
    if status == VERIFICATION_CONFIRMED and not record.sources:
        warnings.append("已确认但没有留下证据来源，之后需要复核时将无从回溯")
    if status == VERIFICATION_PENDING and (record.candidate_wording or "").strip():
        if not has_placeholder(record.candidate_wording):
            warnings.append(
                "待确认的表述没有加【待补】占位符；"
                "导出终稿时会因为看不出它还没核实而被误用"
            )
    if status == VERIFICATION_EXPIRED:
        warnings.append("这条已标记为过期，使用前请更新内容并重新核实")
    if status == VERIFICATION_REJECTED and (record.candidate_wording or "").strip():
        warnings.append("已标记为不采用，生成简历时会显式避开这条表述")
    if _wording_strength_conflict(record):
        warnings.append(
            "表述里出现了「主导 / 独立完成 / 负责」这类强措辞，"
            "但承担程度填的是「参与」——两者不一致，面试时容易被问穿"
        )
    return warnings


def claim_out(record: ClaimRecord) -> ClaimOut:
    """ORM 记录 → 对外结构，并附上服务端算出的改进建议。"""
    payload = ClaimOut.model_validate(record)
    payload.warnings = claim_warnings(record)
    return payload


def summarize(records: list[ClaimRecord]) -> dict[str, Any]:
    """列表接口的汇总部分：各状态计数与各分类计数。"""
    category_counts = {category: 0 for category in CLAIM_CATEGORIES}
    confirmed = 0
    pending = 0
    for record in records:
        category_counts[record.category] = category_counts.get(record.category, 0) + 1
        if record.verification_status == VERIFICATION_CONFIRMED:
            confirmed += 1
        elif record.verification_status == VERIFICATION_PENDING:
            pending += 1
    return {
        "total": len(records),
        "confirmed_count": confirmed,
        "pending_count": pending,
        "category_counts": category_counts,
    }


def claim_brief(record: ClaimRecord) -> dict[str, Any]:
    """列表视图：够判断"这是不是用户说的那一条"，不铺开长文本占满助手上下文。"""
    return {
        "id": record.id,
        "标题": record.title,
        "分类": record.category,
        "主体": record.subject,
        "核实状态": record.verification_status,
        "承担程度": record.responsibility_level,
        "原始事实": (record.source_fact or "")[:200],
        "简历表述": (record.candidate_wording or "")[:200],
    }


def claim_detail_text(record: ClaimRecord, max_chars: int = MAX_CLAIM_TOOL_CHARS) -> str:
    """单条完整内容，含只有被追问时才用得上的面试细节与个人边界。"""
    payload = {
        "id": record.id,
        "标题": record.title,
        "分类": record.category,
        "主体": record.subject,
        "核实状态": record.verification_status,
        "承担程度": record.responsibility_level,
        "原始事实": record.source_fact,
        "简历表述": record.candidate_wording,
        "个人边界": record.boundary,
        "证据来源": record.sources,
        "可用范围": record.allowed_uses,
        "面试细节": record.interview_details,
        "风险备注": record.risk_notes,
        "最近核实": record.last_verified,
        "待改进": claim_warnings(record),
    }
    return json.dumps(payload, ensure_ascii=False)[:max_chars]


def build_baseline(db: Session) -> ClaimDigestOut:
    """构造生成简历用的事实基线。

    只有 ``已确认`` 的条目会作为事实进入提示词；其余状态的候选表述会被列进
    ``blocked_wording``，生成时要求模型避开。台账为空时返回空基线——这样没启用
    台账的用户，生成行为与以前一字不差。
    """
    records = db.query(ClaimRecord).order_by(ClaimRecord.id.asc()).all()
    if not records:
        return ClaimDigestOut(confirmed_count=0, baseline_text="")

    confirmed_lines: list[str] = []
    blocked: list[str] = []
    warnings: list[str] = []
    for record in records:
        if can_enter_final(record.verification_status):
            entry = {
                "subject": record.subject or record.title,
                "category": record.category,
                "fact": record.source_fact,
                "responsibility": record.responsibility_level,
                "boundary": record.boundary,
                "allowed_uses": record.allowed_uses,
            }
            confirmed_lines.append(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
        else:
            wording = (record.candidate_wording or "").strip()
            if wording:
                blocked.append(wording[:500])
            warnings.append(
                f"「{record.title or record.subject or f'#{record.id}'}」"
                f"{verification_label(record.verification_status)}"
            )

    baseline_text = "\n".join(confirmed_lines)[:MAX_BASELINE_CHARS]
    return ClaimDigestOut(
        confirmed_count=len(confirmed_lines),
        baseline_text=baseline_text,
        blocked_wording=blocked[:50],
        warnings=warnings[:50],
    )


__all__ = [
    "MAX_CLAIM_TOOL_CHARS",
    "build_baseline",
    "claim_brief",
    "claim_detail_text",
    "claim_or_none",
    "claim_out",
    "claim_warnings",
    "create_claim",
    "delete_claim",
    "list_claims",
    "summarize",
    "update_claim",
]
