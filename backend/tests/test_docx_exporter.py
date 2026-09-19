"""Word（.docx）导出：字节可读、版式复用 ResumeLayout、分页与 PDF ±1。"""
from io import BytesIO

import pytest
from docx import Document

from app.schemas.resume import ResumeContent
from app.services.docx_exporter import build_resume_docx
from app.services.pdf_exporter import build_resume_pdf, font_available
from app.services.resume_sample import sample_resume_content

needs_font = pytest.mark.skipif(not font_available(), reason="本机没有可用的中文字体")


def _resume() -> ResumeContent:
    return ResumeContent(
        name="张三",
        phone="13800000000",
        summary="负责后端服务的设计与开发。",
        experience=[{"company": "字节跳动", "role": "工程师", "description": ["实现检索接口"]}],
        skills=[{"name": "Python", "level": "熟练"}],
    )


def test_docx_builds_a_valid_word_document():
    result = build_resume_docx(_resume(), template="classic", page_limit=1)

    # .docx 是 ZIP 容器，文件头以 PK 开头；且能被 python-docx 重新打开。
    assert result.content.startswith(b"PK")
    document = Document(BytesIO(result.content))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "张三" in text
    assert "字节跳动" in text
    assert "实现检索接口" in text


def test_docx_reuses_layout_margins_and_respects_margin_override():
    result = build_resume_docx(_resume(), template="classic", page_limit=1, margin_mm=20)

    document = Document(BytesIO(result.content))
    section = document.sections[0]
    # 页边距直接覆盖 20mm，且四边一致（复用 ResumeLayout.margin_mm 的同一来源）。
    assert round(section.top_margin.mm, 2) == pytest.approx(20.0, abs=0.01)
    assert round(section.left_margin.mm, 2) == pytest.approx(20.0, abs=0.01)
    assert round(section.right_margin.mm, 2) == pytest.approx(20.0, abs=0.01)
    assert round(section.bottom_margin.mm, 2) == pytest.approx(20.0, abs=0.01)


def test_docx_uses_template_default_margin_when_not_overridden():
    from app.services.resume_templates import TEMPLATE_LAYOUT_DEFAULTS

    expected = float(TEMPLATE_LAYOUT_DEFAULTS["classic"]["padding_mm"])
    result = build_resume_docx(_resume(), template="classic", page_limit=1)

    document = Document(BytesIO(result.content))
    section = document.sections[0]
    assert round(section.top_margin.mm, 2) == pytest.approx(expected, abs=0.01)


def test_docx_excludes_photo_when_include_photo_is_false():
    # 用一张合法 PNG 的 data URL；关闭照片后文档里不应出现任何图片。
    png = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    resume = ResumeContent(name="张三", photo=png, summary="有照片。")

    with_photo = build_resume_docx(resume, template="classic", page_limit=1, include_photo=True)
    without_photo = build_resume_docx(resume, template="classic", page_limit=1, include_photo=False)

    # 带照片的文档里至少有 1 张图片（inline shape），关掉后没有。
    doc_with = Document(BytesIO(with_photo.content))
    doc_without = Document(BytesIO(without_photo.content))
    assert len(doc_with.inline_shapes) >= 1
    assert len(doc_without.inline_shapes) == 0


@needs_font
def test_docx_page_estimate_is_within_one_of_pdf():
    resume = sample_resume_content()
    pdf = build_resume_pdf(resume, template="classic", page_limit=2, font_scale="standard")
    docx = build_resume_docx(resume, template="classic", page_limit=2, font_scale="standard")

    assert docx.pages is not None
    assert abs(docx.pages - pdf.pages) <= 1
