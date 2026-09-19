"""导出产物的水印后处理：HTML 用 CSS 覆盖层，PDF 用 pypdf 叠加，Word 用页眉。

这是水印的**唯一实现处**。水印是"后处理"：输入已经是渲染好的字节，输出加水印后的字节，
不参与任何排版 / 缩放决策——那部分由 HTML 的 ``_resume_fit_script.j2`` 与 PDF 的
``pdf_exporter.decide_fit_scale`` 各自负责，本模块不加一层新口径。

- HTML：注入一层半透明、固定定位、不可点击的水印文案，不影响正文布局。
- PDF：生成一张 A4 水印页，再用 pypdf 逐页叠加（``over=True`` 让水印盖在内容之上）。
- Word：把文案写进每个节的页眉（居中、浅灰），随 Word 逐页显示。
- 纯文本（txt）/ Markdown / JSON 不支持水印（没有版面概念），抛明确错误。
"""
from __future__ import annotations

import html as html_module
import logging
from io import BytesIO

logger = logging.getLogger(__name__)


class WatermarkError(Exception):
    """对外暴露的水印处理错误，message 可直接展示给用户。"""


def _apply_html_watermark(content: bytes, text: str) -> bytes:
    safe = html_module.escape(text, quote=True)
    overlay = (
        '<div aria-hidden="true" style="position:fixed;inset:0;display:flex;'
        "align-items:center;justify-content:center;pointer-events:none;z-index:9999;"
        f'color:rgba(0,0,0,0.08);font-size:64px;transform:rotate(-30deg);">{safe}</div>'
    )
    document = content.decode("utf-8")
    if "</body>" in document:
        document = document.replace("</body>", f"{overlay}</body>", 1)
    else:
        document += overlay
    return document.encode("utf-8")


def _build_watermark_pdf(text: str) -> bytes:
    from fpdf import FPDF

    # 复用 pdf_exporter 的字体候选清单（那是本仓库唯一的中文字体来源），不另写一份。
    from .pdf_exporter import FONT_FAMILY, _resolve_font_paths

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    fonts = _resolve_font_paths()
    if fonts is None:
        # 无中文字体时退回内置 Helvetica：中文水印会缺字，但不阻断导出。
        pdf.set_font("helvetica", "", 48)
    else:
        regular, _bold = fonts
        try:
            pdf.add_font(FONT_FAMILY, "", regular)
        except Exception as exc:  # noqa: BLE001 - 字体解析失败退回内置字体
            logger.warning("水印中文字体加载失败，退回内置字体：%s", exc)
            pdf.set_font("helvetica", "", 48)
        else:
            pdf.set_font(FONT_FAMILY, "", 48)
    pdf.set_text_color(200, 200, 200)
    pdf.set_xy(10, 140)
    # 居中一行灰色水印文案；不做旋转以规避 fpdf2 各版本 rotate API 的差异。
    pdf.multi_cell(0, 24, text, align="C")
    return bytes(pdf.output())


def _apply_pdf_watermark(content: bytes, text: str) -> bytes:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:  # pragma: no cover - pypdf 已在 requirements 中锁定
        raise WatermarkError("缺少 pypdf，无法为 PDF 添加水印") from exc

    watermark = _build_watermark_pdf(text)
    reader = PdfReader(BytesIO(content))
    stamp = PdfReader(BytesIO(watermark)).pages[0]
    # clone_from 把整份 reader 深拷贝进 writer，页面的间接引用于是归属 writer——
    # 这样 merge_page 内部的 replace_contents() 走「已挂到 writer」的路径，避免
    # pypdf 对「页还挂在 reader 上却改内容」的弃用告警（pypdf 7 会移除该路径）。
    writer = PdfWriter(clone_from=reader)
    for page in writer.pages:
        page.merge_page(stamp, over=True)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _apply_docx_watermark(content: bytes, text: str) -> bytes:
    """把水印文案写进 Word 每个节的页眉（居中、浅灰、大字号）。

    python-docx 只写 XML 里的字体名与字号，最终渲染由 Word 完成；这里不追求与 PDF 的
    倾斜角度完全一致，只保证"每一页都有同一行水印"这个语义。
    """
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.shared import Pt, RGBColor
    except ImportError as exc:  # pragma: no cover - python-docx 已在 requirements 中锁定
        raise WatermarkError("缺少 python-docx，无法为 Word 添加水印") from exc

    document = Document(BytesIO(content))
    for section in document.sections:
        header = section.header
        paragraph = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(text)
        run.font.size = Pt(36)
        run.font.color.rgb = RGBColor(200, 200, 200)
        run.font.name = "微软雅黑"
        run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "微软雅黑")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def apply_watermark(content: bytes, text: str, format: str) -> bytes:
    """给已渲染的导出产物加水印；``text`` 为空时原样返回。"""
    if not text:
        return content
    fmt = (format or "").strip().lower()
    if fmt in ("html", "htm"):
        return _apply_html_watermark(content, text)
    if fmt == "pdf":
        return _apply_pdf_watermark(content, text)
    if fmt in ("docx", "doc"):
        return _apply_docx_watermark(content, text)
    raise WatermarkError(f"不支持为格式 {format!r} 添加水印")


__all__ = ["WatermarkError", "apply_watermark"]
