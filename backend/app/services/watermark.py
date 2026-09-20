"""导出产物的水印后处理：HTML / PDF / Word 三端统一为「倾斜 + 重复平铺 + 半透明」。

这是水印的**唯一实现处**。水印是"后处理"：输入已经是渲染好的字节，输出加水印后的字节，
不参与任何排版 / 缩放决策——那部分由 HTML 的 ``_resume_fit_script.j2`` 与 PDF 的
``pdf_exporter.decide_fit_scale`` 各自负责，本模块不加一层新口径。

- HTML：注入一层固定定位的覆盖层，背景是一张**内联 SVG 平铺图**（文案旋转后按 repeat 铺满）。
- PDF：生成一张 A4 水印页（文案按错位网格旋转平铺），再用 pypdf 逐页叠加（``over=True``）。
- Word：在每节的页眉里放一个**斜向 WordArt**（VML 形状、半透明填充、置于正文之下）。
- 纯文本（txt）/ Markdown / JSON 不支持水印（没有版面概念），抛明确错误。
"""
from __future__ import annotations

import html as html_module
import logging
import urllib.parse
from contextlib import nullcontext
from io import BytesIO

logger = logging.getLogger(__name__)


class WatermarkError(Exception):
    """对外暴露的水印处理错误，message 可直接展示给用户。"""


# ===== HTML：内联 SVG 平铺背景 =====
# 一块瓦片画一个旋转后的文案，浏览器按 repeat 铺满整页 —— 这就是"重复多个、倾斜、半透明"。
_HTML_TILE_WIDTH_PX = 340
_HTML_TILE_HEIGHT_PX = 240
_HTML_TILE_ANGLE = -30
_HTML_TILE_FONT_PX = 30
_HTML_TILE_COLOR = "rgba(0,0,0,0.10)"


def _html_tile_data_uri(text: str) -> str:
    """把一块含旋转文案的瓦片编成 data URI（只编码 SVG 本体，保留 data: 前缀）。"""
    safe = html_module.escape(text, quote=True)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_HTML_TILE_WIDTH_PX}" '
        f'height="{_HTML_TILE_HEIGHT_PX}">'
        f'<text x="24" y="150" transform="rotate({_HTML_TILE_ANGLE} 24 150)" '
        f'fill="{_HTML_TILE_COLOR}" font-size="{_HTML_TILE_FONT_PX}" '
        'font-family="Microsoft YaHei, PingFang SC, Noto Sans CJK SC, sans-serif">'
        f"{safe}</text></svg>"
    )
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg, safe="")


def _apply_html_watermark(content: bytes, text: str) -> bytes:
    uri = _html_tile_data_uri(text)
    overlay = (
        '<div aria-hidden="true" style="position:fixed;inset:0;pointer-events:none;'
        "z-index:9999;"
        f"background-image:url(&quot;{uri}&quot;);background-repeat:repeat;"
        '"></div>'
    )
    document = content.decode("utf-8")
    if "</body>" in document:
        document = document.replace("</body>", f"{overlay}</body>", 1)
    else:
        document += overlay
    return document.encode("utf-8")


# ===== PDF：错位网格 + 旋转，铺满 A4 =====
_PDF_TILE_STEP_X_MM = 92.0
_PDF_TILE_STEP_Y_MM = 70.0
_PDF_TILE_ANGLE = -30
_PDF_WATERMARK_FONT_PT = 34.0
_PDF_WATERMARK_GRAY = (185, 185, 185)
_PDF_WATERMARK_OPACITY = 0.45


def _tile_watermark(pdf, text: str) -> None:
    """把文案旋转后按错位网格铺满 A4（210×297mm）。"""
    y = 24.0
    row = 0
    while y < 297.0:
        x = 8.0 + (_PDF_TILE_STEP_X_MM / 2 if row % 2 else 0.0)
        while x < 211.0:
            with pdf.rotation(angle=_PDF_TILE_ANGLE, x=x, y=y):
                pdf.text(x, y, text)
            x += _PDF_TILE_STEP_X_MM
        y += _PDF_TILE_STEP_Y_MM
        row += 1


def _build_watermark_pdf(text: str) -> bytes:
    from fpdf import FPDF

    # 复用 pdf_exporter 的字体候选清单（那是本仓库唯一的中文字体来源），不另写一份。
    from .pdf_exporter import FONT_FAMILY, _resolve_font_paths

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    fonts = _resolve_font_paths()
    if fonts is None:
        # 无中文字体时退回内置 Helvetica：中文水印会缺字，但不阻断导出。
        pdf.set_font("helvetica", "", _PDF_WATERMARK_FONT_PT)
    else:
        regular, _bold = fonts
        try:
            pdf.add_font(FONT_FAMILY, "", regular)
        except Exception as exc:  # noqa: BLE001 - 字体解析失败退回内置字体
            logger.warning("水印中文字体加载失败，退回内置字体：%s", exc)
            pdf.set_font("helvetica", "", _PDF_WATERMARK_FONT_PT)
        else:
            pdf.set_font(FONT_FAMILY, "", _PDF_WATERMARK_FONT_PT)
    pdf.set_text_color(*_PDF_WATERMARK_GRAY)

    # 半透明：PDF 的 ExtGState 填充透明度对文字填充同样生效；某些版本不支持时退化为浅灰，
    # 观感仍成立（浅灰本身在白底上就近似半透明），绝不因为透明度拿不到就中断导出。
    try:
        context = pdf.local_context(fill_opacity=_PDF_WATERMARK_OPACITY)
    except Exception:  # noqa: BLE001 - 老版本 fpdf2 无透明度 API
        logger.warning("当前 fpdf2 不支持水印透明度，退化为浅灰平铺")
        context = nullcontext()
    with context:
        _tile_watermark(pdf, text)
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


# ===== Word：页眉里的斜向半透明 WordArt（VML）=====
_VML_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:o="urn:schemas-microsoft-com:office:office"'
)


def _docx_watermark_run_xml(text: str) -> str:
    """一个含斜向 WordArt 的 `<w:r>`；VML 形状按 Word 水印惯例置于正文之下、半透明。"""
    safe = html_module.escape(text, quote=True)
    return (
        f"<w:r {_VML_NS}>"
        "<w:rPr><w:noProof/></w:rPr>"
        "<w:pict>"
        '<v:shapetype id="_x0000_t136" coordsize="21600,21600" o:spt="136" adj="10800" '
        'path="m@7,l@8,m@5,21600l@6,21600e">'
        "<v:formulas>"
        '<v:f eqn="sum #0 0 10800"/><v:f eqn="prod #0 2 1"/><v:f eqn="sum 21600 0 @1"/>'
        '<v:f eqn="sum 0 0 @2"/><v:f eqn="sum 21600 0 @3"/><v:f eqn="if @0 @3 0"/>'
        '<v:f eqn="if @0 21600 @1"/><v:f eqn="if @0 0 @2"/><v:f eqn="if @0 @4 21600"/>'
        '<v:f eqn="mid @5 @6"/><v:f eqn="mid @8 @5"/><v:f eqn="mid @7 @8"/>'
        '<v:f eqn="mid @6 @7"/><v:f eqn="sum @6 0 @5"/>'
        "</v:formulas>"
        '<v:path textpathok="t" o:connecttype="custom" '
        'o:connectlocs="@9,0;@10,10800;@11,21600;@12,10800" '
        'o:connectangles="270,180,90,0"/>'
        '<v:textpath on="t" fitshape="t"/>'
        "</v:shapetype>"
        '<v:shape id="ResumeForgeWatermark" o:spid="_x0000_s2049" type="#_x0000_t136" '
        "style="
        '"position:absolute;margin-left:0;margin-top:0;width:420pt;height:150pt;'
        "rotation:315;z-index:-251658752;mso-position-horizontal:center;"
        "mso-position-horizontal-relative:margin;mso-position-vertical:center;"
        'mso-position-vertical-relative:margin"'
        ' fillcolor="#b8b8b8" stroked="f">'
        '<v:fill opacity="0.5"/>'
        f'<v:textpath style="font-family:&quot;微软雅黑&quot;;font-size:1pt" '
        f'string="{safe}"/>'
        "</v:shape>"
        "</w:pict>"
        "</w:r>"
    )


def _apply_docx_watermark(content: bytes, text: str) -> bytes:
    """在 Word 每个节的页眉里放一个斜向半透明 WordArt，随 Word 逐页显示。

    VML 形状由 Word 渲染；这里保证"每页都有一枚倾斜、半透明的水印"这一语义。
    """
    try:
        from docx import Document
        from docx.oxml import parse_xml
    except ImportError as exc:  # pragma: no cover - python-docx 已在 requirements 中锁定
        raise WatermarkError("缺少 python-docx，无法为 Word 添加水印") from exc

    document = Document(BytesIO(content))
    run = parse_xml(_docx_watermark_run_xml(text))
    for section in document.sections:
        header = section.header
        header.is_linked_to_previous = False
        paragraph = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
        paragraph._p.append(run)
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
