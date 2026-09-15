"""浏览器上传的附件与图片的校验原语。

图片校验只有这一份实现：助手附件（``assistant_service``）和岗位/资料识别
（``text_extraction``）都走这里。两处对格式白名单、魔数检查和体积上限的要求完全
一致，分开写迟早会漂移——而漂移的后果是一边放行了另一边认为危险的文件。

本模块只做校验与规范化，不认识具体业务：调用方自己决定要不要接受文本附件。
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Sequence

# 单张图片上限。
MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
# 一次请求里所有附件的合计上限。
#
# 这个数字是**承重**的：调用方把它当作 JSON 请求体的体积预算。5 MB 原始数据经
# base64 约 6.7 MB，仍在默认的 8 MB ``MAX_REQUEST_BODY_MB`` 之内；若放宽到 4 张
# × 2 MB = 8 MB，编码后约 10.7 MB 会直接撞上中间件返回 413。改动前请一并核对
# ``application.py`` 里的请求体上限。
MAX_ATTACHMENTS_TOTAL_BYTES = 5 * 1024 * 1024

IMAGE_MIME_BY_EXTENSION = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
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


def image_signature_matches(mime_type: str, data: bytes) -> bool:
    """按文件头判断内容是否真的是它声明的图片格式。

    只信扩展名或浏览器给的 MIME 是不够的：改个后缀就能把任意文件当图片送进模型。
    """
    checks = {
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        "image/gif": data.startswith((b"GIF87a", b"GIF89a")),
    }
    return checks.get(mime_type, False)


def image_mime_for_extension(name: str) -> str | None:
    return IMAGE_MIME_BY_EXTENSION.get(attachment_extension(name))


def normalize_image_attachment(name: str, mime_type: str, data: str) -> dict[str, Any]:
    """校验一张图片并规范化；错误文案面向用户，需保持稳定。"""
    safe_name = safe_attachment_name(name)
    canonical_mime = image_mime_for_extension(safe_name)
    if canonical_mime is None:
        raise ValueError("仅支持 png/jpeg/webp/gif 图片")

    declared = declared_mime(mime_type)
    if declared and declared != canonical_mime:
        raise ValueError(f"附件“{safe_name}”的类型与扩展名不一致")

    data_mime, raw = decode_data_url(data)
    if data_mime != canonical_mime:
        raise ValueError(f"附件“{safe_name}”的 data URL 类型与扩展名不一致")
    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"附件“{safe_name}”不能超过 2 MB")
    if not image_signature_matches(canonical_mime, raw):
        raise ValueError(f"附件“{safe_name}”的内容与声明图片格式不一致")

    return {
        "name": safe_name,
        "mime_type": canonical_mime,
        "kind": "image",
        "size_bytes": len(raw),
        "text": "",
        "data_url": f"data:{canonical_mime};base64,{base64.b64encode(raw).decode('ascii')}",
    }


def normalize_extraction_images(images: Sequence[Any]) -> list[dict[str, Any]]:
    """校验识别接口收到的图片，并强制合计上限。

    合计上限不是"顺手加的"：它同时是请求体不超限的保证，见
    ``MAX_ATTACHMENTS_TOTAL_BYTES`` 的说明。前端也会拦一道，但服务端不能依赖它。
    """
    normalized = [
        normalize_image_attachment(item.name, item.mime_type, item.data) for item in images
    ]
    total = sum(item["size_bytes"] for item in normalized)
    if total > MAX_ATTACHMENTS_TOTAL_BYTES:
        raise ValueError("图片总大小不能超过 5 MB")
    return normalized


def image_data_urls(images: Sequence[dict[str, Any]]) -> list[str]:
    return [item["data_url"] for item in images if item.get("data_url")]
