"""模拟面试接口：开场、逐轮问答、结束评分与报告归档。

不流式：一轮请求要同时拿到"对上一答的点评"和"下一题"，流式会让界面出现半成品状态。
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.interview import (
    INTERVIEW_STATUS_ACTIVE,
    INTERVIEW_STATUS_FINISHED,
    InterviewSession,
)
from ..models.job import Job
from ..schemas.interview import (
    InterviewAnswerCreate,
    InterviewAnswerResult,
    InterviewBrief,
    InterviewCreate,
    InterviewDetail,
    InterviewMessageOut,
)
from ..schemas.material import MaterialCreate, MaterialOut
from ..services.interview import (
    add_message,
    answered_rounds,
    generate_question,
    generate_report,
    mark_finished,
    session_persona,
)
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.materials import create_material as create_material_record
from ..services.profile_relevance import build_job_prompt_text
from ..services.profile_service import get_profile_detail, to_profile_out
from ..services.settings_service import get_llm_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/interview", tags=["interview"])

MAX_JOB_CONTEXT_FOR_INTERVIEW = 6_000


def _session_or_404(db: Session, session_id: int) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="面试不存在或已被删除")
    return session


def _require_provider(db: Session):
    """模拟面试每一轮都要调用模型，所以必须已配置。"""
    config = get_llm_config(db)
    if not config.base_url.strip() or not config.model.strip():
        raise HTTPException(status_code=400, detail="请先在「设置」页配置大模型 API")
    return create_provider(config), config.model


def _profile_text(db: Session) -> str:
    """个人资料序列化成文本，作为面试官的"简历"。

    必须用 ``mode="json"``：资料里带 ``datetime``（创建/更新时间），默认的 ``model_dump``
    会留下 datetime 对象，``json.dumps`` 会直接抛 TypeError 让整个开场请求 500。
    """
    try:
        profile = to_profile_out(get_profile_detail(db)).model_dump(
            mode="json", exclude={"photo"}
        )
    except Exception:  # noqa: BLE001 - 没有资料不该阻断面试
        logger.warning("读取个人资料失败，模拟面试将不携带资料", exc_info=True)
        return ""
    return json.dumps(profile, ensure_ascii=False)


def _job_text(db: Session, job_id: int | None) -> str:
    if job_id is None:
        return ""
    job = db.get(Job, job_id)
    if job is None:
        return ""
    return build_job_prompt_text(job, MAX_JOB_CONTEXT_FOR_INTERVIEW)


def _to_out(session: InterviewSession) -> InterviewBrief:
    return InterviewBrief(
        id=session.id,
        title=session.title,
        job_id=session.job_id,
        job_title=session.job_title,
        company=session.company,
        interview_type=session.interview_type,
        difficulty=session.difficulty,
        interviewer_style=session.interviewer_style,
        rounds=session.rounds,
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        answered_rounds=answered_rounds(session),
    )


def _to_detail(session: InterviewSession) -> InterviewDetail:
    return InterviewDetail(
        **_to_out(session).model_dump(),
        persona=session.persona,
        focus=session.focus,
        model=session.model,
        report=session.report or {},
        messages=[InterviewMessageOut.model_validate(item) for item in session.messages],
    )


def _default_title(payload: InterviewCreate, job: Job | None) -> str:
    if payload.title.strip():
        return payload.title.strip()[:128]
    if job is not None and job.title:
        return f"{job.title} 模拟面试"[:128]
    return f"{payload.interview_type}模拟面试"[:128]


async def _ask_next_question(
    db: Session, session: InterviewSession, provider
) -> tuple[str, str, bool]:
    return await generate_question(
        provider,
        session,
        profile_text=_profile_text(db),
        job_text=_job_text(db, session.job_id),
    )


async def _finish_with_report(
    db: Session, session: InterviewSession, provider, *, closing: str = ""
) -> None:
    """结束面试并写入报告；报告失败时留下说明而不是让整场面试不可用。"""
    if closing.strip():
        add_message(session, role="note", content=closing.strip())
    try:
        session.report = await generate_report(provider, session)
    except LLMError as exc:
        logger.warning("面试报告生成失败 session=%s：%s", session.id, exc)
        session.report = {"summary": f"报告生成失败：{exc}", "error": True}
    mark_finished(session)
    db.commit()
    db.refresh(session)


@router.get("", response_model=list[InterviewBrief])
def list_sessions(
    limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)
):
    sessions = (
        db.query(InterviewSession)
        .order_by(InterviewSession.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_to_out(item) for item in sessions]


@router.post("", response_model=InterviewDetail, status_code=201)
async def create_session(payload: InterviewCreate, db: Session = Depends(get_db)):
    """开一场面试：先落库会话，再让面试官问第一个问题。"""
    provider, model = _require_provider(db)
    job = db.get(Job, payload.job_id) if payload.job_id else None
    session = InterviewSession(
        title=_default_title(payload, job),
        job_id=job.id if job is not None else None,
        job_title=job.title if job is not None else "",
        company=job.company if job is not None else "",
        interview_type=payload.interview_type,
        difficulty=payload.difficulty,
        interviewer_style=payload.interviewer_style,
        rounds=payload.rounds,
        persona=payload.persona.strip(),
        focus=payload.focus.strip(),
        model=model,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    try:
        question, _feedback, _done = await _ask_next_question(db, session, provider)
    except LLMError as exc:
        # 开场失败就删掉这条空会话：留一条没有任何内容的面试只会让列表变乱。
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    add_message(
        session,
        role="interviewer",
        content=question,
        context={"index": 1, "rounds": session.rounds, "persona": session_persona(session)},
    )
    db.commit()
    db.refresh(session)
    logger.info("模拟面试已开始 id=%s type=%s", session.id, session.interview_type)
    return _to_detail(session)


@router.get("/{session_id}", response_model=InterviewDetail)
def read_session(session_id: int, db: Session = Depends(get_db)):
    return _to_detail(_session_or_404(db, session_id))


@router.post("/{session_id}/answers", response_model=InterviewAnswerResult)
async def submit_answer(
    session_id: int, payload: InterviewAnswerCreate, db: Session = Depends(get_db)
):
    """提交一轮回答：返回点评与下一题；满轮次时自动收尾并出报告。"""
    session = _session_or_404(db, session_id)
    if session.status != INTERVIEW_STATUS_ACTIVE:
        raise HTTPException(status_code=409, detail="这场面试已经结束，请查看报告或新开一场")
    provider, _model = _require_provider(db)

    add_message(session, role="user", content=payload.content)
    db.commit()
    index = answered_rounds(session)

    # 已经答满轮数就**先收尾**，不再去要下一题。这一步必须排在模型调用之前，否则：
    #   · 会多存一道永远不会被回答的问题，它还会进报告和资料箱里的转录；
    #   · 传给模型的 index 变成 rounds + 1，提示词里出现"第 13 / 12 轮"这种自相矛盾的信息，
    #     模型自然不知道该收尾；
    #   · rounds 取到上限（MAX_INTERVIEW_ROUNDS）时 index 越界，generate_question 直接抛错，
    #     最后一答变成 502，面试卡在 active 状态回不来。
    # 最后一答的点评不会丢：报告基于完整问答记录生成，那一答也在里面。
    if index >= session.rounds:
        await _finish_with_report(db, session, provider)
        return InterviewAnswerResult(session=_to_detail(session), feedback="", finished=True)

    try:
        question, feedback, done = await _ask_next_question(db, session, provider)
    except LLMError as exc:
        # 回答已经存下来了，用户不会白写；只是这一轮的追问失败。
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    add_message(
        session,
        role="interviewer",
        content=question,
        context={"index": index, "rounds": session.rounds, "feedback": feedback},
    )
    db.commit()

    # 模型提前结束（done）：这里的 question 按提示词约定是收尾语，存下来给用户看。
    if done:
        await _finish_with_report(db, session, provider)
        return InterviewAnswerResult(session=_to_detail(session), feedback=feedback, finished=True)

    db.refresh(session)
    return InterviewAnswerResult(session=_to_detail(session), feedback=feedback, finished=False)


@router.post("/{session_id}/finish", response_model=InterviewDetail)
async def finish_session(session_id: int, db: Session = Depends(get_db)):
    """提前结束并出报告（用户点"结束面试"）。"""
    session = _session_or_404(db, session_id)
    if session.status == INTERVIEW_STATUS_FINISHED:
        return _to_detail(session)
    if answered_rounds(session) == 0:
        raise HTTPException(status_code=400, detail="还没有回答任何问题，无法生成报告")
    provider, _model = _require_provider(db)
    await _finish_with_report(db, session, provider, closing="（候选人主动结束了这场面试）")
    return _to_detail(session)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: int, db: Session = Depends(get_db)):
    session = _session_or_404(db, session_id)
    db.delete(session)
    db.commit()


def _report_markdown(session: InterviewSession) -> str:
    """把面试记录与报告整理成一份 Markdown，存进资料箱当复盘材料。"""
    report = session.report or {}
    lines = [
        f"# {session.title or '模拟面试'}",
        "",
        f"- 面试类型：{session.interview_type}",
        f"- 难度：{session.difficulty}",
        f"- 面试官风格：{session.interviewer_style}",
        f"- 目标岗位：{session.job_title or '未关联'}"
        + (f" @ {session.company}" if session.company else ""),
        f"- 问答轮数：{answered_rounds(session)} / {session.rounds}",
    ]
    if report.get("score"):
        lines.append(f"- 总评分：{report['score']}")
    lines.extend(["", "## 问答记录", ""])
    for item in session.messages:
        if item.role == "interviewer":
            lines.append(f"**面试官**：{item.content}")
        elif item.role == "user":
            lines.append(f"**我**：{item.content}")
        else:
            lines.append(f"（{item.content}）")
        lines.append("")
    if report.get("dimensions") or report.get("summary"):
        lines.extend(["## 评分报告", ""])
        for item in report.get("dimensions") or []:
            lines.append(f"- **{item.get('name')}**：{item.get('score')} 分 —— {item.get('comment', '')}")
        if report.get("strengths"):
            lines.extend(["", "### 做得好", *[f"- {text}" for text in report["strengths"]]])
        if report.get("improvements"):
            lines.extend(["", "### 可以改进", *[f"- {text}" for text in report["improvements"]]])
        if report.get("summary"):
            lines.extend(["", f"> {report['summary']}"])
    return "\n".join(lines).rstrip() + "\n"


@router.post("/{session_id}/to-material", response_model=MaterialOut, status_code=201)
def report_to_material(session_id: int, db: Session = Depends(get_db)):
    """把这场面试的记录与报告存进资料箱（面试复盘）。"""
    session = _session_or_404(db, session_id)
    return create_material_record(
        db,
        MaterialCreate(
            title=f"面试复盘：{session.title or session.interview_type}"[:256],
            category="面试复盘",
            content=_report_markdown(session),
            note=f"来自模拟面试 #{session.id}",
        ),
    )
