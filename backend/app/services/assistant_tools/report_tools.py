"""模拟面试 / 简历版式，以及只读检索类的提醒 / 内推 / 面经 / 题库 / 复盘 / 知识库 / 统计 / 分享包工具。"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from ...models.interview import InterviewSession
from ...models.resume import ResumeRecord
from ...schemas.knowledge import KnowledgeCreate, KnowledgeUpdate
from ...schemas.reminder import ReminderCreate
from ...schemas.resume import MAX_RESUME_PAGES
from .. import trash
from ..analytics import build_dashboard, dashboard_brief
from ..interview.interview import answered_rounds
from ..interview.interview_experience_service import list_experiences
from ..interview.interview_history import list_question_banks, list_reviews
from ..knowledge_service import (
    create_knowledge as create_knowledge_record,
    knowledge_or_none,
    list_knowledge,
    update_knowledge as update_knowledge_record,
)
from ..referral_service import list_referrals, referral_out
from ..reminder_service import create_reminder as create_reminder_record, list_reminders
from ..resume.resume_templates import font_scale_spec, template_spec
from ..share_package import list_share_packages
from ._shared import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    MAX_PROFILE_RESULT_CHARS,
    _trim,
)
from ._types import ToolResult

logger = logging.getLogger(__name__)
# ===== 模拟面试 =====


def _interview_or_error(db: Session, arguments: dict) -> InterviewSession:
    try:
        session_id = int(arguments.get("session_id"))
    except (TypeError, ValueError):
        raise ValueError("需要提供 session_id（可以先用 list_interview_sessions 查）") from None
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise ValueError(f"模拟面试 {session_id} 不存在")
    return session


def _tool_list_interview_sessions(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    status = str(arguments.get("status") or "").strip()
    query = db.query(InterviewSession)
    if status in {"active", "finished"}:
        query = query.filter(InterviewSession.status == status)
    sessions = query.order_by(InterviewSession.created_at.desc()).limit(limit).all()
    payload = [
        {
            "id": item.id,
            "标题": item.title,
            "岗位": item.job_title,
            "类型": item.interview_type,
            "难度": item.difficulty,
            "轮数": f"{answered_rounds(item)}/{item.rounds}",
            "状态": "进行中" if item.status == "active" else "已结束",
            "总分": (item.report or {}).get("score"),
            "时间": item.created_at.strftime("%Y-%m-%d %H:%M") if item.created_at else "",
        }
        for item in sessions
    ]
    return ToolResult(
        text=json.dumps({"面试": payload}, ensure_ascii=False),
        summary=f"查看了 {len(payload)} 场模拟面试",
        link="/interview",
    )


def _tool_get_interview_report(db: Session, arguments: dict) -> ToolResult:
    session = _interview_or_error(db, arguments)
    report = session.report or {}
    rows = [
        {"role": item.role, "content": item.content.strip()[:2_000]}
        for item in session.messages
        if item.role in {"interviewer", "user"} and item.content.strip()
    ]
    payload = {
        "id": session.id,
        "标题": session.title,
        "岗位": session.job_title,
        "类型": session.interview_type,
        "难度": session.difficulty,
        "轮数": f"{answered_rounds(session)}/{session.rounds}",
        "报告": report,
        "问答记录": rows,
    }
    return ToolResult(
        text=_trim(json.dumps(payload, ensure_ascii=False), MAX_PROFILE_RESULT_CHARS),
        summary=f"读取了模拟面试「{session.title or session.id}」的记录与报告",
        link="/interview",
    )


# ===== 简历版式 =====


def _tool_update_resume_layout(db: Session, arguments: dict) -> ToolResult:
    try:
        resume_id = int(arguments.get("resume_id"))
    except (TypeError, ValueError):
        raise ValueError("需要提供简历 id（可以先用 list_resumes 查）") from None
    record = trash.get_live(db, ResumeRecord, resume_id)
    if record is None:
        raise ValueError(f"简历 {resume_id} 不存在")
    if not any(key in arguments for key in ("template", "page_limit", "font_scale")):
        raise ValueError("需要提供 template、page_limit 或 font_scale 中的至少一项")
    if arguments.get("template") is not None:
        record.template = template_spec(str(arguments["template"]))["name"]
    if arguments.get("page_limit") is not None:
        record.page_limit = max(1, min(int(arguments["page_limit"]), MAX_RESUME_PAGES))
    if arguments.get("font_scale") is not None:
        record.font_scale = font_scale_spec(str(arguments["font_scale"]))["name"]
    db.commit()
    db.refresh(record)
    return ToolResult(
        text=json.dumps(
            {
                "id": record.id,
                "template": record.template,
                "page_limit": record.page_limit,
                "font_scale": record.font_scale,
            },
            ensure_ascii=False,
        ),
        summary=f"调整了简历「{record.title}」的版式",
        link="/resumes",
        changed=True,
    )
# ===== 知识审计补齐：提醒 / 内推 / 面经 / 题库 / 复盘 / 知识库 / 统计 / 分享包 =====
#
# 这些域此前只有界面、没有工具：用户问「我有几个提醒 / 内推 / 面经 / 知识」，助手答不上来，
# 只能靠猜——这正是"了如指掌"的反面。这里补的都是**只读/检索**工具（写工具只有知识库与提醒），
# 且全部复用既有 service（内部已经 live_only 过滤软删除），不另写查询口径。


def _reminder_brief(reminder) -> dict:
    return {
        "id": reminder.id,
        "title": reminder.title,
        "remind_at": reminder.remind_at.isoformat() if reminder.remind_at else None,
        "kind": reminder.kind,
        "status": reminder.status,
        "job_id": reminder.job_id,
        "resume_id": reminder.resume_id,
        "track_id": reminder.track_id,
    }


def _tool_list_reminders(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    rows = list_reminders(
        db,
        kind=str(arguments.get("kind") or ""),
        status=str(arguments.get("status") or ""),
        limit=limit,
    )
    payload = {"总数": len(rows), "返回": len(rows), "提醒": [_reminder_brief(r) for r in rows]}
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了 {len(rows)} 条提醒",
        link="/tracker",
    )


def _referral_brief(db: Session, referral) -> dict:
    out = referral_out(db, referral)
    return {
        "id": out.id,
        "company": out.company,
        "position": out.position or out.job_title,
        "referrer_name": out.referrer_name,
        "relation": out.relation,
        "status": out.status,
        "converted": out.converted,
        "referral_code": out.referral_code,
    }


def _tool_list_referrals(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    rows = list_referrals(
        db,
        status=str(arguments.get("status") or ""),
        keyword=str(arguments.get("keyword") or ""),
        limit=limit,
    )
    payload = {
        "总数": len(rows),
        "返回": len(rows),
        "内推": [_referral_brief(db, r) for r in rows],
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了 {len(rows)} 条内推",
        link="/apply",
    )


def _experience_brief(experience) -> dict:
    return {
        "id": experience.id,
        "title": experience.title,
        "company": experience.company,
        "position": experience.position,
        "source": experience.source,
        "difficulty": experience.difficulty,
        "round_type": experience.round_type,
        "interview_date": experience.interview_date,
        "问题数": len(experience.questions or []),
    }


def _tool_list_interview_experiences(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    rows = list_experiences(
        db,
        keyword=str(arguments.get("keyword") or ""),
        company=str(arguments.get("company") or ""),
        source=str(arguments.get("source") or ""),
        limit=limit,
    )
    payload = {"总数": len(rows), "返回": len(rows), "面经": [_experience_brief(r) for r in rows]}
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了 {len(rows)} 条面经",
        link="/interview",
    )


def _question_bank_brief(record) -> dict:
    return {
        "id": record.id,
        "job_title": record.job_title,
        "company": record.company,
        "resume_title": record.resume_title,
        "题组数": len(record.groups or []),
        "model": record.model,
    }


def _tool_list_question_banks(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    rows = list_question_banks(db, limit=limit)
    payload = {
        "总数": len(rows),
        "返回": len(rows),
        "题库历史": [_question_bank_brief(r) for r in rows],
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了 {len(rows)} 份题库历史",
        link="/interview",
    )


def _review_brief(record) -> dict:
    return {
        "id": record.id,
        "job_title": record.job_title,
        "company": record.company,
        "resume_title": record.resume_title,
        "问题数": len(record.questions or []),
        "建议数": len(record.suggestions or []),
    }


def _tool_list_reviews(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    rows = list_reviews(db, limit=limit)
    payload = {
        "总数": len(rows),
        "返回": len(rows),
        "复盘历史": [_review_brief(r) for r in rows],
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了 {len(rows)} 份复盘历史",
        link="/interview",
    )


def _knowledge_brief(entry) -> dict:
    return {
        "id": entry.id,
        "title": entry.title,
        "category": entry.category,
        "tags": entry.tags or [],
        "source": entry.source,
    }


def _tool_list_knowledge(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    rows = list_knowledge(
        db,
        q=str(arguments.get("q") or ""),
        category=str(arguments.get("category") or ""),
    )
    shown = rows[:limit]
    payload = {
        "总数": len(rows),
        "返回": len(shown),
        "知识库": [_knowledge_brief(r) for r in shown],
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了知识库里的 {len(shown)} 条",
        link="/knowledge",
    )


def _tool_get_knowledge(db: Session, arguments: dict) -> ToolResult:
    try:
        knowledge_id = int(arguments.get("knowledge_id"))
    except (TypeError, ValueError):
        raise ValueError("需要提供知识库条目 id（可以先用 list_knowledge 查）") from None
    entry = knowledge_or_none(db, knowledge_id)
    if entry is None:
        raise ValueError(f"知识库条目 {knowledge_id} 不存在")
    payload = {
        "id": entry.id,
        "title": entry.title,
        "category": entry.category,
        "tags": entry.tags or [],
        "source": entry.source,
        "content": entry.content,
    }
    return ToolResult(
        text=_trim(json.dumps(payload, ensure_ascii=False), MAX_PROFILE_RESULT_CHARS),
        summary=f"读取了知识库条目「{entry.title}」",
        link="/knowledge",
    )


def _tool_create_knowledge(db: Session, arguments: dict) -> ToolResult:
    # 来源固定标注为助手，方便用户在知识库里溯源。
    payload = KnowledgeCreate.model_validate(
        {
            "title": str(arguments.get("title") or ""),
            "category": str(arguments.get("category") or "其他"),
            "tags": arguments.get("tags") or [],
            "content": str(arguments.get("content") or ""),
            "source": str(arguments.get("source") or "助手录入"),
        }
    )
    entry = create_knowledge_record(db, payload)
    return ToolResult(
        text=json.dumps({"id": entry.id, "title": entry.title}, ensure_ascii=False),
        summary=f"新增了知识库条目「{entry.title}」",
        link="/knowledge",
        changed=True,
    )


def _tool_update_knowledge(db: Session, arguments: dict) -> ToolResult:
    try:
        knowledge_id = int(arguments.get("knowledge_id"))
    except (TypeError, ValueError):
        raise ValueError("需要提供知识库条目 id（可以先用 list_knowledge 查）") from None
    entry = knowledge_or_none(db, knowledge_id)
    if entry is None:
        raise ValueError(f"知识库条目 {knowledge_id} 不存在")
    mutable = {
        key: value
        for key, value in arguments.items()
        if key in {"title", "category", "tags", "content", "source"}
    }
    if not mutable:
        raise ValueError("没有给出要修改的字段")
    # KnowledgeUpdate 是整份替换语义：未提到的字段用现有值补齐，避免被清空。
    payload = KnowledgeUpdate.model_validate(
        {
            "title": mutable.get("title", entry.title),
            "category": mutable.get("category", entry.category),
            "tags": mutable.get("tags", entry.tags or []),
            "content": mutable.get("content", entry.content),
            "source": mutable.get("source", entry.source),
        }
    )
    updated = update_knowledge_record(db, entry, payload)
    return ToolResult(
        text=json.dumps({"id": updated.id, "updated": sorted(mutable)}, ensure_ascii=False),
        summary=f"更新了知识库条目「{updated.title}」",
        link="/knowledge",
        changed=True,
    )


def _tool_get_analytics_overview(db: Session, _arguments: dict) -> ToolResult:
    # 下发给助手的是看板的**摘要视图**（``dashboard_brief``），不是整份：全部标量保留，
    # 逐月趋势 / 周内七桶 / 内推状态这些长数组丢掉，公司榜裁到前几名。模型拿一个 24 元素
    # 的趋势数组做不了有用的事，反而稀释了它该看的标量。同一份口径，只是少传几段。
    dashboard = dashboard_brief(build_dashboard(db))
    return ToolResult(
        text=json.dumps(dashboard, ensure_ascii=False),
        summary="查看了求职统计看板",
        link="/analytics",
    )


def _share_package_brief(package) -> dict:
    return {
        "id": package.id,
        "title": package.title,
        "permission": package.permission,
        "file_count": len(package.files or []),
        "created_at": package.created_at.isoformat() if package.created_at else None,
    }


def _tool_list_share_packages(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    rows = list_share_packages(
        db,
        keyword=str(arguments.get("keyword") or ""),
        limit=limit,
    )
    payload = {
        "总数": len(rows),
        "返回": len(rows),
        "分享包": [_share_package_brief(r) for r in rows],
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了 {len(rows)} 个分享包",
        link="/resumes",
    )


def _tool_create_reminder(db: Session, arguments: dict) -> ToolResult:
    if not str(arguments.get("remind_at") or "").strip():
        raise ValueError("需要提供 remind_at（提醒时间，ISO 格式，如 2026-09-20T10:00:00）")
    payload = ReminderCreate.model_validate(
        {
            "title": str(arguments.get("title") or ""),
            "remind_at": arguments["remind_at"],
            "kind": str(arguments.get("kind") or "other"),
            "status": str(arguments.get("status") or "pending"),
            "job_id": arguments.get("job_id"),
            "resume_id": arguments.get("resume_id"),
            "track_id": arguments.get("track_id"),
            "note": str(arguments.get("note") or ""),
        }
    )
    reminder = create_reminder_record(db, payload)
    return ToolResult(
        text=json.dumps(
            {
                "id": reminder.id,
                "title": reminder.title,
                "remind_at": reminder.remind_at.isoformat() if reminder.remind_at else None,
            },
            ensure_ascii=False,
        ),
        summary=f"新增了提醒「{reminder.title}」",
        link="/tracker",
        changed=True,
    )
