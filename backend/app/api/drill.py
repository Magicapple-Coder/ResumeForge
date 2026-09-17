"""按事实台账深挖的面试接口（prefix ``/api/drill``）。

**契约先锁、再提问**是这里唯一的顺序要求：``POST /{id}/answer`` 走的是"读出现有契约 →
按它判定 → 写回结论"，而不是"先看答案再定标准"。这条顺序在实现里体现为
``open_contract()`` 必须在返回问题给用户**之前**被调用。

路由顺序：固定路径（``/claims``）要排在 ``/{session_id}`` 之前。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models.drill import (
    DRILL_STATUS_ACTIVE,
    DRILL_STATUS_FINISHED,
    EVIDENCE_STATUSES,
    FEEDBACK_DEFERRED,
    FEEDBACK_IMMEDIATE,
    REHEARSE_LABELS,
    REHEARSE_VARIANT,
    DrillSession,
)
from ..models.job import Job
from ..schemas.drill import (
    DrillAnswerRequest,
    DrillAnswerResult,
    DrillContractOut,
    DrillCreate,
    DrillRehearseOut,
    DrillRehearseRequest,
    DrillSessionBrief,
    DrillSessionOut,
)
from ..services.drill import (
    load_prompt,
    apply_verdict,
    evaluate_answer,
    finish_session,
    generate_plan,
    generate_review,
    local_review,
    current_question,
    open_contract,
    pending_contract,
    select_claims,
    session_summary,
)
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.settings_service import get_llm_config
from ..services.text_extraction import llm_is_configured

router = APIRouter(prefix="/api/drill", tags=["drill"])
logger = logging.getLogger(__name__)


def _session_or_404(db: Session, session_id: int) -> DrillSession:
    record = db.get(DrillSession, session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="这场深挖记录不存在或已被删除")
    return record


def _session_out(record: DrillSession) -> DrillSessionOut:
    pending = pending_contract(record)
    return DrillSessionOut(
        id=record.id,
        title=record.title,
        job_id=record.job_id,
        job_title=record.job_title,
        company=record.company,
        status=record.status,
        feedback_policy=record.feedback_policy,
        max_questions=record.max_questions,
        current_index=record.current_index,
        created_at=record.created_at,
        contracts=[DrillContractOut.model_validate(item) for item in record.contracts],
        turns=[
            {
                "id": turn.id,
                "contract_id": turn.contract_id,
                "question": turn.question,
                "answer": turn.answer,
                "status": turn.status,
                "feedback": turn.feedback,
                "created_at": turn.created_at,
            }
            for turn in record.turns
        ],
        review=record.review or {},
        summary=session_summary(record),
        pending=DrillContractOut.model_validate(pending) if pending else None,
    )


@router.get("", response_model=list[DrillSessionBrief])
def list_sessions(
    status: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """列出深挖记录；``status`` 可选 active / finished。"""
    query = db.query(DrillSession)
    if status:
        if status not in (DRILL_STATUS_ACTIVE, DRILL_STATUS_FINISHED):
            raise HTTPException(status_code=422, detail="未知的会话状态")
        query = query.filter(DrillSession.status == status)
    return [
        DrillSessionBrief.model_validate(item)
        for item in query.order_by(DrillSession.created_at.desc()).all()
    ]


@router.post("", response_model=DrillSessionOut, status_code=201)
async def create_session(payload: DrillCreate, db: Session = Depends(get_db)):
    """开一场深挖：先选出要验证的主张，再为第一条生成**评分契约**。

    契约在这一步就落库了——用户看到问题的时候，判定标准已经定下来。
    """
    claims = select_claims(db, payload.claim_ids, payload.max_questions)
    if not claims:
        raise HTTPException(
            status_code=400,
            detail=(
                "没有可深挖的主张。深挖只针对台账里「已确认」的条目——"
                "先在「事实台账」里确认几条，再回来开这一场。"
            ),
        )

    job = db.get(Job, payload.job_id) if payload.job_id else None
    # 标题默认带上**第一条主张**的名字：一页十几场「主张深挖」谁也认不出是哪一场，
    # 而列表里区分它们的唯一线索就是标题。
    first_claim = claims[0].title or claims[0].subject or f"条目 {claims[0].id}"
    default_title = (
        f"{job.title} · {first_claim}" if job is not None else f"{first_claim} · 主张深挖"
    )
    session = DrillSession(
        title=payload.title.strip() or default_title[:128],
        job_id=payload.job_id,
        job_title=job.title if job is not None else "",
        company=job.company if job is not None else "",
        feedback_policy=payload.feedback_policy,
        claim_ids=[item.id for item in claims],
        max_questions=min(payload.max_questions, len(claims)),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    config = get_llm_config(db)
    if not llm_is_configured(config):
        # 没有模型就开不了这场深挖——契约必须由模型按主张生成，编一份假的等于没有标准。
        db.delete(session)
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="请先在「设置」页配置大模型：深挖的每一题都要先按你的主张生成评分标准。",
        )

    provider = create_provider(config)
    job_title, company = session.job_title, session.company
    session_id = session.id
    db.close()  # 模型调用期间不要占着连接池

    async def _drop_session() -> None:
        """第一题没生成出来时把这条空会话删掉。

        用户会看到"一场问不出题的记录"，那比报错更让人困惑。删的时候必须**另开一个
        会话**——原请求会话已经关掉了。
        """
        with SessionLocal() as cleanup_db:
            stored = cleanup_db.get(DrillSession, session_id)
            if stored is not None:
                cleanup_db.delete(stored)
                cleanup_db.commit()

    try:
        plan = await generate_plan(provider, claims[0], job_title=job_title, company=company)
    except LLMError as exc:
        logger.warning("生成面试深挖契约失败：%s", exc)
        await _drop_session()
        raise HTTPException(status_code=502, detail=f"生成第一题失败：{exc}") from exc
    except Exception:  # noqa: BLE001 - 外部模型异常不能变成 500
        logger.exception("生成面试深挖契约发生内部错误")
        await _drop_session()
        raise HTTPException(status_code=502, detail="生成第一题失败，请稍后重试")

    with SessionLocal() as write_db:
        stored = write_db.get(DrillSession, session_id)
        if stored is None:  # pragma: no cover - 只在并发删除时发生
            raise HTTPException(status_code=404, detail="这场深挖记录已不存在")
        claim = write_db.get(type(claims[0]), claims[0].id)
        open_contract(stored, claim, plan)
        # 立刻 flush：契约的 id 要给后续轮次做外键，None 会让"这轮属于哪道题"对不上。
        write_db.flush()
        write_db.commit()
        write_db.refresh(stored)
        return _session_out(stored)


@router.get("/{session_id}", response_model=DrillSessionOut)
def read_session(session_id: int, db: Session = Depends(get_db)):
    return _session_out(_session_or_404(db, session_id))


@router.post("/{session_id}/answer", response_model=DrillAnswerResult)
async def answer(session_id: int, payload: DrillAnswerRequest, db: Session = Depends(get_db)):
    """回答当前这一问：按**已锁定的契约**判定，然后要么追问，要么问下一题。"""
    session = _session_or_404(db, session_id)
    if session.status != DRILL_STATUS_ACTIVE:
        raise HTTPException(status_code=409, detail="这场深挖已经结束了")
    contract = pending_contract(session)
    if contract is None:
        raise HTTPException(status_code=409, detail="当前没有等待回答的问题")

    config = get_llm_config(db)
    if not llm_is_configured(config):
        raise HTTPException(status_code=400, detail="请先在「设置」页配置大模型")

    provider = create_provider(config)
    db.close()

    # ★ 判定要读契约与问答记录，两者都必须来自**重载后**的会话：请求会话已经关掉，
    #   继续用它上面挂着的对象会 detached（访问 JSON 字段就抛异常，最后被翻成
    #   一句含糊的"内部错误"）。
    read_db, reloaded = _load_session_for_model(session_id)
    try:
        live_contract = (
            reloaded.contracts[-1]
            if reloaded.contracts and reloaded.contracts[-1].id == contract.id
            else None
        )
        if live_contract is None:  # pragma: no cover - 并发改动
            raise HTTPException(status_code=409, detail="这场深挖的进度已经变化，请刷新后重试")
        try:
            verdict = await evaluate_answer(provider, reloaded, live_contract, payload.answer)
        except LLMError as exc:
            logger.warning("面试深挖判定失败：%s", exc)
            raise HTTPException(status_code=502, detail=f"判定这一轮失败：{exc}") from exc
        except Exception:  # noqa: BLE001 - 外部模型异常不能变成 500
            logger.exception("面试深挖判定发生内部错误")
            raise HTTPException(status_code=502, detail="判定这一轮失败，请稍后重试")
    finally:
        read_db.close()

    with SessionLocal() as write_db:
        stored = write_db.get(DrillSession, session_id)
        if stored is None:  # pragma: no cover
            raise HTTPException(status_code=404, detail="这场深挖记录已不存在")
        current = stored.contracts[-1] if stored.contracts else None
        if current is None or current.id != contract.id:
            raise HTTPException(status_code=409, detail="这场深挖的进度已经变化，请刷新后重试")
        apply_verdict(
            stored,
            current,
            verdict,
            # 被回答的是"上一次判定生成的那一问"，没有就退回契约上的第一问。
            question=current_question(stored, current),
            answer=payload.answer,
        )
        write_db.commit()

        # 这道题问完了：要么开下一题（新契约），要么收尾出复盘。
        finished = False
        next_plan_error = ""
        if verdict.done:
            if stored.current_index >= stored.max_questions:
                finished = True
            else:
                claims = select_claims(write_db, stored.claim_ids, stored.max_questions)
                nxt = next((c for c in claims if c.id not in {k.claim_id for k in stored.contracts}), None)
                if nxt is None:
                    finished = True
                else:
                    try:
                        plan = await generate_plan(
                            provider, nxt, job_title=stored.job_title, company=stored.company
                        )
                        open_contract(stored, nxt, plan)
                        # 同上一处：契约的 id 要先落下来，后面的轮次才挂得上。
                        write_db.flush()
                    except LLMError as exc:
                        # 下一题生成失败不该把这一场作废：已有的判定都在，直接收尾出复盘。
                        logger.warning("生成下一题的契约失败，提前收尾：%s", exc)
                        next_plan_error = str(exc)
                        finished = True
                    except Exception:  # noqa: BLE001
                        logger.exception("生成下一题的契约发生内部错误，提前收尾")
                        next_plan_error = "内部错误"
                        finished = True

        if finished and stored.status == DRILL_STATUS_ACTIVE:
            try:
                review = await generate_review(provider, stored)
            except LLMError as exc:
                logger.warning("生成复盘失败，改用本地汇总：%s", exc)
                review = local_review(stored)
            except Exception:  # noqa: BLE001
                logger.exception("生成复盘发生内部错误，改用本地汇总")
                review = local_review(stored)
            finish_session(stored, review)
        write_db.commit()
        write_db.refresh(stored)
        # ★ 响应必须在**这个会话关闭之前**构造好：`_session_out` 要读
        #   `stored.contracts` / `stored.turns`，而它们是延迟加载的——出了这个块
        #   对象就 detached，访问时抛 DetachedInstanceError，最后被翻成一句
        #   含糊的"内部错误"。
        session_out = _session_out(stored)

    feedback = verdict.feedback if session.feedback_policy == FEEDBACK_IMMEDIATE else ""
    if next_plan_error:
        # 提前收尾的原因要如实说，否则"这场怎么突然结束了"会成为一个疑问。
        note = f"（下一题生成失败，已提前收尾：{next_plan_error}）"
        feedback = f"{feedback} {note}".strip() if feedback else note
    return DrillAnswerResult(
        status=verdict.status,
        evidence_found=verdict.evidence_found,
        missing=verdict.missing,
        contradictions=verdict.contradictions,
        # 真实模拟模式下不在每题后念判定——那会让人按判分标准答题，而不像真面试。
        feedback=feedback,
        finished=finished,
        session=session_out,
    )


def _load_session_for_model(session_id: int):
    """打开一个**由调用方负责关闭**的会话，返回其中的深挖记录。

    不能用 `with` 块：模型调用要读 ``record.contracts`` / ``record.turns``，而这些关系是
    延迟加载的——会话一关，访问它们就抛 ``DetachedInstanceError``，最后会被翻成一句
    含糊的"内部错误"，排查时很容易走偏。所以这里把生命周期交给调用方，
    在模型调用**结束之后**再关。
    """
    db = SessionLocal()
    try:
        record = db.get(DrillSession, session_id)
        if record is None:  # pragma: no cover - 并发删除
            raise HTTPException(status_code=404, detail="这场深挖记录已不存在")
        # 主动读一遍，把契约与轮次都装进内存，避免调用方在 await 期间触发懒加载。
        for contract in record.contracts:
            _ = (
                contract.required_evidence,
                contract.followup_triggers,
                contract.evidence_found,
                contract.missing,
                contract.contradictions,
            )
        _ = [turn.question for turn in record.turns]
        return db, record
    except Exception:
        db.close()
        raise


@router.post("/{session_id}/finish", response_model=DrillSessionOut)
async def finish(session_id: int, db: Session = Depends(get_db)):
    """提前结束并出复盘。已经结束的再调一次不会重复生成。"""
    session = _session_or_404(db, session_id)
    if session.status != DRILL_STATUS_ACTIVE:
        return _session_out(session)

    config = get_llm_config(db)
    if not llm_is_configured(config):
        finish_session(session, local_review(session))
        db.commit()
        db.refresh(session)
        return _session_out(session)

    provider = create_provider(config)
    db.close()
    read_db, reloaded = _load_session_for_model(session_id)
    try:
        try:
            review = await generate_review(provider, reloaded)
        except LLMError as exc:
            logger.warning("生成复盘失败，改用本地汇总：%s", exc)
            review = local_review(reloaded)
        except Exception:  # noqa: BLE001
            logger.exception("生成复盘发生内部错误，改用本地汇总")
            review = local_review(reloaded)
    finally:
        read_db.close()

    with SessionLocal() as write_db:
        stored = write_db.get(DrillSession, session_id)
        if stored is None:  # pragma: no cover
            raise HTTPException(status_code=404, detail="这场深挖记录已不存在")
        finish_session(stored, review)
        write_db.commit()
        write_db.refresh(stored)
        return _session_out(stored)


@router.post("/{session_id}/rehearse", response_model=DrillRehearseOut)
async def rehearse(
    session_id: int, payload: DrillRehearseRequest, db: Session = Depends(get_db)
):
    """把复练队列里的一条变成一个**可回答的新问题**（不落库）。

    复练的关键是"不原题重复"：同一条主张换一个角度再问一次，才检验得出他是不是真的
    会了——把上次的答案背一遍不算。
    """
    # 先确认这一场存在（不存在时给 404 而不是让后面报一个看不懂的错）。
    _session_or_404(db, session_id)
    config = get_llm_config(db)
    if not llm_is_configured(config):
        raise HTTPException(status_code=400, detail="请先在「设置」页配置大模型")

    provider = create_provider(config)
    db.close()

    kind_note = REHEARSE_LABELS.get(payload.kind, REHEARSE_LABELS[REHEARSE_VARIANT])
    instruction = (
        "候选人要把一条主张再练一遍。请**换一个角度**出一道新题——"
        "不要重复他上次被问到的问题。\n"
        f"题型：{kind_note}\n"
        f"这条主张：{payload.claim_title}\n"
        f"上次暴露的缺口：{payload.why or '（未记录）'}\n\n"
        "只输出一个 JSON 对象，不要解释或 Markdown 围栏：\n"
        '{"question": "一个新问题（一次只问一个）", "expect": "这道题在要求什么，'
        '让人知道该往哪个方向答"}'
    )
    try:
        raw = await provider.chat(
            [
                {"role": "system", "content": load_prompt("drill_contract.md")},
                {"role": "user", "content": instruction},
            ]
        )
        from ..services.llm.structured_output import parse_json_object

        data = parse_json_object(raw, label="面试深挖", max_chars=20_000)
    except LLMError as exc:
        logger.warning("生成复练题失败：%s", exc)
        raise HTTPException(status_code=502, detail=f"生成复练题失败：{exc}") from exc

    question = str(data.get("question") or "").strip()[:1_000]
    if not question:
        raise HTTPException(status_code=502, detail="生成复练题失败：模型没有给出问题")
    return DrillRehearseOut(
        claim_title=payload.claim_title,
        kind=payload.kind,
        question=question,
        expect=str(data.get("expect") or "").strip()[:1_000],
    )


@router.get("/{session_id}/rehearsal", response_model=list[dict])
def list_rehearsal(session_id: int, db: Session = Depends(get_db)):
    """复练队列：只含"部分验证 / 未验证 / 存在矛盾"的主张。"""
    session = _session_or_404(db, session_id)
    items = (session.review or {}).get("rehearsal") or []
    return [
        {
            **item,
            "kind_label": REHEARSE_LABELS.get(item.get("kind", ""), ""),
        }
        for item in items
        if isinstance(item, dict)
    ]


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: int, db: Session = Depends(get_db)):
    session = db.get(DrillSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="这场深挖记录不存在或已被删除")
    db.delete(session)
    db.commit()
    return None


__all__ = ["router", "EVIDENCE_STATUSES", "FEEDBACK_DEFERRED", "FEEDBACK_IMMEDIATE"]
