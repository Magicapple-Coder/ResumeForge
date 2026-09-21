"""水印后处理：三端统一的「倾斜 + 重复平铺 + 半透明」。

水印是导出后处理，必须钉住这几件事：
- HTML 路径注入的是一层**平铺**覆盖层，且水印文案绝不能被当作 HTML 解析（XSS）；
- PDF 路径叠完**页数不变**、原正文仍在，且水印确实是**重复多份**（平铺）而不是单行；
- Word 路径写入的是**斜向 VML WordArt**（不是普通页眉文字）；
- 空文本直接透传（不能凭空多出一层空水印），不支持的格式明确报错。
"""
import urllib.parse
from io import BytesIO

import pytest
from docx import Document
from pypdf import PdfReader

from app.services.docx_exporter import build_resume_docx
from app.services.pdf_exporter import build_resume_pdf, font_available
from app.services.resume.resume_sample import sample_resume_content
from app.services.watermark import WatermarkError, apply_watermark

needs_font = pytest.mark.skipif(not font_available(), reason="本机没有可用的中文字体")


def test_empty_text_passes_through():
    content = b"<html></html>"
    assert apply_watermark(content, "", "html") == content


def test_html_watermark_escapes_and_injects_tiled_overlay():
    content = "<html><body><p>正文</p></body></html>".encode("utf-8")
    out = apply_watermark(content, '<script>"内部水印"</script>', "html")
    text = out.decode("utf-8")
    decoded = urllib.parse.unquote(text)
    # 注入的是"固定定位 + 平铺"的覆盖层（倾斜 + 重复），而不是一坨居中文字。
    assert "position:fixed" in text
    assert "background-repeat:repeat" in text
    assert "rotate(-30" in decoded
    # 文案原样出现（在 SVG 数据里，URL 解码后可见）。
    assert "内部水印" in decoded
    # 特殊字符必须被转义，绝不能把水印文案当 HTML 解析（XSS 防线）。
    assert "<script>" not in decoded
    assert "&lt;script&gt;" in decoded
    # 正文不受影响。
    assert "<p>正文</p>" in text


def test_html_watermark_appends_when_no_body_tag():
    content = b"<html>hello</html>"
    out = apply_watermark(content, "水印", "html")
    text = out.decode("utf-8")
    assert text.startswith("<html>hello</html>")
    assert "background-repeat:repeat" in text
    assert "水印" in urllib.parse.unquote(text)


def test_unsupported_format_raises():
    with pytest.raises(WatermarkError):
        apply_watermark(b"plain text", "水印", "txt")


@needs_font
def test_pdf_watermark_tiles_and_keeps_page_count_and_original_text():
    pdf = build_resume_pdf(sample_resume_content(), template="classic", page_limit=1)
    before = PdfReader(BytesIO(pdf.content))

    out = apply_watermark(pdf.content, "内部使用", "pdf")
    after = PdfReader(BytesIO(out))

    # 叠加不增删页。
    assert len(after.pages) == len(before.pages)
    # 水印文案与原文内容都在（叠加是合并，不是覆盖删除）。
    merged = "\n".join((page.extract_text() or "") for page in after.pages)
    assert "内部使用" in merged
    assert "个人总结" in merged or "实习/工作经历" in merged
    # 平铺：同一页里水印不止出现一次（单行居中水印只会出现一次）。
    assert merged.count("内部使用") >= 2


def test_docx_watermark_writes_a_diagonal_art_in_header():
    """Word 水印是每个节页眉里的斜向半透明 WordArt（VML 形状），不是普通文字。"""
    docx = build_resume_docx(sample_resume_content(), template="classic", page_limit=1)
    out = apply_watermark(docx.content, "内部使用", "docx")

    document = Document(BytesIO(out))
    header_xml = "".join(section.header._element.xml for section in document.sections)
    assert header_xml, "应当写进了页眉"
    assert "ResumeForgeWatermark" in header_xml  # VML 水印形状
    assert "rotation:315" in header_xml  # 倾斜
    assert "内部使用" in header_xml  # 文案
