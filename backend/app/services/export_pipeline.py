"""通用导出管线：全仓库**唯一**的导出出口。

任何"把一份简历变成可下载文件"的路径都必须经过 :func:`build_export`：先按需脱敏
（``privacy.redact``），再按 ``FORMAT_RENDERERS`` 注册表选格式渲染器，最后可选地做水印
后处理（``watermark.apply_watermark``）。``api/resumes.py`` 不再分支散派格式。

渲染器是**既有实现**的适配壳：json/md/html 复用 ``exporter``，pdf 复用 ``pdf_exporter``，
docx/txt 是 R-16 新增的两个渲染器（Word 复用 ``ResumeLayout``，纯文本复用 Markdown 正文
结构去标记）。管线不新增任何缩放 / 版式逻辑——fit-scale 两套口径维持现状，由既有测试钉住。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..schemas.resume import ResumeContent
from .docx_exporter import build_resume_docx
from .exporter import build_filename, export_json, export_markdown, render_html
from .pdf_exporter import build_resume_pdf
from .privacy import RedactionOptions, redact
from .txt_exporter import export_txt
from .watermark import apply_watermark


@dataclass(frozen=True)
class ExportRequest:
    """一次导出请求。字段与 ``schemas/export.ExportRequest`` 一一对应，由 API 层转换。

    ``font_scale`` / ``page_limit`` 为 ``None`` 时表示沿用记录里存的值；``margin_mm``
    为 ``None`` 时沿用记录里的页边距（模板默认或 format_config.page_padding）。
    """

    format: str = "pdf"
    watermark: str = ""
    redact: bool = False
    redact_options: RedactionOptions | None = None
    margin_mm: float | None = None
    font_scale: str | None = None
    page_limit: int | None = None
    include_photo: bool = True


@dataclass(frozen=True)
class RenderContext:
    """渲染器所需、由调用方解析好的版式上下文。

    ``template`` / ``template_html`` 由 ``resume_template_store.resolve_style_template``
    解析一次后传入，避免每个渲染器各解析一次。``margin_mm`` 是导出时的页边距直接覆盖，
    ``include_photo`` 决定照片是否进入渲染（txt/md/json 本来就不含照片）。
    """

    template: str = "classic"
    template_html: str = ""
    page_limit: int = 1
    font_scale: str = "standard"
    format_config: dict | None = None
    margin_mm: float | None = None
    include_photo: bool = True


@dataclass(frozen=True)
class RenderedArtifact:
    """单个格式渲染器的输出。"""

    content: bytes
    media_type: str
    pages: int | None = None
    page_limit: int | None = None
    overflow: bool = False


@dataclass(frozen=True)
class ExportArtifact:
    """管线的最终产物。"""

    content: bytes
    filename: str
    media_type: str
    pages: int | None = None
    page_limit: int | None = None
    overflow: bool = False


def _render_json(resume: ResumeContent, context: RenderContext) -> RenderedArtifact:
    return RenderedArtifact(
        content=export_json(resume).encode("utf-8"),
        media_type="application/json; charset=utf-8",
    )


def _render_markdown(resume: ResumeContent, context: RenderContext) -> RenderedArtifact:
    return RenderedArtifact(
        content=export_markdown(resume).encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
    )


def _render_html(resume: ResumeContent, context: RenderContext) -> RenderedArtifact:
    return RenderedArtifact(
        content=render_html(
            resume,
            template=context.template,
            page_limit=context.page_limit,
            font_scale=context.font_scale,
            format_config=context.format_config,
            template_html=context.template_html,
        ).encode("utf-8"),
        media_type="text/html; charset=utf-8",
    )


def _render_pdf(resume: ResumeContent, context: RenderContext) -> RenderedArtifact:
    pdf = build_resume_pdf(
        resume,
        template=context.template,
        page_limit=context.page_limit,
        font_scale=context.font_scale,
        format_config=context.format_config,
        margin_mm=context.margin_mm,
        include_photo=context.include_photo,
    )
    return RenderedArtifact(
        content=pdf.content,
        media_type="application/pdf",
        pages=pdf.pages,
        page_limit=context.page_limit,
        overflow=pdf.overflow,
    )


def _render_docx(resume: ResumeContent, context: RenderContext) -> RenderedArtifact:
    docx = build_resume_docx(
        resume,
        template=context.template,
        page_limit=context.page_limit,
        font_scale=context.font_scale,
        format_config=context.format_config,
        margin_mm=context.margin_mm,
        include_photo=context.include_photo,
    )
    return RenderedArtifact(
        content=docx.content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        pages=docx.pages,
        page_limit=context.page_limit,
        overflow=docx.overflow,
    )


def _render_txt(resume: ResumeContent, context: RenderContext) -> RenderedArtifact:
    return RenderedArtifact(
        content=export_txt(resume).encode("utf-8"),
        media_type="text/plain; charset=utf-8",
    )


# 格式渲染器注册表：新增格式（docx/txt）时在此挂一个渲染器即可，不改管线。
FORMAT_RENDERERS: dict[str, Callable[[ResumeContent, RenderContext], RenderedArtifact]] = {
    "json": _render_json,
    "md": _render_markdown,
    "html": _render_html,
    "pdf": _render_pdf,
    "docx": _render_docx,
    "txt": _render_txt,
}


def build_export(
    request: ExportRequest,
    resume: ResumeContent,
    context: RenderContext,
) -> ExportArtifact:
    """把一份简历按请求导出成最终产物（脱敏 → 格式渲染 → 可选水印）。"""
    renderer = FORMAT_RENDERERS.get(request.format)
    if renderer is None:
        raise ValueError(f"不支持的导出格式：{request.format}")

    # 脱敏是可组合的前置步骤（共享知识第 7 条：规则只在 privacy 一份实现）。
    effective_resume = redact(resume, request.redact_options) if request.redact else resume

    # 请求里显式给出的版式覆盖优先，否则沿用记录里存的值。
    effective_context = RenderContext(
        template=context.template,
        template_html=context.template_html,
        page_limit=request.page_limit if request.page_limit is not None else context.page_limit,
        font_scale=request.font_scale or context.font_scale,
        format_config=context.format_config,
        margin_mm=request.margin_mm,
        include_photo=request.include_photo,
    )
    rendered = renderer(effective_resume, effective_context)
    content = rendered.content
    if request.watermark:
        content = apply_watermark(content, request.watermark, request.format)
    return ExportArtifact(
        content=content,
        filename=build_filename(effective_resume, request.format),
        media_type=rendered.media_type,
        pages=rendered.pages,
        page_limit=rendered.page_limit,
        overflow=rendered.overflow,
    )


__all__ = [
    "ExportArtifact",
    "ExportRequest",
    "FORMAT_RENDERERS",
    "RenderContext",
    "RenderedArtifact",
    "build_export",
]
