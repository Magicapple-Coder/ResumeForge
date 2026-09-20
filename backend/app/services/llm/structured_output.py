"""从大模型回复中提取受限的 JSON 对象。

模型服务商不一定严格遵守"只输出 JSON"，因此这里提供一个很小的容错层：
- 允许 Markdown 代码围栏（```json ... ``` 或 ``` ... ```），即使前后还夹着说明文字；
- 允许在 JSON 前后有解释性文字；
- 允许对象/数组末尾出现尾随逗号；
- 最终只接受 JSON 对象，不执行任何模型返回的代码或标记语言。

容错只做"定位并截取第一个平衡的 {...}"，不替模型脑补结构。
"""

import json
import re
from typing import Any

from .base import LLMError

# 整段被一个代码围栏包住的情况（历史写法，先保留）。
_FENCED_JSON_RE = re.compile(r"\A```(?:json)?\s*(.*?)\s*```\Z", re.IGNORECASE | re.DOTALL)
# 在前后夹着文字的回复里，定位第一个代码围栏块。
_INLINE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """去掉代码围栏：优先整段围栏，否则取第一个围栏块；都没有就原样返回。"""
    fenced = _FENCED_JSON_RE.fullmatch(text)
    if fenced is not None:
        return fenced.group(1).strip()
    inline = _INLINE_FENCE_RE.search(text)
    if inline is not None:
        return inline.group(1).strip()
    return text


def _extract_balanced_object(text: str, start: int) -> str | None:
    """从 ``start``（首个 ``{`` 的位置）起，按括号计数截取首个平衡的 ``{...}`` 子串。

    字符串字面量内部的括号与转义会被忽略，避免把 ``"a{b}"`` 这种内容误判成嵌套对象。
    返回截取到的子串；若括号不平衡（如模型截断）返回 ``None``。
    """
    depth = 0
    in_string = False
    escape = False
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        i += 1
    return None


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _strip_trailing_commas(text: str) -> str:
    """去掉对象/数组末尾的尾随逗号（如 ``{"a":1,}``、``[1,2,]``）。

    只作用于 ``}`` / ``]`` 之前，不会误伤字符串里的逗号。
    """
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def parse_json_object(raw: str, *, label: str, max_chars: int = 100_000) -> dict[str, Any]:
    """解析模型返回的 JSON 对象，并将格式问题转换为用户可理解的错误。"""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > max_chars:
        raise LLMError(f"模型返回的{label}为空或过长，请重试")

    # 1. 剥离代码围栏（含前后解释文字）。
    cleaned = _strip_code_fence(raw.strip())

    # 2. 截取首个平衡的 {...}（括号计数，忽略字符串内括号）。
    start = cleaned.find("{")
    if start < 0:
        raise LLMError(f"模型未返回有效的{label} JSON，请重试")
    balanced = _extract_balanced_object(cleaned, start)
    if balanced is None:
        raise LLMError(f"模型返回的{label} JSON 不完整（括号未闭合），请重试")

    # 3. 去掉尾随逗号后解析。
    candidate = _strip_trailing_commas(balanced)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMError(f"模型未返回有效的{label} JSON，请重试") from exc
    if not isinstance(value, dict):
        raise LLMError(f"模型返回的{label}结构无效，请重试")
    return value
