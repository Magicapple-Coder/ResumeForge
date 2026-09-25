"""简历模板工作台接口：自制样式/格式模板的增删改查与预览渲染。"""
import base64
import logging
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.resume import ResumeRecord
from ..schemas.resume import ResumeContent
from ..schemas.resume_template import (
    ResumeTemplateCreate,
    ResumeTemplateDetail,
    ResumeTemplateOut,
    ResumeTemplateUpdate,
    TemplatePreviewRequest,
)
from ..services.attachments import (
    MAX_ATTACHMENT_BYTES,
    detect_file_format,
    document_mime_of_content,
    image_mime_of_content,
)
from ..services.document_text import extract_document_text
from ..services.exporter import render_html
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.settings_service import get_llm_config
from ..services.resume.resume_sample import sample_resume_content
from ..services.resume.resume_template_store import (
    TemplateError,
    create_user_template,
    delete_user_template,
    get_user_template,
    list_user_templates,
    resolve_format_config,
    resolve_style_template,
    update_user_template,
)
from ..services.resume.resume_template_import import (
    TemplateImportError,
    TemplateImportSource,
    derive_format_template,
    missing_format_keys,
)
from ..services.resume.resume_templates import (
    RESUME_TEMPLATES,
    TEMPLATES_DIR,
    font_scale_spec,
    template_spec,
    validated_format_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resume-templates", tags=["resume-templates"])

# Jinja 报错原文对用户没有意义（"…ResumeContent object has no attribute 'basic'"），
# 而这类错误在自制模板里最常见——写在右侧的字段名与真实字段名差一个词。所以把
# "属性不存在"翻译成"你写错的是哪个字段 + 正确的取法 + 可用字段清单"。
_MISSING_ATTRIBUTE_RE = re.compile(r"object has no attribute '([^']+)'")


def _template_error_detail(exc: Exception) -> str:
    """把模板渲染异常转成面向用户的提示。"""
    text = str(exc)
    matched = _MISSING_ATTRIBUTE_RE.search(text)
    if matched:
        field = matched.group(1)
        available = "、".join(ResumeContent.model_fields)
        return (
            f"模板里用到了不存在的字段「{field}」。简历内容都挂在 resume 上"
            f"（例如 {{{{ resume.name }}}}），可用字段：{available}；"
            '各分区正文建议直接用 {% include "_resume_sections.j2" %}。'
        )
    return f"模板渲染失败：{text}（请检查 Jinja 语法与 include 路径）"


def _to_detail(template) -> ResumeTemplateDetail:
    return ResumeTemplateDetail.model_validate(template)


def _template_or_404(db: Session, template_id: int):
    template = get_user_template(db, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="模板不存在或已被删除")
    return template


@router.get("/builtin")
def read_builtin_templates():
    """内置模板清单（只读）。用户模板见 ``GET /api/resume-templates``。"""
    return [
        {"name": item["name"], "label": item["label"], "description": item["description"]}
        for item in RESUME_TEMPLATES.values()
    ]


@router.get("", response_model=list[ResumeTemplateOut])
def read_user_templates(
    kind: str | None = Query(default=None, pattern="^(style|format)$"),
    db: Session = Depends(get_db),
):
    """自制模板列表（可按类型筛选）。内置模板不在这里，见 ``/api/resumes/templates``。"""
    return [ResumeTemplateOut.model_validate(item) for item in list_user_templates(db, kind)]


@router.post("", response_model=ResumeTemplateDetail, status_code=201)
def create_template(payload: ResumeTemplateCreate, db: Session = Depends(get_db)):
    """新建模板。样式模板的 HTML 会被清洗（去掉脚本与外链）并补齐 CSP。"""
    try:
        template = create_user_template(
            db,
            name=payload.name,
            kind=payload.kind,
            description=payload.description,
            html=payload.html,
            config=payload.config,
            source_name=payload.source_name,
        )
    except TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_detail(template)


@router.post("/import-from-file", response_model=ResumeTemplateDetail, status_code=201)
async def import_template_from_file(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    db: Session = Depends(get_db),
):
    """从上传的目标模板（图片 / PDF / DOCX）反推一份**格式模板**。

    为什么产出的是格式模板而不是样式模板：样式模板是整份 HTML，让模型长篇写 HTML 既
    容易出错也有注入面（仓库里已经因此限制"助手不能生成完整 HTML 模板"）。而"照着这份
    简历的样子来"实际需要的正是那几项版式参数——它们有白名单与范围校验，越界会被丢弃，
    落库安全。

    图片交给模型看（没有可直接抽取的结构化文字），文档用本地抽取（多数服务商不接受
    PDF 入参，也避免把原始文件发给第三方）。
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="文件是空的，请重新选择")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"文件不能超过 {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB，请压缩后再试",
        )

    filename = file.filename or ""
    filename = file.filename or ""
    # **按内容判定类型**，不按扩展名：改个后缀就能把任意文件塞给模型，这里不看名字。
    image_mime = image_mime_of_content(data)
    document_mime = document_mime_of_content(data)
    if image_mime is None and document_mime is None:
        detected, _ = detect_file_format(data)
        raise HTTPException(
            status_code=422,
            detail=(
                f"这个文件看起来是「{detected}」，不是可用的模板素材。"
                "请上传简历的图片（PNG / JPG / WEBP）或文档（PDF / DOCX）。"
            ),
        )
    source = TemplateImportSource(filename=filename)
    if image_mime is not None:
        # 图片交给模型看（复用图片附件那一份 MIME 判定）：与“截图识别”同一条路。
        source = TemplateImportSource(
            filename=filename,
            image_data_urls=[f"data:{image_mime};base64,{base64.b64encode(data).decode('ascii')}"],
        )
    else:
        # 文档走本地抽取：多数服务商不接受 PDF 入参，也避免把原始文件发给第三方。
        data_url = f"data:{document_mime};base64,{base64.b64encode(data).decode('ascii')}"
        try:
            extracted = extract_document_text(filename, document_mime, data_url)
        except ValueError as exc:
            # 抽不出文字（空文档、扫描件、加密 PDF）时说清原因，并指出替代路径。
            raise HTTPException(
                status_code=422,
                detail=f"{exc}。也可以把简历截图成图片上传，或手动新建格式模板。",
            ) from exc
        source = TemplateImportSource(filename=filename, text=extracted.text)

    config = get_llm_config(db)
    if not config.base_url or not config.model:
        raise HTTPException(status_code=400, detail="请先在「设置」页配置大模型 API")
    provider = create_provider(config)
    db.close()
    try:
        derived = await derive_format_template(provider, source)
    except TemplateImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"分析模板失败：{exc}") from exc
    except Exception as exc:  # noqa: BLE001 - 给用户可理解的失败提示
        logger.exception("模板导入分析发生内部错误")
        raise HTTPException(status_code=502, detail="分析模板失败，请稍后重试") from exc

    # 用户显式给了名字就用它，否则用模型起的名字。
    final_name = (name or "").strip() or str(derived["name"])
    try:
        template = create_user_template(
            db,
            name=final_name,
            kind="format",
            description=str(derived["description"]),
            config=derived["config"],
            source_name=filename,
        )
    except TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    missed = missing_format_keys(derived["config"])
    if missed:
        logger.info("模板导入未识别到的参数：%s", ",".join(missed))
    return _to_detail(template)


@router.get("/builtin-source")
def read_builtin_source(name: str = Query(..., min_length=1, max_length=64)):
    """读取某个内置模板的源码，用于「从内置模板复制一份」开始自制。

    内置模板本身是随包的 Jinja 文件，只能读不能改；给用户一份可编辑的副本，比让
    他从空白页开始写要容易得多。
    """
    spec = RESUME_TEMPLATES.get(name.strip())
    if spec is None:
        raise HTTPException(status_code=404, detail="没有这个内置模板")
    path = TEMPLATES_DIR / spec["file"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="内置模板文件缺失，请重新安装应用")
    return {"name": spec["name"], "label": spec["label"], "html": path.read_text(encoding="utf-8")}


@router.get("/{template_id}", response_model=ResumeTemplateDetail)
def read_template(template_id: int, db: Session = Depends(get_db)):
    return _to_detail(_template_or_404(db, template_id))


@router.put("/{template_id}", response_model=ResumeTemplateDetail)
def update_template(
    template_id: int, payload: ResumeTemplateUpdate, db: Session = Depends(get_db)
):
    template = _template_or_404(db, template_id)
    try:
        template = update_user_template(
            db,
            template,
            name=payload.name,
            description=payload.description,
            html=payload.html,
            config=payload.config,
            enabled=payload.enabled,
        )
    except TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_detail(template)


@router.delete("/{template_id}", status_code=204)
def remove_template(template_id: int, db: Session = Depends(get_db)):
    delete_user_template(db, _template_or_404(db, template_id))


def _preview_content(payload: TemplatePreviewRequest, db: Session) -> "object":
    if payload.content is not None:
        return payload.content
    if payload.resume_id is not None:
        record = db.get(ResumeRecord, payload.resume_id)
        if record is not None:
            from ..schemas.resume import ResumeContent

            return ResumeContent.model_validate(record.content)
    return sample_resume_content()


@router.post("/preview")
def preview_template(payload: TemplatePreviewRequest, db: Session = Depends(get_db)):
    """渲染模板预览（工作台的实时预览与"每个模板一眼看效果"都走这里）。

    传 ``html`` 就渲染这段（未保存的编辑内容）；否则用已保存模板或内置模板。
    """
    template_name = payload.template_name
    template_html = payload.html
    if not template_html:
        if payload.template_id is not None:
            saved = _template_or_404(db, payload.template_id)
            if saved.kind == "style":
                template_name = saved.name
        template_name, template_html = resolve_style_template(db, template_name)

    # 与真实渲染同口径：`/api/resumes/render` 与记录落库都是"先 resolve(format_name)、
    # 再用 format_config 逐键覆盖"（见 api/resumes.py 的 render_resume 与
    # _record_format_config）。预览此前是"有 format_config 就整份顶替 format_name"，
    # 于是前端一旦把当前字号系数（在 format_config 里）传进来，就会把 format_name 的
    # 版式（如 compact 的行高/页边距）整个丢掉，缩略图与用户实际生成的简历不一致。
    format_config = dict(resolve_format_config(db, payload.format_name))
    format_config.update(validated_format_config(payload.format_config))

    content = _preview_content(payload, db)
    try:
        html = render_html(
            content,
            template=template_spec(template_name)["name"],
            page_limit=payload.page_limit,
            font_scale=font_scale_spec(payload.font_scale)["name"],
            format_config=format_config,
            template_html=template_html,
        )
    except TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 模板写错时给出可读提示，而不是 500 堆栈
        logger.warning("模板预览渲染失败：%s", exc)
        raise HTTPException(status_code=400, detail=_template_error_detail(exc)) from exc
    return Response(html, media_type="text/html; charset=utf-8")
