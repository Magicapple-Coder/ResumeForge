"""个人资料参考文件的安全清洗、相关片段提取和上下文准备。"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .profile_matching import _contains, _score_item
from .profile_relevance_constants import (
    DOMAIN_SIGNALS,
    _MARKDOWN_LIST_PREFIX_RE,
    _MARKDOWN_TABLE_DIVIDER_RE,
    _REFERENCE_CONTENT_KEY,
    _REFERENCE_FACT_LIMIT,
    _REFERENCE_FACT_MAX_CHARS,
    _REFERENCE_FILE_KEY,
    _REFERENCE_EXCERPT_MAX_CHARS,
    _REFERENCE_INSTRUCTION_RE,
    _REFERENCE_META_RE,
    JobFocus,
)
from .profile_budget import _trim_text


def _safe_reference_blocks(content: str) -> list[str]:
    """切分参考文件并移除含明显提示注入的整个段落。"""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    return [
        block.replace("```", "").strip()
        for block in re.split(r"\n\s*\n+", normalized)
        if block.strip() and _REFERENCE_INSTRUCTION_RE.search(block) is None
    ]


def _strip_markdown(value: str) -> str:
    value = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", value).strip()


def _clean_reference_fact_line(line: str) -> str:
    """把 Markdown 行转换为可直接追溯的事实句，丢弃标题和元说明。"""
    stripped = line.strip()
    if (
        not stripped
        or stripped.startswith(("#", ">"))
        or re.fullmatch(r"[-*_]{3,}", stripped)
        or _REFERENCE_META_RE.search(stripped)
    ):
        return ""

    if stripped.startswith("|") and stripped.endswith("|"):
        cells = [_strip_markdown(cell) for cell in stripped.strip("|").split("|")]
        if not cells or all(_MARKDOWN_TABLE_DIVIDER_RE.fullmatch(cell) for cell in cells):
            return ""
        if cells[0] in {"层级", "技术", "指标", "数值", "项目", "说明"}:
            return ""
        stripped = f"{cells[0]}：{'、'.join(cell for cell in cells[1:] if cell)}"
    else:
        stripped = _MARKDOWN_LIST_PREFIX_RE.sub("", stripped)

    cleaned = _strip_markdown(stripped).strip(" -：:")
    if (
        len(cleaned) < 12
        or _REFERENCE_META_RE.search(cleaned)
        or _REFERENCE_INSTRUCTION_RE.search(cleaned)
    ):
        return ""
    return _trim_text(cleaned, _REFERENCE_FACT_MAX_CHARS)


def _reference_fact_candidates(content: str) -> list[str]:
    """从安全段落中提取自包含的事实行，保留原文而不做语义扩写。"""
    candidates: list[str] = []
    seen: set[str] = set()
    for block in _safe_reference_blocks(content):
        for line in block.splitlines():
            fact = _clean_reference_fact_line(line)
            normalized = re.sub(r"\s+", "", fact).casefold()
            if not fact or normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(fact)
    return candidates


def _select_reference_facts(content: str, section: str, focus: JobFocus) -> list[str]:
    """选取少量 JD 相关事实，供模型使用并作为空输出时的确定性回退。"""
    ranked: list[tuple[int, str, int, set[str]]] = []
    for index, fact in enumerate(_reference_fact_candidates(content)):
        score = _score_item({"reference_fact": fact}, section, focus)
        if score <= 0:
            continue
        matched_signals = {
            f"term:{term.casefold()}" for term in focus.terms if _contains(fact, term)
        }
        matched_signals.update(
            f"domain:{domain}"
            for domain in focus.domains
            if any(_contains(fact, signal) for signal in DOMAIN_SIGNALS[domain])
        )
        ranked.append((index, fact, score, matched_signals))

    selected: list[str] = []
    remaining = list(ranked)
    uncovered = {f"term:{term.casefold()}" for term in focus.terms}
    uncovered.update(f"domain:{domain}" for domain in focus.domains)
    while remaining and len(selected) < _REFERENCE_FACT_LIMIT:
        choice = max(
            remaining,
            key=lambda item: (len(item[3] & uncovered), item[2], -item[0]),
        )
        remaining.remove(choice)
        _, fact, _, matched_signals = choice
        selected.append(fact)
        uncovered -= matched_signals
    return selected


def _reference_chunks(content: str) -> list[str]:
    """按 Markdown 段落切分，并在进入 Prompt 前丢弃明显的指令注入。"""
    return [_trim_text(block, 700) for block in _safe_reference_blocks(content)]


def _select_reference_excerpt(content: str, section: str, focus: JobFocus) -> str:
    """选择直接命中 JD 的参考段落，并保持其在原文中的顺序。"""
    ranked = [
        (index, chunk, _score_item({"reference": chunk}, section, focus))
        for index, chunk in enumerate(_reference_chunks(content))
    ]
    matching = sorted(
        (item for item in ranked if item[2] > 0),
        key=lambda item: (-item[2], item[0]),
    )
    selected_indexes: set[int] = set()
    used_chars = 0
    for index, chunk, _ in matching:
        separator_size = 2 if selected_indexes else 0
        if selected_indexes and used_chars + separator_size + len(chunk) > _REFERENCE_EXCERPT_MAX_CHARS:
            continue
        selected_indexes.add(index)
        used_chars += separator_size + len(chunk)
        if used_chars >= _REFERENCE_EXCERPT_MAX_CHARS:
            break
    return "\n\n".join(chunk for index, chunk, _ in ranked if index in selected_indexes)


def _prepare_reference_excerpt(
    item: dict[str, Any], section: str, focus: JobFocus
) -> dict[str, Any]:
    """移除内部原文，只暴露可追溯的岗位相关节选与事实。"""
    result = deepcopy(item)
    content = str(result.pop(_REFERENCE_CONTENT_KEY, ""))
    file_name = str(result.pop(_REFERENCE_FILE_KEY, ""))
    excerpt = _select_reference_excerpt(content, section, focus)
    facts = _select_reference_facts(content, section, focus)
    return _with_reference_payload(result, file_name, excerpt, facts)


def _prepare_general_reference_excerpt(item: dict[str, Any]) -> dict[str, Any]:
    """通用简历（没有目标岗位）的参考节选：不按岗位打分，按原文顺序取靠前内容。

    **不能复用上面那个函数**：``_select_reference_facts`` 会把打分 ≤ 0 的事实全部跳过，
    没有岗位信号时一条都不剩；``_select_reference_excerpt`` 同理。结果是通用简历的附件
    事实被静默清空，还会连带让 ``has_reference_facts`` 变假，使强化模式的质量门槛和
    兜底恢复一起失效。
    """
    result = deepcopy(item)
    content = str(result.pop(_REFERENCE_CONTENT_KEY, ""))
    file_name = str(result.pop(_REFERENCE_FILE_KEY, ""))
    facts = _reference_fact_candidates(content)[:_REFERENCE_FACT_LIMIT]
    excerpt = _reference_head_excerpt(content)
    return _with_reference_payload(result, file_name, excerpt, facts)


def _with_reference_payload(
    result: dict[str, Any], file_name: str, excerpt: str, facts: list[str]
) -> dict[str, Any]:
    if excerpt or facts:
        result["reference_file_name"] = file_name
    if excerpt:
        result["reference_excerpt"] = excerpt
    if facts:
        result["reference_facts"] = facts
    return result


def _reference_head_excerpt(content: str) -> str:
    """按原文顺序取靠前的段落填满预算。"""
    selected: list[str] = []
    used_chars = 0
    for chunk in _reference_chunks(content):
        separator_size = 2 if selected else 0
        if selected and used_chars + separator_size + len(chunk) > _REFERENCE_EXCERPT_MAX_CHARS:
            break
        selected.append(chunk)
        used_chars += separator_size + len(chunk)
        if used_chars >= _REFERENCE_EXCERPT_MAX_CHARS:
            break
    return "\n\n".join(selected)
