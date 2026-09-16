"""从上传的文档里在本机提取文字（PDF、DOCX）。

为什么不是把文件交给模型：项目只支持 OpenAI Chat Completions 兼容协议，多数服务商
不接受 PDF 入参，多模态能力也参差不齐。本地提取换来三件事——离线可用（未配置模型时
本地规则仍能解析这些文字）、不把原始文件发给第三方、以及识别结果可以走**真正的原文
锚定**（见 ``text_extraction._anchor_text``：图片只能靠模型自己抄录一遍再对照，天然更弱）。

解析的是不可信输入，所以每条限制都有理由：页数、字符数、体积都封顶，PDF 走 pypdf，
DOCX 只读白名单成员，绝不 ``extractall``。任何解析失败都转成面向用户的中文提示。
"""

from __future__ import annotations

import io
import logging
import zipfile
from collections.abc import Sequence
from typing import Any, NamedTuple
from xml.etree import ElementTree

from pypdf import PdfReader

from .attachments import DOCX_MIME, document_source

logger = logging.getLogger(__name__)

# 一份文档最多读多少页。简历和招聘信息没有超过这个数的正当理由，而页数直接决定
# 解析耗时。
MAX_PDF_PAGES = 30
# 一次识别里所有文档提取出的纯文字上限（不是每份文档各一份）。超过后截断并明确告知
# 用户，不做静默丢弃。
#
# 20,000 而不是跟粘贴文本一样的 100,000：这段文字要过一遍本地规则解析，而解析在
# **单行超长文本**上是平方级（实测 30,000 字单行要 9 秒，20,000 字 4 秒；正常多行
# 文本 35,000 字只要 0.13 秒）。一份简历或招聘信息的正文远用不到 20,000 字，
# 把上限留在这个量级可以避免一次上传让请求卡住十几秒。
MAX_DOCUMENT_TEXT_CHARS = 20_000

_DOCX_DOCUMENT_XML = "word/document.xml"
_DOCX_WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_TRUNCATED_WARNING = "文档内容较长，本次只识别了前一部分；其余内容请复制为文本粘贴。"
_EMPTY_TEXT_MESSAGE = (
    "没有从这份文件里提取到文字，可能是扫描件或纯图片文件；请改用截图上传，截图会走图片识别。"
)


class ExtractedDocument(NamedTuple):
    """一份文档的提取结果。``size_bytes`` 是**原始文件**大小，供体积预算使用。"""

    name: str
    mime_type: str
    size_bytes: int
    text: str
    warnings: list[str]


class ExtractedDocuments(NamedTuple):
    text: str
    warnings: list[str]
    size_bytes: int


def _truncate(text: str) -> tuple[str, list[str]]:
    if len(text) <= MAX_DOCUMENT_TEXT_CHARS:
        return text, []
    return text[:MAX_DOCUMENT_TEXT_CHARS], [_TRUNCATED_WARNING]


def _pdf_text(raw: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            # 空密码是某些导出工具的常见情况，能打开就不该拦。
            if not reader.decrypt(""):
                raise ValueError("文件有密码保护，请先解除限制后再上传")
        pages = reader.pages[:MAX_PDF_PAGES]
        return "\n".join(page.extract_text() or "" for page in pages)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - 第三方解析器抛出的异常类型不固定
        logger.warning("PDF 文字提取失败：%s", type(exc).__name__)
        raise ValueError("文件无法解析，可能已损坏或不是真正的 PDF") from exc


def _docx_text(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            # 只读白名单成员，不走 extractall：docx 是 zip，解压路径由上传者控制。
            with archive.open(_DOCX_DOCUMENT_XML) as stream:
                tree = ElementTree.parse(stream)
    except KeyError as exc:
        raise ValueError("文件不是有效的 docx（缺少正文），请另存为 .docx 后重新上传") from exc
    except (zipfile.BadZipFile, ElementTree.ParseError, OSError) as exc:
        raise ValueError("文件无法解析，可能已损坏或不是真正的 DOCX") from exc

    paragraphs: list[str] = []
    for paragraph_element in tree.iter(f"{_DOCX_WORD_NAMESPACE}p"):
        # 表格单元格里也是 w:p，所以按文档顺序遍历段落就能同时覆盖正文与表格。
        text = "".join(
            node.text or "" for node in paragraph_element.iter(f"{_DOCX_WORD_NAMESPACE}t")
        )
        if text.strip():
            paragraphs.append(text.strip())
    return "\n".join(paragraphs)


def extract_document_text(name: str, mime_type: str, data: str) -> ExtractedDocument:
    """校验并提取一份文档的文字。

    校验失败抛出面向用户的 ``ValueError``；提取不到文字也算失败——传一份空文档给模型
    只会换来一段基于臆测的识别结果。
    """
    safe_name, canonical_mime, raw = document_source(name, mime_type, data)
    extracted = _docx_text(raw) if canonical_mime == DOCX_MIME else _pdf_text(raw)
    text = extracted.strip()
    if not text:
        raise ValueError(f"附件“{safe_name}”：{_EMPTY_TEXT_MESSAGE}")
    body, warnings = _truncate(text)
    return ExtractedDocument(
        name=safe_name,
        mime_type=canonical_mime,
        size_bytes=len(raw),
        text=body,
        warnings=warnings,
    )


def extract_documents_text(documents: Sequence[Any]) -> ExtractedDocuments:
    """把若干份文档提取成一段可解析文本，供岗位/资料识别使用。

    **不插入任何来源标记**：这段文字要和粘贴文本一样喂给本地规则，而规则会把开头的
    孤行当作正文——`[文档：jd.docx]` 这样的标记会直接混进岗位描述。文件来源在界面上
    本来就看得见（附件会以文件形式列出），不值得为此污染解析结果。

    所有文档都会被校验，即使前面的文档已经用完了字符预算——否则一份损坏的文件会因为
    排在后面而被静默忽略。
    """
    blocks: list[str] = []
    warnings: list[str] = []
    total_bytes = 0
    remaining = MAX_DOCUMENT_TEXT_CHARS
    for document in documents:
        extracted = extract_document_text(document.name, document.mime_type, document.data)
        total_bytes += extracted.size_bytes
        warnings.extend(extracted.warnings)
        body = extracted.text
        if len(body) > remaining:
            body = body[:remaining].rstrip()
            warnings.append(_TRUNCATED_WARNING)
        remaining -= len(body)
        blocks.append(body)
    return ExtractedDocuments(
        text="\n\n".join(blocks),
        warnings=list(dict.fromkeys(warnings)),
        size_bytes=total_bytes,
    )
