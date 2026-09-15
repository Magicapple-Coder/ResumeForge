"""从大模型回复中提取受限的 JSON 对象。

模型服务商不一定严格遵守“只输出 JSON”，因此这里提供一个很小的容错层：
允许完整 Markdown 代码围栏或少量前后说明，但最终只接受 JSON 对象，不执行任何
模型返回的代码或标记语言。
"""

import json
import re
from typing import Any

from .base import LLMError

_FENCED_JSON_RE = re.compile(r"\A```(?:json)?\s*(.*?)\s*```\Z", re.IGNORECASE | re.DOTALL)


def parse_json_object(raw: str, *, label: str, max_chars: int = 100_000) -> dict[str, Any]:
    """解析模型返回的 JSON 对象，并将格式问题转换为用户可理解的错误。"""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > max_chars:
        raise LLMError(f"模型返回的{label}为空或过长，请重试")

    cleaned = raw.strip()
    fenced = _FENCED_JSON_RE.fullmatch(cleaned)
    if fenced is not None:
        cleaned = fenced.group(1).strip()

    start = cleaned.find("{")
    if start < 0:
        raise LLMError(f"模型未返回有效的{label} JSON，请重试")
    try:
        value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError as exc:
        raise LLMError(f"模型未返回有效的{label} JSON，请重试") from exc
    if not isinstance(value, dict):
        raise LLMError(f"模型返回的{label}结构无效，请重试")
    return value
