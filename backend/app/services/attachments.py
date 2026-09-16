"""浏览器上传附件的校验原语：图片与文档的格式白名单、文件头与体积上限。

图片校验只有这一份实现：助手附件（``assistant_service``）和岗位/资料识别
（``text_extraction``）都走这里。两处对格式白名单、魔数检查和体积上限的要求完全
一致，分开写迟早会漂移——而漂移的后果是一边放行了另一边认为危险的文件。

文档（PDF/DOCX）的**文字提取**在 ``document_text`` 里，但"这份文件该不该被接受"
同样只在这里判定，两条入口共享同一份白名单与体积上限。

本模块只做校验与规范化，不认识具体业务：调用方自己决定要不要接受文本附件。
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Iterable, Sequence
from typing import Any

# 单张图片、单份文档上限。
MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
# 一次请求里所有附件的合计上限。
#
# 这个数字是**承重**的：调用方把它当作 JSON 请求体的体积预算。5 MB 原始数据经
# base64 约 6.7 MB，仍在默认的 8 MB ``MAX_REQUEST_BODY_MB`` 之内；若放宽到 4 张
# × 2 MB = 8 MB，编码后约 10.7 MB 会直接撞上中间件返回 413。改动前请一并核对
# ``application.py`` 里的请求体上限。
MAX_ATTACHMENTS_TOTAL_BYTES = 5 * 1024 * 1024
# 一次请求里的附件个数上限。与 ``schemas/extraction.py`` 的
# ``MAX_EXTRACTION_IMAGE_COUNT`` 和前端 ``utils/attachments.ts`` 的
# ``MAX_ATTACHMENT_COUNT`` 是同一个约定；服务端这一份是权威。
MAX_ATTACHMENT_COUNT = 4

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

IMAGE_MIME_BY_EXTENSION = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jpe": "image/jpeg",
    ".jfif": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

# 服务商普遍不接受、浏览器预览也不可靠的格式：入库前统一转成 PNG/JPEG。
# 见 ``image_conversion.convert_to_supported_image``。
TRANSCODED_IMAGE_MIMES = frozenset({"image/bmp", "image/tiff"})

DOCUMENT_MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": DOCX_MIME,
}

# 声明 MIME 允许为空：浏览器偶尔给不出准确值，真正的判据是扩展名 + 文件头。
_EMPTY_DECLARED_MIMES = frozenset({"", "application/octet-stream"})

# "看懂了但做不了"的格式单独给一句话。笼统地说"格式不受支持"，用户只会换个后缀再试。
_EXTENSION_HINTS = {
    ".heic": "HEIC/HEIF 照片请先在手机或系统里导出为 JPEG，或直接截图后再上传",
    ".heif": "HEIC/HEIF 照片请先在手机或系统里导出为 JPEG，或直接截图后再上传",
    ".avif": "AVIF 图片请先导出为 PNG 或 JPEG 后再上传",
    ".svg": "矢量图（SVG）请先导出为 PNG 或 JPEG 后再上传",
    ".doc": "旧版 .doc 请用 Word 另存为 .docx 或 PDF 后再上传",
    ".rtf": "RTF 文件请另存为 .docx 或 PDF 后再上传",
    ".odt": "ODT 文件请另存为 .docx 或 PDF 后再上传",
    ".xlsx": "表格文件暂不支持；需要录入的内容可以复制为文本或截图后上传",
    ".pptx": "演示文稿暂不支持；需要录入的内容可以复制为文本或截图后上传",
}

_DATA_URL_RE = re.compile(r"^data:([^;,]+);base64,(.+)$", re.IGNORECASE | re.DOTALL)


def safe_attachment_name(value: str) -> str:
    """只取最后一段路径，挡掉浏览器可能带来的目录部分。"""
    name = re.split(r"[/\\]", value.strip())[-1]
    if name in {"", ".", ".."}:
        raise ValueError("附件名称无效")
    return name


def attachment_extension(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].casefold() if dot >= 0 else ""


def declared_mime(value: str) -> str:
    return value.split(";", 1)[0].strip().casefold()


def decode_data_url(data: str) -> tuple[str, bytes]:
    match = _DATA_URL_RE.fullmatch(data)
    if match is None:
        raise ValueError("附件 data URL 必须使用 base64 编码")
    try:
        decoded = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("附件不是有效的 base64 数据") from exc
    return match.group(1).casefold(), decoded


def unsupported_attachment_error(name: str) -> ValueError:
    """统一的"这种格式不收"错误，两个入口共用一份文案。"""
    hint = _EXTENSION_HINTS.get(attachment_extension(name))
    if hint:
        return ValueError(f"附件“{name}”：{hint}")
    return ValueError(
        f"附件“{name}”的格式不受支持：仅支持 txt/md/json/csv、pdf/docx 文档，"
        "以及 png/jpg/webp/gif/bmp/tiff 图片"
    )


# 文件头 → 真实格式。**只用于把"内容与扩展名不符"写成一句能照着做的提示**，
# 不参与放行判断：放行与否只看声明的扩展名与 MIME。
#
# 为什么值得做：扩展名说谎在现实里很常见（图片站/CDN 会对 `.jpeg` 链接按 Accept
# 返回 WebP 或 AVIF，另存下来名字是 .jpeg、内容是 WebP）。只说"内容与声明格式不一致"，
# 用户既不知道真实格式，也不知道下一步该做什么，只能反复换文件试。
_FORMAT_SIGNATURES: tuple[tuple[str, str | None, tuple[bytes, ...]], ...] = (
    ("PNG", ".png", (b"\x89PNG\r\n\x1a\n",)),
    ("JPEG", ".jpg", (b"\xff\xd8\xff",)),
    ("GIF", ".gif", (b"GIF87a", b"GIF89a")),
    ("BMP", ".bmp", (b"BM",)),
    ("TIFF", ".tiff", (b"II*\x00", b"MM\x00*")),
    ("PDF", ".pdf", (b"%PDF-",)),
)

# 认得出、但本应用收不了的格式：直接说该转成什么，而不是让用户自己猜。
_ZIP_LABEL = "ZIP 压缩包"
_FORMAT_ADVICE = {
    "HEIC/HEIF": "这种格式暂不支持，请先在手机或系统里导出为 JPEG 后再上传",
    "AVIF": "这种格式暂不支持，请先导出为 PNG 或 JPEG 后再上传",
    _ZIP_LABEL: "它像是一个压缩包：如果是 Word 文档，把扩展名改成 .docx 后可以按文档上传",
}


def detect_file_format(data: bytes) -> tuple[str, str | None]:
    """按文件头猜真实格式，返回 ``(展示名, 可直接使用的受支持扩展名或 None)``。"""
    for label, extension, signatures in _FORMAT_SIGNATURES:
        if data.startswith(signatures):
            return label, extension
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "WebP", ".webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in {b"avif", b"avis"}:
            return "AVIF", None
        return "HEIC/HEIF", None
    if data.startswith(b"PK\x03\x04"):
        return _ZIP_LABEL, None
    return "无法识别", None


def image_mime_of_content(data: bytes) -> str | None:
    """内容真实格式对应的图片 MIME；不是受支持的图片就返回 None。"""
    _, extension = detect_file_format(data)
    return IMAGE_MIME_BY_EXTENSION.get(extension) if extension else None


def document_mime_of_content(data: bytes) -> str | None:
    """内容真实格式对应的文档 MIME。

    zip 一律当作 docx：只有打开 ``word/document.xml`` 才能确认，那一步在
    ``document_text`` 里；这里若因为"看不出是 docx 还是 xlsx"就拒绝，被改过名的
    Word 文档就永远收不了。
    """
    label, extension = detect_file_format(data)
    if label == _ZIP_LABEL:
        return DOCX_MIME
    return DOCUMENT_MIME_BY_EXTENSION.get(extension) if extension else None


def format_mismatch_error(name: str, data: bytes) -> ValueError:
    """内容与扩展名不符时的提示：说清真实格式，并给出下一步。"""
    detected, extension = detect_file_format(data)
    if extension:
        return ValueError(
            f"附件“{name}”的内容与扩展名不符：实际看起来是 {detected}。"
            f"把扩展名改成 {extension}（或另存为 {detected}）后重新上传即可。"
        )
    if detected == "无法识别":
        return ValueError(
            f"附件“{name}”的内容与扩展名不符，也识别不出它的实际格式，"
            "文件可能已损坏或被截断；请用图片工具重新导出后再上传。"
        )
    advice = _FORMAT_ADVICE.get(
        detected, "请改用受支持的图片（png/jpg/webp/gif/bmp/tiff）或文档（pdf/docx）后重新上传"
    )
    return ValueError(f"附件“{name}”的内容与扩展名不符：实际看起来是 {detected}。{advice}")


def image_signature_matches(mime_type: str, data: bytes) -> bool:
    """按文件头判断内容是否真的是它声明的图片格式。

    只信扩展名或浏览器给的 MIME 是不够的：改个后缀就能把任意文件当图片送进模型。
    """
    checks = {
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        "image/gif": data.startswith((b"GIF87a", b"GIF89a")),
        "image/bmp": data.startswith(b"BM"),
        "image/tiff": data.startswith((b"II*\x00", b"MM\x00*")),
    }
    return checks.get(mime_type, False)


def document_signature_matches(mime_type: str, data: bytes) -> bool:
    """文件头必须是 PDF 或 ZIP。

    ZIP 只证明"这是个 OOXML 容器"，具体是不是 Word 文档由 ``document_text``
    打开 ``word/document.xml`` 时再判定——把扩展名改掉骗不过那一步。
    """
    if mime_type == "application/pdf":
        return data.startswith(b"%PDF-")
    return data.startswith(b"PK\x03\x04")


def image_mime_for_extension(name: str) -> str | None:
    return IMAGE_MIME_BY_EXTENSION.get(attachment_extension(name))


def document_mime_for_extension(name: str) -> str | None:
    return DOCUMENT_MIME_BY_EXTENSION.get(attachment_extension(name))


def normalize_image_attachment(name: str, mime_type: str, data: str) -> dict[str, Any]:
    """校验一张图片并规范化；错误文案面向用户，需保持稳定。"""
    safe_name = safe_attachment_name(name)
    canonical_mime = image_mime_for_extension(safe_name)
    if canonical_mime is None:
        raise unsupported_attachment_error(safe_name)

    declared = declared_mime(mime_type)
    if declared and declared != canonical_mime:
        raise ValueError(f"附件“{safe_name}”的类型与扩展名不一致")

    data_mime, raw = decode_data_url(data)
    if data_mime != canonical_mime:
        raise ValueError(f"附件“{safe_name}”的 data URL 类型与扩展名不一致")
    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"附件“{safe_name}”不能超过 2 MB")
    adopted_label = ""
    if not image_signature_matches(canonical_mime, raw):
        # 以内容为准：扩展名说谎时按真实格式处理。放宽的只是"名字 vs 内容"这一层，
        # "内容必须是一张受支持的图片"没有放宽——认不出真实格式仍然拒绝。
        # 现实里这不是罕见情况：图片站/CDN 常对 `.jpeg` 链接按浏览器偏好返回 WebP，
        # 另存下来名字是 .jpeg、内容是 WebP；逼用户改名只会让人以为功能坏了。
        detected = image_mime_of_content(raw)
        if detected is None:
            raise format_mismatch_error(safe_name, raw)
        adopted_label = detect_file_format(raw)[0]
        canonical_mime = detected

    if canonical_mime in TRANSCODED_IMAGE_MIMES:
        # 延迟导入：只有真的收到 bmp/tiff 时才需要 Pillow 与它的解码器。
        from .image_conversion import convert_to_supported_image

        try:
            raw, canonical_mime = convert_to_supported_image(raw, MAX_ATTACHMENT_BYTES)
        except ValueError as exc:
            raise ValueError(f"附件“{safe_name}”{exc}") from exc

    attachment = {
        "name": safe_name,
        "mime_type": canonical_mime,
        "kind": "image",
        "size_bytes": len(raw),
        "text": "",
        "data_url": f"data:{canonical_mime};base64,{base64.b64encode(raw).decode('ascii')}",
    }
    if adopted_label:
        # 按真实格式收下了，但要让用户知道文件名与内容不符，免得他以为文件被改过。
        attachment["notes"] = [f"文件实际是 {adopted_label}，已按真实格式处理。"]
    return attachment


def document_source(name: str, mime_type: str, data: str) -> tuple[str, str, bytes]:
    """校验一份文档，返回 ``(安全文件名, 规范 MIME, 原始字节)``。"""
    safe_name = safe_attachment_name(name)
    canonical_mime = document_mime_for_extension(safe_name)
    if canonical_mime is None:
        raise unsupported_attachment_error(safe_name)

    declared = declared_mime(mime_type)
    if declared not in _EMPTY_DECLARED_MIMES and declared != canonical_mime:
        raise ValueError(f"附件“{safe_name}”的类型与扩展名不一致")

    data_mime, raw = decode_data_url(data)
    if data_mime and data_mime not in {canonical_mime, "application/octet-stream"}:
        raise ValueError(f"附件“{safe_name}”的 data URL 类型与扩展名不一致")
    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"附件“{safe_name}”不能超过 2 MB")
    if not document_signature_matches(canonical_mime, raw):
        # 与图片同一条规则：名字可能说谎，内容说了算。认不出真实格式才拒绝。
        detected = document_mime_of_content(raw)
        if detected is None:
            raise format_mismatch_error(safe_name, raw)
        canonical_mime = detected

    return safe_name, canonical_mime, raw


def total_attachment_bytes(items: Iterable[dict[str, Any]]) -> int:
    return sum(int(item["size_bytes"]) for item in items)


def assert_attachment_budget(*, count: int, total_bytes: int, word: str = "附件") -> None:
    """个数与合计体积的共同上限；文档和图片共用同一份额度。"""
    if count > MAX_ATTACHMENT_COUNT:
        raise ValueError(f"一次最多上传 {MAX_ATTACHMENT_COUNT} 个{word}")
    if total_bytes > MAX_ATTACHMENTS_TOTAL_BYTES:
        raise ValueError(f"{word}总大小不能超过 5 MB")


def normalize_extraction_images(images: Sequence[Any]) -> list[dict[str, Any]]:
    """校验识别接口收到的图片，并强制合计上限。

    合计上限不是"顺手加的"：它同时是请求体不超限的保证，见
    ``MAX_ATTACHMENTS_TOTAL_BYTES`` 的说明。前端也会拦一道，但服务端不能依赖它。
    """
    normalized = [
        normalize_image_attachment(item.name, item.mime_type, item.data) for item in images
    ]
    total = total_attachment_bytes(normalized)
    if total > MAX_ATTACHMENTS_TOTAL_BYTES:
        raise ValueError("图片总大小不能超过 5 MB")
    return normalized


def image_data_urls(images: Sequence[dict[str, Any]]) -> list[str]:
    return [item["data_url"] for item in images if item.get("data_url")]
