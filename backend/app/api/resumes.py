"""简历接口：流式生成（SSE）、历史记录、预览渲染与导出。"""
import json
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import cast, or_, String
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models.job import Job
from ..services import trash
from ..models.resume import GENERATE_ACTIVE_STATUSES, ResumeGenerateTask, ResumeRecord
from ..schemas.common import Page
from ..schemas.export import (
    ExportRequest as ExportRequestSchema,
    RedactionOptions as RedactionOptionsSchema,
)
from ..schemas.job import JobOut
from ..schemas.resume import (
    GenerateRequest,
    GenerateTaskOut,
    LayoutAnalyzeOut,
    LayoutAnalyzeRequest,
    LayoutDiagnosisOut,
    LayoutFitCandidateOut,
    LayoutFitRoomOut,
    LayoutPageOut,
    LayoutSuggestionOut,
    ManualResumeRequest,
    ResumeBrief,
    ResumeContent,
    ResumeFavoriteUpdate,
    ResumeLayoutUpdate,
    ResumeNoteUpdate,
    ResumeOut,
    ResumeRenderRequest,
    ResumeSuggestionsOut,
    ResumeTitleUpdate,
)
from ..services.claims import build_baseline
from ..services.exporter import normalize_page_limit, render_html
from ..services.export_pipeline import ExportRequest, RenderContext, build_export
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.pdf_exporter import ResumePDFError, font_available
from ..services.privacy import RedactionOptions as PrivacyRedactionOptions, redact
from ..services.profile.profile_service import get_profile_detail, to_profile_out
from ..services.resume.resume_completeness import find_incomplete, incomplete_detail
from ..services.resume.resume_generate_runner import (
    ResumeGenerateRunnerError,
    get_resume_generate_runner,
)
from ..services.resume.resume_generator import ResumeGenerator
from ..services.resume.resume_record import (
    build_manual_title,
    record_format_config,
    resolved_format_name,
    resolved_style_name,
    save_record,
)
from ..services.resume.resume_layout import (
    STATUS_OVERFLOW,
    build_fit_ladder,
    diagnose,
    fit_room_report,
)
from ..services.resume.resume_suggestions import generate_suggestions
from ..services.resume.resume_template_store import (
    custom_format_options,
    custom_template_options,
    resolve_format_config,
    resolve_style_template,
)
from ..services.resume.resume_templates import (
    DEFAULT_FONT_SCALE,
    DEFAULT_PAGE_LIMIT,
    DEFAULT_TEMPLATE,
    FORMAT_PRESETS,
    font_scale_options,
    font_scale_spec,
    format_field_options,
    market_options,
    validated_format_config,
    template_options_with_custom,
)
from ..services.settings_service import get_llm_config
from ..services.watermark import WatermarkError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resumes", tags=["resumes"])

# 服务端 PDF 的实际页数与用户选定的上限。前端靠它们提示"下载下来的页数和你选的不一样"，
# 因此这两个响应头必须出现在 CORS 的 expose_headers 里（见 application.py）。
PDF_PAGES_HEADER = "X-Resume-Pages"
PDF_PAGE_LIMIT_HEADER = "X-Resume-Page-Limit"


@router.get("/templates")
def read_resume_templates(db: Session = Depends(get_db)):
    """可选的简历模板、格式模板与字号档位（生成、预览、工作台共用这一份清单）。

    必须定义在 ``/{resume_id}`` 之前：否则 ``templates`` 会被当成记录 id 匹配，
    请求会以 422 结束。
    """
    return {
        "templates": template_options_with_custom(custom_template_options(db)),
        "font_scales": font_scale_options(),
        "format_fields": format_field_options(),
        "format_presets": [
            {
                "name": item["name"],
                "label": item["label"],
                "description": item["description"],
                "config": item["config"],
                "custom": False,
                "id": None,
            }
            for item in FORMAT_PRESETS
        ]
        + [
            {
                "name": item["name"],
                "label": item["label"],
                "description": item["description"],
                "config": item["config"],
                "custom": True,
                "id": item["id"],
            }
            for item in custom_format_options(db)
        ],
        "defaults": {
            "template": DEFAULT_TEMPLATE,
            "font_scale": DEFAULT_FONT_SCALE,
            "page_limit": DEFAULT_PAGE_LIMIT,
            "format_name": "",
        },
        # 模板市场（R-19）：映射既有样式模板 + 格式预设 + 建议字号，不新建样式文件。
        "market": market_options(),
        "pdf_direct_available": font_available(),
    }


def _format_sse(payload: dict) -> str:
    """把事件转成 SSE 数据帧。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/generate")
async def generate_resume(payload: GenerateRequest, db: Session = Depends(get_db)):
    """流式生成简历（SSE）。

    ``job_id`` 为空表示生成**通用简历**（不针对任何岗位）。事件类型见
    services/resume/resume_generator.py 文档；生成结果成功落库后，依次发送携带记录 id 的
    saved 事件和最终 done 事件。
    """
    job = db.get(Job, payload.job_id) if payload.job_id is not None else None
    if payload.job_id is not None and (job is None or trash.is_deleted(job)):
        raise HTTPException(status_code=404, detail="岗位不存在或已被删除")

    profile = get_profile_detail(db)
    if (
        not profile.name
        and not profile.projects
        and not profile.experiences
        and not profile.campus_experiences
    ):
        raise HTTPException(status_code=400, detail="请先在「我的资料」页完善个人信息")

    config = get_llm_config(db)
    if not config.base_url or not config.model:
        raise HTTPException(status_code=400, detail="请先在「设置」页配置大模型 API")

    generator = ResumeGenerator(create_provider(config))
    job_out = JobOut.model_validate(job) if job is not None else None
    profile_out = to_profile_out(profile)
    # 事实台账里已确认的条目作为事实基线交给模型；台账为空时它就是空基线，
    # 生成行为与没有这个功能时完全一致。
    baseline = build_baseline(db)
    # 流式模型调用可能持续数分钟；快照完成后立即释放请求 Session，避免占满连接池。
    db.close()

    async def event_stream():
        raw_parts: list[str] = []
        parsed: dict | None = None
        warnings: list[str] = []
        done_event: dict | None = None
        try:
            async for event in generator.generate(
                profile_out, job_out, payload.options, baseline=baseline
            ):
                if event["type"] == "delta":
                    raw_parts.append(event["text"])
                if event["type"] == "done":
                    parsed = event["resume"]
                    warnings = event["warnings"]
                    done_event = event
                    continue
                yield _format_sse(event)
            if parsed is not None and done_event is not None:
                with SessionLocal() as save_db:
                    record = save_record(
                        save_db,
                        parsed,
                        warnings,
                        job_out,
                        "".join(raw_parts),
                        generator.provider.config.model,
                        payload.options.enhance,
                        payload.options.enhancement_level,
                        requested_title=payload.title,
                        template=payload.options.template,
                        format_name=payload.options.format_name,
                        page_limit=payload.options.page_limit,
                        font_scale=payload.options.font_scale,
                        custom_instruction=payload.options.custom_instruction,
                    )
                # 只有持久化成功后才宣布完成；断流不会留下“成功但无历史记录”的状态。
                yield _format_sse({"type": "saved", "record_id": record.id})
                yield _format_sse(done_event)
        except LLMError as exc:
            logger.warning("简历生成失败（模型错误）：%s", exc)
            yield _format_sse({"type": "error", "message": str(exc)})
        except Exception:  # noqa: BLE001 - 流式接口必须兜底，异常转为事件而非中断连接
            logger.exception("简历生成发生内部错误")
            yield _format_sse({"type": "error", "message": "生成过程中发生内部错误，请查看后端日志"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ===== 生成后台任务（轮询模型，替代弹窗里的同步 SSE 等待）=====
#
# 为什么保留上面的 ``POST /generate``（SSE）又新增这套任务接口：SSE 是"请求期间持续
# 连接"的旧形态，无法满足"关掉弹窗后生成继续在后台跑"；而直接改掉 SSE 会破坏既有
# 流式语义与一批测试。所以新增一套任务接口，前端生成弹窗改走这里，SSE 路径保持不变。


@router.post("/generate/tasks", response_model=GenerateTaskOut, status_code=201)
def start_resume_generation(payload: GenerateRequest, db: Session = Depends(get_db)):
    """启动一次后台简历生成，返回可轮询的任务（``task_id`` 即任务 id）。

    前置校验与 ``POST /generate`` 完全一致（岗位存在、资料非空、LLM 已配置），
    保证任务一旦建起来，后台线程就能拿到完整输入。
    """
    job = db.get(Job, payload.job_id) if payload.job_id is not None else None
    if payload.job_id is not None and (job is None or trash.is_deleted(job)):
        raise HTTPException(status_code=404, detail="岗位不存在或已被删除")

    profile = get_profile_detail(db)
    if (
        not profile.name
        and not profile.projects
        and not profile.experiences
        and not profile.campus_experiences
    ):
        raise HTTPException(status_code=400, detail="请先在「我的资料」页完善个人信息")

    config = get_llm_config(db)
    if not config.base_url or not config.model:
        raise HTTPException(status_code=400, detail="请先在「设置」页配置大模型 API")

    # 防重复：已有进行中的任务就拒绝，绝不因用户连点两次而产生两条任务/两份简历。
    active = (
        db.query(ResumeGenerateTask)
        .filter(ResumeGenerateTask.status.in_(GENERATE_ACTIVE_STATUSES))
        .first()
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="已有简历生成任务正在进行中，请等待其完成")

    task = ResumeGenerateTask(
        job_id=payload.job_id,
        title=payload.title,
        options=payload.options.model_dump(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    runner = get_resume_generate_runner()
    try:
        runner.start(task.id)
    except ResumeGenerateRunnerError as exc:
        # 启动失败（极端竞态：恰好有另一条任务刚被创建）：回滚这条空任务，不留孤儿。
        db.delete(task)
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GenerateTaskOut.model_validate(task)


@router.get("/generate/tasks/{task_id}", response_model=GenerateTaskOut)
def get_resume_generate_task(task_id: int, db: Session = Depends(get_db)):
    """查询一次生成任务的状态（前端 1.5s 轮询）。"""
    task = db.get(ResumeGenerateTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="生成任务不存在或已被删除")
    return GenerateTaskOut.model_validate(task)


@router.post("/generate/tasks/{task_id}/cancel", response_model=GenerateTaskOut)
def cancel_resume_generate_task(task_id: int, db: Session = Depends(get_db)):
    """取消进行中的生成任务。取消后**不落库**任何简历，任务标为 cancelled。"""
    task = db.get(ResumeGenerateTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="生成任务不存在或已被删除")
    runner = get_resume_generate_runner()
    try:
        runner.cancel(task_id)
    except ResumeGenerateRunnerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.expire_all()
    refreshed = db.get(ResumeGenerateTask, task_id)
    return GenerateTaskOut.model_validate(refreshed)


@router.post("/manual", response_model=ResumeOut, status_code=201)
def create_manual_resume(payload: ManualResumeRequest, db: Session = Depends(get_db)):
    """保存用户自行编写的简历，并可选关联岗位。"""
    job = db.get(Job, payload.job_id) if payload.job_id is not None else None
    if payload.job_id is not None and (job is None or trash.is_deleted(job)):
        raise HTTPException(status_code=404, detail="关联岗位不存在或已被删除")

    content = payload.content.model_dump()
    record = ResumeRecord(
        title=build_manual_title(payload.content, job, payload.title),
        job_id=job.id if job else None,
        job_title=job.title if job else payload.content.job_intent,
        company=job.company if job else "",
        content=content,
        warnings=[],
        source="manual",
        model="",
        enhancement_enabled=False,
        enhancement_level="balanced",
        parse_error="",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info("用户手写简历已保存 record_id=%s job=%s", record.id, record.job_title)
    return _to_resume_out(record)


def _to_resume_out(record: ResumeRecord) -> ResumeOut:
    return ResumeOut(
        id=record.id,
        title=record.title,
        job_id=record.job_id,
        job_title=record.job_title,
        company=record.company,
        source=record.source or "ai",
        favorite=record.favorite,
        model=record.model,
        enhancement_enabled=record.enhancement_enabled,
        enhancement_level=record.enhancement_level,
        note=record.note or "",
        template=record.template or DEFAULT_TEMPLATE,
        format_name=record.format_name or "",
        # 这个字段漏了不会报错，只会让保存成功却读不回来——界面上表现为"按了没反应"。
        format_config=record.format_config or {},
        page_limit=record.page_limit or 1,
        font_scale=record.font_scale or DEFAULT_FONT_SCALE,
        created_at=record.created_at,
        content=ResumeContent.model_validate(record.content),
        warnings=record.warnings or [],
        parse_error=record.parse_error,
    )


@router.get("", response_model=Page[ResumeBrief])
def list_resumes(
    db: Session = Depends(get_db),
    keyword: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    job_id: int | None = Query(default=None, ge=1),
    favorite: bool | None = Query(default=None),
    has_job: bool | None = Query(default=None),
):
    """列出简历。``has_job=false`` 只返回通用简历（未关联任何岗位）。"""
    query = db.query(ResumeRecord).filter(trash.live_only(ResumeRecord))
    if job_id is not None:
        query = query.filter(ResumeRecord.job_id == job_id)
    if has_job is not None:
        query = query.filter(
            ResumeRecord.job_id.is_not(None) if has_job else ResumeRecord.job_id.is_(None)
        )
    if favorite is not None:
        query = query.filter(ResumeRecord.favorite == favorite)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                ResumeRecord.title.like(like),
                ResumeRecord.job_title.like(like),
                ResumeRecord.company.like(like),
                cast(ResumeRecord.content, String).like(like),
            )
        )
    total = query.count()
    records = query.order_by(ResumeRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return Page(items=[ResumeBrief.model_validate(r) for r in records], total=total)


@router.post("/{resume_id}/suggestions", response_model=ResumeSuggestionsOut)
async def suggest_resume_edits(resume_id: int, db: Session = Depends(get_db)):
    """按需生成当前简历针对关联岗位的修改建议，不修改简历内容。"""
    record = db.get(ResumeRecord, resume_id)
    if record is None or trash.is_deleted(record):
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    if record.job_id is None:
        raise HTTPException(status_code=400, detail="这份简历没有关联的岗位，无法生成岗位化建议")
    job = db.get(Job, record.job_id)
    if job is None or trash.is_deleted(job):
        raise HTTPException(status_code=400, detail="关联岗位已被删除，无法生成岗位化建议")

    config = get_llm_config(db)
    if not config.base_url or not config.model:
        raise HTTPException(status_code=400, detail="请先在「设置」页配置大模型 API")
    try:
        profile = to_profile_out(get_profile_detail(db))
        resume = ResumeContent.model_validate(record.content)
        job_out = JobOut.model_validate(job)
        provider = create_provider(config)
        db.close()
        suggestions = await generate_suggestions(
            provider,
            resume,
            job_out,
            profile,
        )
    except LLMError as exc:
        logger.warning("简历岗位建议生成失败：%s", exc)
        raise HTTPException(status_code=502, detail=f"生成修改建议失败：{exc}") from exc
    except Exception as exc:  # noqa: BLE001 - 为用户提供可理解的失败提示
        logger.exception("简历岗位建议发生内部错误")
        raise HTTPException(status_code=502, detail="生成修改建议失败，请稍后重试") from exc
    return ResumeSuggestionsOut(
        job_id=job.id,
        job_title=job.title,
        company=job.company,
        suggestions=suggestions,
    )


@router.get("/{resume_id}", response_model=ResumeOut)
def get_resume(resume_id: int, db: Session = Depends(get_db)):
    record = db.get(ResumeRecord, resume_id)
    if record is None or trash.is_deleted(record):
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    return _to_resume_out(record)


@router.put("/{resume_id}", response_model=ResumeOut)
def update_resume(resume_id: int, payload: ResumeContent, db: Session = Depends(get_db)):
    """保存用户对生成简历的手工修改。"""
    record = db.get(ResumeRecord, resume_id)
    if record is None or trash.is_deleted(record):
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")

    record.content = payload.model_dump()
    # AI 生成阶段的告警不再适用于用户已手工确认过的内容。
    record.warnings = []
    record.parse_error = ""
    db.commit()
    db.refresh(record)
    return _to_resume_out(record)


@router.patch("/{resume_id}", response_model=ResumeOut)
def rename_resume(
    resume_id: int,
    payload: ResumeTitleUpdate,
    db: Session = Depends(get_db),
):
    """只更新简历名称；正文与生成告警都不受影响。"""
    record = db.get(ResumeRecord, resume_id)
    if record is None or trash.is_deleted(record):
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    record.title = payload.title
    db.commit()
    db.refresh(record)
    return _to_resume_out(record)


@router.patch("/{resume_id}/note", response_model=ResumeOut)
def update_resume_note(
    resume_id: int,
    payload: ResumeNoteUpdate,
    db: Session = Depends(get_db),
):
    """只更新简历备注（列表默认可见、详情可编辑）。"""
    record = trash.get_live(db, ResumeRecord, resume_id)
    if record is None:
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    record.note = payload.note
    db.commit()
    db.refresh(record)
    return _to_resume_out(record)


@router.patch("/{resume_id}/favorite", response_model=ResumeOut)
def update_resume_favorite(
    resume_id: int,
    payload: ResumeFavoriteUpdate,
    db: Session = Depends(get_db),
):
    """切换简历收藏状态，不修改简历正文。"""
    record = db.get(ResumeRecord, resume_id)
    if record is None or trash.is_deleted(record):
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    record.favorite = payload.favorite
    db.commit()
    db.refresh(record)
    return _to_resume_out(record)


@router.delete("/{resume_id}", status_code=204)
def delete_resume(resume_id: int, db: Session = Depends(get_db)):
    """移入回收站（软删除）。

    简历记录里有生成正文、版式覆盖与警告信息，是用户花了模型调用换来的；误删的代价远大于
    多留一行。彻底删除在「回收站」里单独提供（不可恢复，需二次确认）。
    """
    record = db.get(ResumeRecord, resume_id)
    if record is None or trash.is_deleted(record):
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    trash.soft_delete(db, "resume", record)
    db.commit()


@router.patch("/{resume_id}/layout", response_model=ResumeOut)
def update_resume_layout(
    resume_id: int, payload: ResumeLayoutUpdate, db: Session = Depends(get_db)
):
    """只调整版式参数（模板/页数/字号/按简历的覆盖），不重新生成内容。

    生成后内容偏多时，用户可以先增大页数或缩小字号再渲染，不必重跑模型。
    """
    record = db.get(ResumeRecord, resume_id)
    if record is None or trash.is_deleted(record):
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    # 样式模板名按"内置优先，其次用户自制"解析；格式模板单独存一份名字，渲染时再解析成
    # 具体的覆盖配置——这样用户改了格式模板，引用它的简历跟着变。
    record.template = resolved_style_name(db, payload.template)
    record.format_name = resolved_format_name(db, payload.format_name)
    # None = 这次不涉及这一项，保持原样；空字典 = 明确清掉覆盖。
    if payload.format_config is not None:
        record.format_config = validated_format_config(payload.format_config)
    record.page_limit = normalize_page_limit(payload.page_limit)
    record.font_scale = font_scale_spec(payload.font_scale)["name"]
    db.commit()
    db.refresh(record)
    return _to_resume_out(record)


@router.post("/{resume_id}/layout/analyze", response_model=LayoutAnalyzeOut)
def analyze_resume_layout(
    resume_id: int, payload: LayoutAnalyzeRequest, db: Session = Depends(get_db)
):
    """根据浏览器量到的实际高度给出版面诊断与逐档收紧方案。

    **高度必须由浏览器提供**：版面只有真正排版之后才存在，后端没有浏览器，也不该为了
    量一个高度去引一个无头浏览器依赖。所以这里的分工是——客户端负责量，规则全在这边。
    """
    record = db.get(ResumeRecord, resume_id)
    if record is None or trash.is_deleted(record):
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")

    measure = payload.measure
    current_config = record_format_config(db, record)
    room = fit_room_report(record.template, record.font_scale, current_config)
    diagnosis = diagnose(
        used_height=measure.used_height,
        page_content_height=measure.page_content_height,
        page_limit=measure.page_limit,
        has_fit_room=room["has_room"],
    )
    # 只有真的塞不下才需要给收紧方案：放得下时给一堆"再收紧一点"只会让人白改。
    ladder = (
        build_fit_ladder(record.template, record.font_scale, current_config)
        if diagnosis.status == STATUS_OVERFLOW
        else []
    )
    return LayoutAnalyzeOut(
        diagnosis=LayoutDiagnosisOut(
            status=diagnosis.status,
            status_label=diagnosis.status_label,
            summary=diagnosis.summary,
            fill=diagnosis.fill,
            pages_needed=diagnosis.pages_needed,
            page_limit=diagnosis.page_limit,
            pages=[LayoutPageOut(page=item.page, fill=item.fill) for item in diagnosis.pages],
            suggestions=[
                LayoutSuggestionOut(kind=item.kind, title=item.title, detail=item.detail)
                for item in diagnosis.suggestions
            ],
        ),
        fit_ladder=[
            LayoutFitCandidateOut(
                key=item.key, label=item.label, config=item.config, css=item.css
            )
            for item in ladder
        ],
        fit_room=LayoutFitRoomOut(**room),
    )


@router.post("/render")
def render_resume(payload: ResumeRenderRequest, db: Session = Depends(get_db)):
    """渲染为 HTML（生成完成后、未落库前的即时预览也走这里）。

    传入的模板名既可以是内置模板，也可以是用户自制的样式模板；格式模板同理。
    ``format_config`` 是这次渲染的临时覆盖（叠加在 format_name 之上），
    「自动一页」逐档试版式时用它，试出结果之前不落库。
    """
    template_name, template_html = resolve_style_template(db, payload.template)
    config = dict(resolve_format_config(db, payload.format_name))
    config.update(validated_format_config(payload.format_config))
    return Response(
        render_html(
            payload.content,
            template=template_name,
            page_limit=payload.page_limit,
            font_scale=payload.font_scale,
            format_config=config,
            template_html=template_html,
        ),
        media_type="text/html; charset=utf-8",
    )


def _get_live_resume(db: Session, resume_id: int) -> ResumeRecord:
    record = db.get(ResumeRecord, resume_id)
    if record is None or trash.is_deleted(record):
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    return record


def _export_record(
    db: Session,
    record: ResumeRecord,
    request: ExportRequest,
    *,
    allow_incomplete: bool,
) -> Response:
    """导出闸门 + 管线委托 + 响应头，是 GET / POST 两条导出路径的共用出口。"""
    resume = ResumeContent.model_validate(record.content)
    # 导出闸门：正文里还留着【待补】之类的标记时拦下来。带占位符的简历投出去，
    # 用户往往直到面试被问起才发现——这道检查的价值全在"导出那一刻"。
    if not allow_incomplete:
        incomplete = find_incomplete(resume)
        if incomplete:
            raise HTTPException(status_code=409, detail=incomplete_detail(incomplete))
    # 样式模板解析一次，json/md 用不到也不多花一次查询；html/pdf/docx 复用同一份解析结果。
    export_template, export_html = resolve_style_template(db, record.template)
    context = RenderContext(
        template=export_template,
        template_html=export_html,
        page_limit=record.page_limit,
        font_scale=record.font_scale,
        format_config=record_format_config(db, record),
    )
    try:
        artifact = build_export(request, resume, context)
    except ResumePDFError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WatermarkError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    headers: dict[str, str] = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(artifact.filename, safe='')}",
    }
    # 服务端 PDF/Word 用的是自己那套排版，页数未必等于用户选的上限（内容多时会多出一页）。
    # 把实际页数带回去，让界面能提示，而不是让用户下载完才发现。
    if artifact.pages is not None:
        headers[PDF_PAGES_HEADER] = str(artifact.pages)
    if artifact.page_limit is not None:
        headers[PDF_PAGE_LIMIT_HEADER] = str(artifact.page_limit)
    return Response(artifact.content, media_type=artifact.media_type, headers=headers)


@router.get("/{resume_id}/export")
def export_resume(
    resume_id: int,
    format: str = Query(..., pattern="^(json|md|html|pdf)$"),
    allow_incomplete: bool = Query(
        default=False,
        description="为真时允许导出仍含未完成标记的草稿；默认拦下并说明是哪几处",
    ),
    db: Session = Depends(get_db),
):
    """兼容旧的 GET 导出：仍限四种格式，内部委托管线。全参数导出走 ``POST``。"""
    record = _get_live_resume(db, resume_id)
    return _export_record(
        db,
        record,
        ExportRequest(format=format),
        allow_incomplete=allow_incomplete,
    )


@router.post("/{resume_id}/export")
def export_resume_with_options(
    resume_id: int,
    payload: ExportRequestSchema,
    db: Session = Depends(get_db),
):
    """全参数导出（R-16 / R-17）：格式、水印、脱敏、页边距、字号、页数、照片。

    脱敏作为管线前置步骤（``redact`` 是唯一实现），脱敏版是**独立导出文件**，不回写、
    不落库副本。响应头保留 ``X-Resume-Pages`` / ``X-Resume-Page-Limit``。
    """
    record = _get_live_resume(db, resume_id)
    privacy_options = PrivacyRedactionOptions(**payload.redact_options.model_dump())
    request = ExportRequest(
        format=payload.format,
        watermark=payload.watermark,
        redact=payload.redact,
        redact_options=privacy_options,
        margin_mm=payload.margin_mm,
        font_scale=payload.font_scale,
        page_limit=payload.page_limit,
        include_photo=payload.include_photo,
    )
    return _export_record(db, record, request, allow_incomplete=payload.allow_incomplete)


@router.post("/{resume_id}/redact", response_model=ResumeContent)
def redact_resume_preview(
    resume_id: int,
    payload: RedactionOptionsSchema,
    db: Session = Depends(get_db),
):
    """脱敏预览：返回脱敏后的 ``ResumeContent``，不落库、不改动原记录。"""
    record = _get_live_resume(db, resume_id)
    resume = ResumeContent.model_validate(record.content)
    options = PrivacyRedactionOptions(**payload.model_dump())
    return redact(resume, options)
