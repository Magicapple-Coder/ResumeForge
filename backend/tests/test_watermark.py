"""水印后处理：HTML 转义 / 注入、PDF 叠加、空文本透传、不支持格式报错。

这是 QA 早先标记的「watermark.py 零测试」缺口。水印是导出后处理，必须钉住三件事：
HTML 路径不能把水印文案当 HTML 解析（XSS），PDF 路径叠完页数不变、原正文仍在，
空文本直接透传（不能凭空多出一层空水印）。
"""
from io import BytesIO

import pytest
from docx import Document
from pypdf import PdfReader

from app.services.docx_exporter import build_resume_docx
from app.services.pdf_exporter import build_resume_pdf, font_available
from app.services.resume_sample import sample_resume_content
from app.services.watermark import WatermarkError, apply_watermark

needs_font = pytest.mark.skipif(not font_available(), reason="本机没有可用的中文字体")


def test_empty_text_passes_through():
    content = b"<html></html>"
    assert apply_watermark(content, "", "html") == content


def test_html_watermark_escapes_and_injects_overlay():
    content = "<html><body><p>正文</p></body></html>".encode("utf-8")
    out = apply_watermark(content, '<script>"内部水印"</script>', "html")
    text = out.decode("utf-8")
    # 注入半透明覆盖层，且文案原样出现。
    assert "position:fixed" in text
    assert "内部水印" in text
    # 特殊字符必须被转义，绝不能把水印文案当 HTML 解析（XSS 防线）。
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    # 正文不受影响。
    assert "<p>正文</p>" in text


def test_html_watermark_appends_when_no_body_tag():
    content = b"<html>hello</html>"
    out = apply_watermark(content, "水印", "html")
    assert "水印" in out.decode("utf-8")


def test_unsupported_format_raises():
    with pytest.raises(WatermarkError):
        apply_watermark(b"plain text", "水印", "txt")


@needs_font
def test_pdf_watermark_keeps_page_count_and_original_text():
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


def test_docx_watermark_writes_header_text():
    """Word 水印写入每个节的页眉，重开文档后能读到同一行水印文案。"""
    docx = build_resume_docx(sample_resume_content(), template="classic", page_limit=1)
    out = apply_watermark(docx.content, "内部使用", "docx")

    document = Document(BytesIO(out))
    header_text = "\n".join(
        paragraph.text
        for section in document.sections
        for paragraph in section.header.paragraphs
    )
    assert "内部使用" in header_text
