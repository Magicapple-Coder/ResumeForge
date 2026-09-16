"""文档识别（PDF/DOCX）的离线测试。

测试用的 PDF 与 DOCX 由本文件自己拼字节：为了几个用例再引入文档生成库不划算，
而且生成库造出来的 PDF 往往没有文字层，恰好测不到提取逻辑。
"""

import base64
import io
import zipfile
from xml.sax.saxutils import escape

import pytest
from pypdf import PdfWriter

from app.services.attachments import assert_attachment_budget, total_attachment_bytes
from app.services.document_text import (
    MAX_DOCUMENT_TEXT_CHARS,
    extract_document_text,
    extract_documents_text,
)

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def data_url(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


class DocumentStub:
    """识别接口收到的形状：只有 name / mime_type / data。"""

    def __init__(self, name: str, raw: bytes, mime: str):
        self.name = name
        self.mime_type = mime
        self.data = data_url(raw, mime)


def build_docx(*paragraphs: str, table_cell: str = "") -> bytes:
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
        for text in paragraphs
    )
    if table_cell:
        # 表格单元格里的文字也是 w:p：解析器按文档顺序遍历段落，两者都要覆盖。
        body += (
            "<w:tbl><w:tr><w:tc><w:p><w:r>"
            f"<w:t>{escape(table_cell)}</w:t>"
            "</w:r></w:p></w:tc></w:tr></w:tbl>"
        )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def build_pdf(text: str = "", *, blank: bool = False) -> bytes:
    """手写一份最小 PDF，带正确的 xref 表。

    ``blank=True`` 用来模拟扫描件：页面存在，但没有可作为文字提取的内容。
    """
    content = b"q Q" if blank else b"BT /F1 12 Tf 72 720 Td (" + text.encode("ascii") + b") Tj ET"
    objects = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>"),
        (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
        (
            4,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>",
        ),
        (
            5,
            b"<< /Length "
            + str(len(content)).encode("ascii")
            + b" >>\nstream\n"
            + content
            + b"\nendstream",
        ),
    ]

    output = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number, body in objects:
        offsets[number] = len(output)
        output += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    size = len(objects) + 1
    xref_offset = len(output)
    output += f"xref\n0 {size}\n".encode("ascii") + b"0000000000 65535 f \n"
    for number in range(1, size):
        output += f"{offsets[number]:010d} 00000 n \n".encode("ascii")
    output += (
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def build_encrypted_pdf(password: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(password)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_text_is_extracted_locally():
    raw = build_pdf("ResumeForge Backend Resume")

    extracted = extract_document_text("resume.pdf", PDF_MIME, data_url(raw, PDF_MIME))

    assert "ResumeForge Backend Resume" in extracted.text
    assert extracted.mime_type == PDF_MIME
    assert extracted.size_bytes == len(raw)
    assert extracted.warnings == []


def test_docx_text_includes_paragraphs_and_table_cells():
    raw = build_docx("姓名：张三", "求职意向：后端开发工程师", table_cell="天津工业大学")

    extracted = extract_document_text("resume.docx", DOCX_MIME, data_url(raw, DOCX_MIME))

    assert extracted.text.splitlines() == ["姓名：张三", "求职意向：后端开发工程师", "天津工业大学"]


def test_document_without_a_text_layer_points_at_the_screenshot_route():
    raw = build_pdf(blank=True)

    with pytest.raises(ValueError, match="没有从这份文件里提取到文字"):
        extract_document_text("scan.pdf", PDF_MIME, data_url(raw, PDF_MIME))


def test_password_protected_pdf_is_rejected():
    raw = build_encrypted_pdf("secret")

    with pytest.raises(ValueError, match="文件有密码保护"):
        extract_document_text("locked.pdf", PDF_MIME, data_url(raw, PDF_MIME))


def test_broken_documents_get_actionable_messages():
    with pytest.raises(ValueError, match="文件无法解析"):
        extract_document_text("broken.pdf", PDF_MIME, data_url(b"%PDF-1.4\n\x00\x01\x02", PDF_MIME))

    # 长得像 zip、但里面没有 Word 正文：改名成 .docx 骗不过这一步。
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "not a document")
    with pytest.raises(ValueError, match="不是有效的 docx"):
        extract_document_text("fake.docx", DOCX_MIME, data_url(buffer.getvalue(), DOCX_MIME))


def test_long_document_is_truncated_with_a_warning():
    raw = build_docx("A" * (MAX_DOCUMENT_TEXT_CHARS + 5_000))

    extracted = extract_document_text("long.docx", DOCX_MIME, data_url(raw, DOCX_MIME))

    assert len(extracted.text) == MAX_DOCUMENT_TEXT_CHARS
    assert extracted.warnings == ["文档内容较长，本次只识别了前一部分；其余内容请复制为文本粘贴。"]


def test_documents_share_one_text_budget_and_are_all_validated():
    first_raw = build_docx("B" * 40_000)
    second_raw = build_docx("C" * 40_000)
    big = DocumentStub("big.docx", first_raw, DOCX_MIME)
    another = DocumentStub("another.docx", second_raw, DOCX_MIME)

    combined = extract_documents_text([big, another])

    assert len(combined.text) <= MAX_DOCUMENT_TEXT_CHARS + 200  # 只多出行首尾的标记
    assert "文档内容较长" in "".join(combined.warnings)
    assert combined.size_bytes == len(first_raw) + len(second_raw)

    # 预算用完也要继续校验后面的文件，否则损坏的文件会因为排在后面而被静默忽略。
    broken = DocumentStub("broken.docx", b"PK\x03\x04not-a-docx", DOCX_MIME)
    with pytest.raises(ValueError, match="可能已损坏"):
        extract_documents_text([big, another, broken])


def test_documents_are_joined_without_source_markers():
    """标记行会被本地规则当成正文（岗位描述里会多出一行文件名），所以不插标记。"""
    first = DocumentStub("jd.docx", build_docx("职位名称：后端开发工程师"), DOCX_MIME)
    second = DocumentStub("jd.pdf", build_pdf("Company: Example Inc"), PDF_MIME)

    combined = extract_documents_text([first, second])

    assert combined.text == "职位名称：后端开发工程师\n\nCompany: Example Inc"
    assert combined.warnings == []


def test_attachment_budget_covers_count_and_total_bytes():
    two_mb = [{"size_bytes": 2 * 1024 * 1024}]

    with pytest.raises(ValueError, match="一次最多上传 4 个附件"):
        assert_attachment_budget(count=5, total_bytes=1024)
    with pytest.raises(ValueError, match="附件总大小不能超过 5 MB"):
        assert_attachment_budget(
            count=3, total_bytes=total_attachment_bytes(two_mb * 3)
        )
    assert_attachment_budget(count=4, total_bytes=total_attachment_bytes(two_mb))
