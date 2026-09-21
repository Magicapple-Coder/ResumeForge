"""附件格式的扩展测试：新增图片格式的转码、文档附件，以及拒绝路径的文案。

图片样本用 Pillow 现造：它已经是运行时依赖，测试里就该用真文件而不是假的文件头。
"""

import base64
import io
import os

import pytest
from PIL import Image

from app.schemas.assistant import AssistantAttachmentInput
from app.services.assistant.assistant_service import normalize_attachments
from app.services.attachments import MAX_ATTACHMENT_BYTES
from app.services.image_conversion import convert_to_supported_image
from tests.test_document_text import DOCX_MIME, build_docx, build_pdf, data_url


def image_bytes(image: Image.Image, image_format: str) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def sample_image() -> Image.Image:
    """一张有明确边界的小图：转换后必须仍然是同一张图。"""
    image = Image.new("RGB", (240, 160), "white")
    for x in range(40, 200, 4):
        image.putpixel((x, 80), (0, 0, 0))
    return image


def decoded(data_url_value: str) -> bytes:
    return base64.b64decode(data_url_value.split(",", 1)[1])


def test_bmp_upload_is_transcoded_to_png():
    raw = image_bytes(sample_image(), "BMP")

    [attachment] = normalize_attachments(
        [
            AssistantAttachmentInput(
                name="whiteboard.bmp", mime_type="image/bmp", data=data_url(raw, "image/bmp")
            )
        ]
    )

    assert attachment["kind"] == "image"
    assert attachment["mime_type"] == "image/png"
    assert attachment["data_url"].startswith("data:image/png;base64,")
    # size_bytes 说的是"存下来的这份内容有多大"，转码后就该是转码后的长度。
    assert attachment["size_bytes"] == len(decoded(attachment["data_url"]))
    with Image.open(io.BytesIO(decoded(attachment["data_url"]))) as converted:
        assert converted.size == (240, 160)


def test_tiff_upload_is_transcoded_and_keeps_the_file_name():
    raw = image_bytes(sample_image(), "TIFF")

    [attachment] = normalize_attachments(
        [
            AssistantAttachmentInput(
                name="screenshot.tif", mime_type="image/tiff", data=data_url(raw, "image/tiff")
            )
        ]
    )

    assert attachment["name"] == "screenshot.tif"
    assert attachment["mime_type"] == "image/png"


def test_jpeg_alias_extensions_are_passed_through_unchanged():
    raw = image_bytes(sample_image(), "JPEG")

    [attachment] = normalize_attachments(
        [
            AssistantAttachmentInput(
                name="photo.jfif", mime_type="image/jpeg", data=data_url(raw, "image/jpeg")
            )
        ]
    )

    # 已经是模型支持的格式：不重编码，字节与用户上传的完全一致。
    assert attachment["mime_type"] == "image/jpeg"
    assert decoded(attachment["data_url"]) == raw


def test_photo_like_bmp_falls_back_to_jpeg_within_the_limit():
    noisy = Image.frombytes("RGB", (1200, 1200), os.urandom(1200 * 1200 * 3))
    raw = image_bytes(noisy, "BMP")

    converted, mime_type = convert_to_supported_image(raw, MAX_ATTACHMENT_BYTES)

    # 这类内容 PNG 压不下去（噪点不可压缩），必须退到 JPEG 并可能降采样。
    assert mime_type == "image/jpeg"
    assert len(converted) <= MAX_ATTACHMENT_BYTES
    with Image.open(io.BytesIO(converted)) as result:
        assert result.size[0] <= 1200 and result.size[1] <= 1200


def test_broken_image_payload_is_rejected_with_a_readable_message():
    with pytest.raises(ValueError, match="无法解码"):
        convert_to_supported_image(b"BM" + b"\x00" * 64, MAX_ATTACHMENT_BYTES)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("IMG_0001.HEIC", "导出为 JPEG"),
        ("slides.svg", "矢量图"),
        ("legacy.doc", "另存为 .docx 或 PDF"),
        ("table.xlsx", "表格文件暂不支持"),
    ],
)
def test_known_but_unsupported_formats_get_actionable_messages(name, expected):
    with pytest.raises(ValueError, match=expected):
        normalize_attachments(
            [AssistantAttachmentInput(name=name, mime_type="", data="data:application/pdf;base64,eA==")]
        )


def test_unknown_extension_lists_what_is_supported():
    with pytest.raises(ValueError, match="仅支持 txt/md/json/csv、pdf/docx"):
        normalize_attachments(
            [AssistantAttachmentInput(name="archive.zip", mime_type="", data="eA==")]
        )


def test_document_whose_extension_lies_is_read_by_content():
    """真 docx 被命名成 .pdf：按 zip 内容判定为 docx，照常提取文字。"""
    [attachment] = normalize_attachments(
        [
            AssistantAttachmentInput(
                name="resume.pdf",
                mime_type="application/pdf",
                data=data_url(build_docx("张三"), "application/pdf"),
            )
        ]
    )

    assert attachment["kind"] == "document"
    assert attachment["mime_type"] == DOCX_MIME
    assert attachment["text"] == "张三"


def test_image_content_in_a_document_slot_is_still_rejected():
    """放宽只限"名字 vs 内容"这一层：图片放进文档槽位仍然要拦住并说明真实格式。"""
    with pytest.raises(ValueError, match=r"实际看起来是 PNG"):
        normalize_attachments(
            [
                AssistantAttachmentInput(
                    name="resume.pdf",
                    mime_type="application/pdf",
                    data=data_url(image_bytes(sample_image(), "PNG"), "application/pdf"),
                )
            ]
        )


def test_mislabeled_image_is_accepted_as_its_real_format():
    """扩展名说谎在现实里很常见（图片站会给 `.jpeg` 链接返回 WebP）。

    用户不该为了这个去改名：内容说了算，按真实格式收下，并在说明里讲清楚发生了什么。
    """
    png = image_bytes(sample_image(), "PNG")

    [attachment] = normalize_attachments(
        [
            AssistantAttachmentInput(
                name="参考图.jpeg",
                mime_type="image/jpeg",
                data=data_url(png, "image/jpeg"),
            )
        ]
    )

    assert attachment["kind"] == "image"
    assert attachment["mime_type"] == "image/png"
    assert attachment["data_url"].startswith("data:image/png;base64,")
    assert attachment["notes"] == ["文件实际是 PNG，已按真实格式处理。"]
    # 数据 URL 前缀仍然是浏览器按扩展名给的 image/jpeg，这一点没有被改写
    assert decoded(attachment["data_url"]).startswith(b"\x89PNG\r\n\x1a\n")


def test_pdf_renamed_to_an_image_is_reported_as_a_document():
    pdf = build_pdf("ResumeForge PDF Resume")

    with pytest.raises(ValueError, match=r"改成 \.pdf") as error:
        normalize_attachments(
            [
                AssistantAttachmentInput(
                    name="参考图.jpeg",
                    mime_type="image/jpeg",
                    data=data_url(pdf, "image/jpeg"),
                )
            ]
        )
    assert "实际看起来是 PDF" in str(error.value)


def test_webp_content_in_a_png_file_is_taken_as_webp():
    """最常见的现实场景：从图片站另存下来的 `.jpeg` 其实是 WebP。"""
    webp = image_bytes(sample_image(), "WEBP")

    [attachment] = normalize_attachments(
        [
            AssistantAttachmentInput(
                name="参考图.jpeg", mime_type="image/jpeg", data=data_url(webp, "image/jpeg")
            )
        ]
    )

    assert attachment["mime_type"] == "image/webp"
    assert attachment["notes"] == ["文件实际是 WebP，已按真实格式处理。"]


def test_heic_and_broken_files_get_specific_advice():
    heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00"
    with pytest.raises(ValueError, match=r"实际看起来是 HEIC/HEIF") as heic_error:
        normalize_attachments(
            [
                AssistantAttachmentInput(
                    name="IMG_0001.jpeg",
                    mime_type="image/jpeg",
                    data=data_url(heic, "image/jpeg"),
                )
            ]
        )
    assert "导出为 JPEG" in str(heic_error.value)

    with pytest.raises(ValueError, match=r"也识别不出它的实际格式") as broken_error:
        normalize_attachments(
            [
                AssistantAttachmentInput(
                    name="IMG_0002.jpeg",
                    mime_type="image/jpeg",
                    data=data_url(b"\x01\x02\x03\x04", "image/jpeg"),
                )
            ]
        )
    assert "已损坏或被截断" in str(broken_error.value)


def test_document_attachment_uses_the_original_file_size():
    raw = build_docx("姓名：张三", "求职意向：后端开发工程师")

    [attachment] = normalize_attachments(
        [
            AssistantAttachmentInput(
                name="resume.docx", mime_type=DOCX_MIME, data=data_url(raw, DOCX_MIME)
            )
        ]
    )

    assert attachment["kind"] == "document"
    assert attachment["text"].splitlines() == ["姓名：张三", "求职意向：后端开发工程师"]
    assert attachment["size_bytes"] == len(raw)
