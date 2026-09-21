"""简历记录的落库与版式解析。

这里收拢了简历生成 / 手写 / 导出 / 分享包共用的几段逻辑，避免它们散落在路由层：

- ``save_record``：生成结果落库（流式与后台任务共用）。
- ``record_format_config``：一份简历**实际生效**的版式配置（具名格式模板 + 覆盖）。
  预览、导出、PDF、分享包都必须走这一个函数——各解析一次就会出现"预览收紧了、
  导出的 PDF 没变"，而用户只在下载后才看得到。
- ``resolved_format_name`` / ``resolved_style_name``：模板名按"能不能解析"归一，
  自制模板按**用户起的名字**存，不能拿 ``template_spec`` 偷偷换成内置模板。
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from ...models.job import Job
from ...models.resume import ResumeRecord
from ...schemas.job import JobOut
from ...schemas.resume import ResumeContent
from ..exporter import normalize_page_limit
from .resume_template_store import resolve_format_config, resolve_style_template
from .resume_templates import (
    DEFAULT_FONT_SCALE,
    DEFAULT_TEMPLATE,
    font_scale_spec,
    validated_format_config,
)

logger = logging.getLogger(__name__)


def record_format_config(db: Session, record: ResumeRecord) -> dict:
    """这份简历实际生效的版式配置：具名格式模板 + 只属于它的覆盖。"""
    config = dict(resolve_format_config(db, record.format_name))
    config.update(validated_format_config(record.format_config))
    return config


def resolved_format_name(db: Session, name: str) -> str:
    """格式模板名只有在能解析出配置时才存进记录；否则存空串（用模板自带版式）。"""
    key = (name or "").strip()
    if not key:
        return ""
    return key if resolve_format_config(db, key) else ""


def resolved_style_name(db: Session, name: str) -> str:
    """样式模板名：内置的存规范化名字，自制模板存**用户起的名字**。"""
    key = (name or "").strip()
    if not key:
        return DEFAULT_TEMPLATE
    builtin_name, user_html = resolve_style_template(db, key)
    return key if user_html else builtin_name


def build_manual_title(content: ResumeContent, job: Job | None, requested_title: str) -> str:
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


def save_record(
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
    commit: bool = True,
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
        template=resolved_style_name(db, template),
        format_name=resolved_format_name(db, format_name),
        page_limit=normalize_page_limit(page_limit),
        font_scale=font_scale_spec(font_scale)["name"],
        custom_instruction=custom_instruction.strip()[:2000],
    )
    db.add(record)
    if commit:
        db.commit()
        db.refresh(record)
        logger.info(
            "简历生成完成 record_id=%s model=%s job=%s",
            record.id,
            model,
            job.title if job is not None else "通用简历",
        )
    else:
        db.flush()
    return record
