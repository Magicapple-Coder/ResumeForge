"""把模型不一定认识的图片格式转成它认识的格式。

只有 bmp/tiff 这类"服务商普遍不接受、浏览器预览也不可靠"的格式会走到这里。PNG/JPEG/
WebP/GIF 一律按原样放行：重编码它们只会平白改变用户上传的字节、丢掉画质，还得让
``attachments.py`` 的魔数校验和体积上限跟着重新算一遍。

本模块只负责解码与编码；格式判定、名称校验和体积上限仍在 ``attachments.py``。
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

# 解码后的像素上限（约 4000 万像素）。Pillow 自带的 ``MAX_IMAGE_PIXELS`` 默认只发
# 警告，而这里要的是硬边界：压缩炸弹付出的是内存，不是"慢一点"。
MAX_IMAGE_PIXELS = 40_000_000

# 转码后仍然超过 2 MB 时的降采样阶梯（长边像素）。从大到小逐个尝试，先满足体积，
# 再尽量减少清晰度损失——截图里的文字就是靠这一步还能看清。
_DOWNSCALE_STEPS = (2400, 1800, 1200, 900, 640)

_JPEG_QUALITY = 88


def _decode(raw: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(raw))
        width, height = image.size
        if width * height > MAX_IMAGE_PIXELS:
            raise ValueError("像素过多，无法安全处理，请先压缩或裁剪后再上传")
        image.load()
    except ValueError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, MemoryError) as exc:
        raise ValueError("内容无法解码，可能已损坏或不是真正的图片") from exc
    return image


def _has_transparency(image: Image.Image) -> bool:
    if image.mode in {"RGBA", "LA", "PA"}:
        return True
    return image.mode == "P" and "transparency" in image.info


def _encode_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def _encode_jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    # JPEG 没有 alpha 通道，带透明度的图必须先铺一层白底，否则 Pillow 直接报错。
    flattened = image.convert("RGB") if image.mode not in {"RGB", "L"} else image
    flattened.save(buffer, format="JPEG", quality=_JPEG_QUALITY, optimize=False)
    return buffer.getvalue()


def _downscaled(image: Image.Image, longest_edge: int) -> Image.Image:
    copy = image.copy()
    copy.thumbnail((longest_edge, longest_edge), Image.Resampling.LANCZOS)
    return copy


def convert_to_supported_image(raw: bytes, max_bytes: int) -> tuple[bytes, str]:
    """把图片转成 PNG 或 JPEG，返回 ``(字节, MIME)``。

    体积上限由调用方给（``attachments.MAX_ATTACHMENT_BYTES``），本模块不重复定义常量。

    先试无损 PNG：bmp/tiff 的主力是截图、文档扫描件和导出的图表，PNG 的文字边缘比
    JPEG 清楚得多，而模型要读的正是文字。只有 PNG 超限时才退到 JPEG 并逐级降采样。
    """
    image = _decode(raw)
    # 手机竖拍的照片常常靠 EXIF 记录方向，不摆正就转码会让模型看到躺倒的文字。
    upright = ImageOps.exif_transpose(image)
    if upright is not None:
        image = upright
    transparent = _has_transparency(image)

    encoded = _encode_png(image)
    if len(encoded) <= max_bytes:
        return encoded, "image/png"

    if not transparent:
        encoded = _encode_jpeg(image)
        if len(encoded) <= max_bytes:
            return encoded, "image/jpeg"

    for longest_edge in _DOWNSCALE_STEPS:
        smaller = _downscaled(image, longest_edge)
        encoded = _encode_png(smaller) if transparent else _encode_jpeg(smaller)
        if len(encoded) <= max_bytes:
            return encoded, "image/png" if transparent else "image/jpeg"

    raise ValueError(f"转码后仍超过 {max_bytes // (1024 * 1024)} MB，请先裁剪或压缩后再上传")
