"""简历接口：流式生成（SSE）、历史记录、预览渲染与导出。"""
import json
import logging
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import cast, or_, String
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models.job import Job
from ..models.resume import ResumeRecord
from ..schemas.common import Page
from ..schemas.job import JobOut
from ..schemas.resume import (
    GenerateRequest,
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
    ResumeOut,
    ResumeRenderRequest,
    ResumeSuggestionsOut,
    ResumeTitleUpdate,
)
from ..services.claims import build_baseline
from ..services.exporter import (
    build_filename,
    export_json,
    export_markdown,
    normalize_page_limit,
    render_html,
)
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.pdf_exporter import ResumePDFError, build_resume_pdf, font_available
from ..services.profile_service import get_profile_detail, to_profile_out
from ..services.resume_completeness import find_incomplete, incomplete_detail
from ..services.resume_generator import ResumeGenerator
from ..services.resume_layout import (
    STATUS_OVERFLOW,
    build_fit_ladder,
    diagnose,
    fit_room_report,
)
from ..services.resume_suggestions import generate_suggestions
from ..services.resume_template_store import (
    custom_format_options,
    custom_template_options,
    resolve_format_config,
    resolve_style_template,
)
from ..services.resume_templates import (
    DEFAULT_FONT_SCALE,
    DEFAULT_PAGE_LIMIT,
    DEFAULT_TEMPLATE,
    FORMAT_PRESETS,
    font_scale_options,
    font_scale_spec,
    format_field_options,
    validated_format_config,
    template_options_with_custom,
)
from ..services.settings_service import get_llm_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resumes", tags=["resumes"])

# 支持的导出格式
_EXPORT_FORMATS = {
    "json": "application/json; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
}

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
        "pdf_direct_available": font_available(),
    }


def _format_sse(payload: dict) -> str:
    """把事件转成 SSE 数据帧。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _record_format_config(db: Session, record: ResumeRecord) -> dict:
    """这份简历实际生效的版式配置：具名格式模板 + 只属于它的覆盖。

    预览、导出、PDF 都必须走这一个函数——三处各解析一次的话，很容易出现
    "预览里字号收紧了、导出的 PDF 没有"，而用户只有在下载之后才会发现。
    """
    config = dict(resolve_format_config(db, record.format_name))
    config.update(validated_format_config(record.format_config))
    return config


def _resolved_format_name(db: Session, name: str) -> str:
    """格式模板名只有在能解析出配置时才存进记录；否则存空串（用模板自带版式）。"""
    key = (name or "").strip()
    if not key:
        return ""
    return key if resolve_format_config(db, key) else ""


def _resolved_style_name(db: Session, name: str) -> str:
    """样式模板名：内置的存规范化名字，自制模板存**用户起的名字**。

    不能用 ``template_spec()`` 的结果：它会把查不到的名字悄悄换成默认内置模板，于是
    "用自制模板生成"的记录里存的是 classic，重新打开预览就变回内置样式——用户以为
    自己选的模板没生效。
    """
    key = (name or "").strip()
    if not key:
        return DEFAULT_TEMPLATE
    builtin_name, user_html = resolve_style_template(db, key)
    return key if user_html else builtin_name


@router.post("/generate")
async def generate_resume(payload: GenerateRequest, db: Session = Depends(get_db)):
    """流式生成简历（SSE）。

    ``job_id`` 为空表示生成**通用简历**（不针对任何岗位）。事件类型见
    services/resume_generator.py 文档；生成结果成功落库后，依次发送携带记录 id 的
    saved 事件和最终 done 事件。
    """
    job = db.get(Job, payload.job_id) if payload.job_id is not None else None
    if payload.job_id is not None and job is None:
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
                    record = _save_record(
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


def _save_record(
    db: Session,
    content: dict,
    warnings: list[str],
    job: JobOut | None,
    raw: str,
    model: str,
    enhancement_enabled: bool,
    enhancement_level: str,
    source: str = "ai",
    requested_title: str = "",
    template: str = DEFAULT_TEMPLATE,
    format_name: str = "",
    page_limit: int = 1,
    font_scale: str = DEFAULT_FONT_SCALE,
    custom_instruction: str = "",
) -> ResumeRecord:
    """生成结果落库（在流结束后的同一请求内调用）。

    ``job is None`` 是通用简历：没有公司与岗位，``job_title`` 沿用正文里的求职意向
    （与 ``POST /manual`` 在无岗位时已有的约定一致），标题回退到「…-通用简历-时间戳」。
    """
    name = str(content.get("name") or "简历").strip()[:48]
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    if job is None:
        company = ""
        job_title = str(content.get("job_intent") or "").strip()[:128]
        title = f"{name}-通用简历-{timestamp}"
    else:
        company = (job.company.strip() or "未命名公司")[:80]
        job_title = job.title.strip()[:80]
        title = f"{name}-{company}-{job_title}-{timestamp}"
    title = requested_title.strip()[:256] or title
    record = ResumeRecord(
        title=title,
        job_id=job.id if job is not None else None,
        job_title=job_title,
        company=company,
        content=content,
        warnings=warnings,
        source=source,
        model=model,
        enhancement_enabled=enhancement_enabled,
        enhancement_level=enhancement_level,
        # 与 PATCH 路径同一套解析：自制样式模板要按**名字**存下来，不能拿 template_spec()
        # 去归一——那个函数会把不认识的模板名悄悄换成 classic，于是用户用自制模板生成的
        # 简历一重开就变回内置样式。内置模板仍然只存规范化后的名字。
        template=_resolved_style_name(db, template),
        # 格式模板按名字存一份：生成时选的版式要跟着记录走，否则重新打开预览/导出会
        # 悄悄退回模板自带版式（用户会以为"我选的版式没生效"）。
        format_name=_resolved_format_name(db, format_name),
        page_limit=normalize_page_limit(page_limit),
        font_scale=font_scale_spec(font_scale)["name"],
        custom_instruction=custom_instruction.strip()[:2000],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info(
        "简历生成完成 record_id=%s model=%s job=%s",
        record.id,
        model,
        job.title if job is not None else "通用简历",
    )
    return record


def _build_manual_title(content: ResumeContent, job: Job | None, requested_title: str) -> str:
    """生成手写简历默认标题；允许用户传入标题以便在简历中心区分版本。"""
    title = requested_title.strip()
    if title:
        return title[:256]
    name = content.name.strip()[:48] or "未命名"
    company = (job.company.strip() if job else "").strip()[:80]
    job_title = (job.title.strip() if job else "").strip()[:80]
    target = "-".join(part for part in (company, job_title) if part) or "自定义简历"
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    return f"{name}-{target}-{timestamp}"[:256]


@router.post("/manual", response_model=ResumeOut, status_code=201)
def create_manual_resume(payload: ManualResumeRequest, db: Session = Depends(get_db)):
    """保存用户自行编写的简历，并可选关联岗位。"""
    job = db.get(Job, payload.job_id) if payload.job_id is not None else None
    if payload.job_id is not None and job is None:
        raise HTTPException(status_code=404, detail="关联岗位不存在或已被删除")

    content = payload.content.model_dump()
    record = ResumeRecord(
        title=_build_manual_title(payload.content, job, payload.title),
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
    query = db.query(ResumeRecord)
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
    if record is None:
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    if record.job_id is None:
        raise HTTPException(status_code=400, detail="这份简历没有关联的岗位，无法生成岗位化建议")
    job = db.get(Job, record.job_id)
    if job is None:
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
    if record is None:
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    return _to_resume_out(record)


@router.put("/{resume_id}", response_model=ResumeOut)
def update_resume(resume_id: int, payload: ResumeContent, db: Session = Depends(get_db)):
    """保存用户对生成简历的手工修改。"""
    record = db.get(ResumeRecord, resume_id)
    if record is None:
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
    if record is None:
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    record.title = payload.title
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
    if record is None:
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    record.favorite = payload.favorite
    db.commit()
    db.refresh(record)
    return _to_resume_out(record)


@router.delete("/{resume_id}", status_code=204)
def delete_resume(resume_id: int, db: Session = Depends(get_db)):
    record = db.get(ResumeRecord, resume_id)
    if record is None:
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    db.delete(record)
    db.commit()


@router.patch("/{resume_id}/layout", response_model=ResumeOut)
def update_resume_layout(
    resume_id: int, payload: ResumeLayoutUpdate, db: Session = Depends(get_db)
):
    """只调整版式参数（模板/页数/字号/按简历的覆盖），不重新生成内容。

    生成后内容偏多时，用户可以先增大页数或缩小字号再渲染，不必重跑模型。
    """
    record = db.get(ResumeRecord, resume_id)
    if record is None:
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    # 样式模板名按"内置优先，其次用户自制"解析；格式模板单独存一份名字，渲染时再解析成
    # 具体的覆盖配置——这样用户改了格式模板，引用它的简历跟着变。
    record.template = _resolved_style_name(db, payload.template)
    record.format_name = _resolved_format_name(db, payload.format_name)
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
    if record is None:
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")

    measure = payload.measure
    current_config = _record_format_config(db, record)
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
    record = db.get(ResumeRecord, resume_id)
    if record is None:
        raise HTTPException(status_code=404, detail="简历记录不存在或已被删除")
    resume = ResumeContent.model_validate(record.content)
    # 导出闸门：正文里还留着【待补】之类的标记时拦下来。带占位符的 PDF 投出去，
    # 用户往往直到面试被问起才发现——这道检查的价值全在"导出那一刻"。
    if not allow_incomplete:
        incomplete = find_incomplete(resume)
        if incomplete:
            raise HTTPException(status_code=409, detail=incomplete_detail(incomplete))
    headers: dict[str, str] = {}
    if format == "json":
        content, media_type = export_json(resume), _EXPORT_FORMATS["json"]
    elif format == "md":
        content, media_type = export_markdown(resume), _EXPORT_FORMATS["md"]
    elif format == "html":
        export_template, export_html = resolve_style_template(db, record.template)
        content, media_type = (
            render_html(
                resume,
                template=export_template,
                page_limit=record.page_limit,
                font_scale=record.font_scale,
                format_config=_record_format_config(db, record),
                template_html=export_html,
            ),
            _EXPORT_FORMATS["html"],
        )
    else:
        try:
            pdf = build_resume_pdf(
                resume,
                template=resolve_style_template(db, record.template)[0],
                page_limit=record.page_limit,
                font_scale=record.font_scale,
                format_config=_record_format_config(db, record),
            )
        except ResumePDFError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        content, media_type = pdf.content, _EXPORT_FORMATS["pdf"]
        # 服务端 PDF 用的是自己那套排版，页数未必等于用户选的上限（内容多时会多出一页）。
        # 把实际页数带回去，让界面能提示，而不是让用户下载完才发现。
        headers[PDF_PAGES_HEADER] = str(pdf.pages)
        headers[PDF_PAGE_LIMIT_HEADER] = str(record.page_limit)
    filename = build_filename(resume, format)
    headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
    return Response(content, media_type=media_type, headers=headers)
