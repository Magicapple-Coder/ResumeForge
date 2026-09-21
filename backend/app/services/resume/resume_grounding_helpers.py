"""简历事实回填使用的纯匹配、证据和参考事实工具。"""

from __future__ import annotations

import re
from copy import deepcopy

from ...schemas.job import JobOut

_REFERENCE_FALLBACK_LIMITS = {"light": 2, "balanced": 3, "strong": 5}


def _similar(a: str, b: str) -> bool:
    """双向包含判断，容忍模型对名称的轻度改写。"""
    return bool(a and b) and (a in b or b in a)


def _similar_skill(a: str, b: str) -> bool:
    """技能名匹配：避免单字母技能把普通英文单词误判为同一技能。"""
    left = re.sub(r"\s+", "", a).casefold()
    right = re.sub(r"\s+", "", b).casefold()
    if not left or not right:
        return False
    if left == right:
        return True
    if len(left) < 3 or len(right) < 3:
        return False
    return left in right or right in left


def _source_value(source, field: str) -> str:
    if isinstance(source, dict):
        value = source.get(field, "")
    else:
        value = getattr(source, field, "")
    return value if isinstance(value, str) else ""


def _find_source(item, sources: list[dict], name_field: str, role_field: str | None = None):
    """按名称找候选源条目；无法唯一定位时宁可不使用该条输出。"""
    name = getattr(item, name_field, "")
    if not name:
        return None
    candidates = [
        source for source in sources if _similar(name, _source_value(source, name_field))
    ]
    if len(candidates) > 1 and role_field:
        role = getattr(item, role_field, "")
        role_matches = [
            source
            for source in candidates
            if role and _similar(role, _source_value(source, role_field))
        ]
        if role_matches:
            candidates = role_matches
    if len(candidates) > 1:
        start_date = getattr(item, "start_date", "")
        end_date = getattr(item, "end_date", "")
        date_matches = [
            source
            for source in candidates
            if (not start_date or start_date == _source_value(source, "start_date"))
            and (not end_date or end_date == _source_value(source, "end_date"))
        ]
        if date_matches:
            candidates = date_matches
    return candidates[0] if len(candidates) == 1 else None


_FACT_SEPARATOR_RE = re.compile(r"[\s,，、;；:：。.!！？!?()（）\[\]【】\"'`]+")


def _normalize_fact(value: str) -> str:
    """规范化要点文本，用于严格匹配，不把多个事实混为一个。"""
    return _FACT_SEPARATOR_RE.sub("", value).casefold()


def _ground_list(generated: list[str], source: list[str]) -> list[str]:
    """把模型选中的要点映射回同一来源的原始事实。"""
    canonical_sources = [
        (original, _normalize_fact(original))
        for original in source
        if original and _normalize_fact(original)
    ]
    result: list[str] = []
    seen: set[str] = set()
    for value in generated:
        normalized = _normalize_fact(value)
        if not normalized:
            continue
        matches = [
            (original, source_value)
            for original, source_value in canonical_sources
            if normalized == source_value or (len(normalized) >= 2 and normalized in source_value)
        ]
        if not matches:
            continue
        original, source_value = min(matches, key=lambda item: len(item[1]))
        if source_value not in seen:
            seen.add(source_value)
            result.append(original)
    return result


_QUANTIFIED_VALUE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:[%％]|倍|万|千|[kK]|次|人|个|项|条|页|张|表|字段|接口|路径|"
    r"种|端|套|层|模块|功能|毫秒|ms|秒|天|小时|年|个月)"
)


def _unsupported_quantified_values(values: list[str] | str, source_text: str) -> list[str]:
    """找出候选事实中没有出现过的量化结果。"""
    texts = [values] if isinstance(values, str) else values
    normalized_source = re.sub(r"\s+", "", source_text)
    unsupported: list[str] = []
    for text in texts:
        for value in _QUANTIFIED_VALUE_RE.findall(text):
            normalized_value = re.sub(r"\s+", "", value)
            if normalized_value not in normalized_source and value not in unsupported:
                unsupported.append(value)
    return unsupported


def _source_list(source: dict, field: str) -> list[str]:
    value = source.get(field, [])
    return value if isinstance(value, list) else []


def _ground_or_restore_list(generated: list[str], source: list[str]) -> list[str]:
    """优先保留模型明确选择的事实；无法验证时回填来源。"""
    grounded = _ground_list(generated, source)
    return grounded or list(source)


def _source_evidence_text(source: dict, fields: tuple[str, ...]) -> str:
    """合并条目录入事实与岗位相关附件证据，供量化结果校验。"""
    values = [value for field in fields for value in _source_list(source, field)]
    values.extend(_source_list(source, "reference_facts"))
    excerpt = _source_value(source, "reference_excerpt")
    if excerpt:
        values.append(excerpt)
    return "\n".join(values)


def _enhance_or_restore_list(
    generated: list[str], source: list[str], source_evidence: str
) -> list[str]:
    """美化模式保留改写，但过滤来源无法支持的量化断言。"""
    if not source_evidence.strip():
        return list(source)
    accepted: list[str] = []
    seen: set[str] = set()
    for value in generated:
        cleaned = value.strip()
        normalized = _normalize_fact(cleaned)
        if (
            not cleaned
            or not normalized
            or normalized in seen
            or _unsupported_quantified_values([cleaned], source_evidence)
        ):
            continue
        seen.add(normalized)
        accepted.append(cleaned)
    return accepted or list(source)


def _build_grounded_summary(selected_data: dict, job: JobOut | None = None) -> str:
    """用已选事实生成不依赖模型自由发挥的摘要。

    ``job is None`` 是通用简历（无目标岗位）：措辞里不能出现"面向某某岗位"，
    也不该说技能"与岗位匹配"。
    """
    evidence: list[str] = []
    for item in selected_data.get("experiences", [])[:2]:
        company = _source_value(item, "company")
        role = _source_value(item, "role")
        if company or role:
            evidence.append(" ".join(value for value in (company, role) if value))
    for item in selected_data.get("projects", [])[:2]:
        name = _source_value(item, "name")
        role = _source_value(item, "role")
        if name or role:
            evidence.append(" ".join(value for value in (name, role) if value))

    skills = [
        _source_value(item, "name")
        for item in selected_data.get("skills", [])[:6]
        if _source_value(item, "name")
    ]
    sentences: list[str] = []
    selected_summary = _source_value(selected_data, "summary").strip()
    if selected_summary:
        # 这是用户资料中已通过岗位相关性筛选的原文，不是模型生成的断言。
        sentences.append(selected_summary)
    if job is not None:
        if evidence:
            sentences.append(f"面向{job.title}，具备{'、'.join(evidence)}等相关经历。")
        else:
            sentences.append(f"面向{job.title}求职。")
    elif evidence:
        sentences.append(f"具备{'、'.join(evidence)}等相关经历。")
    if skills:
        sentences.append(
            f"已掌握{'、'.join(skills)}等与岗位匹配的技能。"
            if job is not None
            else f"已掌握{'、'.join(skills)}等技能。"
        )
    return "".join(sentences)


def _reference_fallback_facts(source: dict, enhancement_level: str) -> list[str]:
    """返回已清洗且实际进入候选上下文的附件事实。"""
    limit = _REFERENCE_FALLBACK_LIMITS.get(enhancement_level, 3)
    return [
        value.strip()
        for value in _source_list(source, "reference_facts")[:limit]
        if isinstance(value, str) and value.strip()
    ]


def _selected_data_with_reference_fallbacks(
    selected_data: dict, enhancement_level: str
) -> dict:
    """为模型整段遗漏的区块补入同条目的附件事实。"""
    fallback_data = deepcopy(selected_data)
    for item in fallback_data.get("educations", []):
        if not item.get("achievements"):
            item["achievements"] = _reference_fallback_facts(item, enhancement_level)
    for section in ("experiences", "campus_experiences"):
        for item in fallback_data.get(section, []):
            if not item.get("description"):
                item["description"] = _reference_fallback_facts(item, enhancement_level)
    for item in fallback_data.get("projects", []):
        if not item.get("description") and not item.get("highlights"):
            item["description"] = _reference_fallback_facts(item, enhancement_level)
    return fallback_data


__all__ = [
    "_REFERENCE_FALLBACK_LIMITS",
    "_similar",
    "_similar_skill",
    "_source_value",
    "_find_source",
    "_normalize_fact",
    "_ground_list",
    "_unsupported_quantified_values",
    "_source_list",
    "_ground_or_restore_list",
    "_source_evidence_text",
    "_enhance_or_restore_list",
    "_build_grounded_summary",
    "_reference_fallback_facts",
    "_selected_data_with_reference_fallbacks",
]
