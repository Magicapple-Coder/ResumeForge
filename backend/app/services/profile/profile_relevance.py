"""岗位相关性筛选兼容门面。

实际职责按资料规范化、岗位匹配、参考文件和预算控制拆分到同目录模块；
本文件保留原有导入路径，并负责把这些纯函数编排成岗位专属候选上下文。
"""

from __future__ import annotations

import json
from typing import Any

from ...schemas.job import JobOut
from ...schemas.profile import ProfileOut
from .profile_budget import (
    _drop_one_detail,
    _dump,
    _trim_all_strings,
    _trim_middle,
    _trim_text,
    build_job_prompt_text,
    serialize_profile_prompt_data,
)
from .profile_context import (
    _reference_fields,
    build_llm_profile_prompt_data,
    build_profile_prompt_data,
    split_commas,
    split_lines,
)
from .profile_matching import (
    _contains,
    _item_text,
    _job_text,
    _matched_skills,
    _prioritize_item_details,
    _score_item,
    _select_entries,
    _select_ranked_items,
    _select_skills,
    _select_summary,
    _skill_domain_score,
    _take_entries,
    _unique,
    build_job_focus,
)
from .profile_references import (
    _clean_reference_fact_line,
    _prepare_general_reference_excerpt,
    _prepare_reference_excerpt,
    _reference_chunks,
    _reference_fact_candidates,
    _safe_reference_blocks,
    _select_reference_excerpt,
    _select_reference_facts,
    _strip_markdown,
)
from .profile_relevance_constants import (
    DOMAIN_CONTEXT_SIGNALS,
    DOMAIN_SIGNALS,
    SECTION_LIMITS,
    SECTION_PRIMARY_FIELDS,
    SKILL_DOMAIN_HINTS,
    JobFocus,
    ProfileSelection,
    _ASCII_TERM_RE,
    _LIST_DETAIL_FIELDS,
    _LLM_PROFILE_FIELDS,
    _MARKDOWN_LIST_PREFIX_RE,
    _MARKDOWN_TABLE_DIVIDER_RE,
    _MIN_PROFILE_CONTEXT_CHARS,
    _OPTIONAL_TOP_LEVEL_FIELDS,
    _REFERENCE_CONTENT_KEY,
    _REFERENCE_EXCERPT_MAX_CHARS,
    _REFERENCE_FACT_LIMIT,
    _REFERENCE_FACT_MAX_CHARS,
    _REFERENCE_FILE_KEY,
    _REFERENCE_INSTRUCTION_RE,
    _REFERENCE_META_RE,
    _REFERENCE_SECTIONS,
    _TITLE_SPLIT_RE,
)


_EMPTY_FOCUS = JobFocus(skills=(), domains=(), terms=())


def build_targeted_profile_context(
    profile: ProfileOut,
    job: JobOut,
    max_chars: int = 12_000,
    *,
    include_references: bool = False,
) -> ProfileSelection:
    """构建岗位专属候选资料，并在边界安全的预算内序列化。"""
    full = build_profile_prompt_data(profile, include_references=include_references)
    focus = build_job_focus(job, profile)
    selected: dict[str, Any] = {
        key: value for key, value in full.items() if key not in SECTION_LIMITS
    }
    # 当前岗位是本份简历的唯一求职意向；旧总结只保留有岗位交集的句子。
    selected["job_intent"] = job.title or full["job_intent"]
    selected["summary"] = _select_summary(full["summary"], focus)
    for section in ("educations", "experiences", "campus_experiences", "projects", "awards"):
        selected[section] = [
            _prepare_reference_excerpt(
                _prioritize_item_details(item, section, focus), section, focus
            )
            if include_references and section in _REFERENCE_SECTIONS
            else _prioritize_item_details(item, section, focus)
            for item in _select_entries(full[section], section, focus)
        ]
    evidence = {
        section: selected[section]
        for section in ("educations", "experiences", "campus_experiences", "projects")
    }
    selected["skills"] = _select_skills(full["skills"], evidence, focus)
    selected = build_llm_profile_prompt_data(selected)
    return _assemble_selection(full, selected, focus, max_chars)


def _assemble_selection(
    full: dict[str, Any],
    selected: dict[str, Any],
    focus: JobFocus,
    max_chars: int,
) -> ProfileSelection:
    """把已选好的候选资料做预算压缩并统计，供岗位与通用两条路径共用。"""
    serialized = serialize_profile_prompt_data(selected, max_chars)
    # ``serialize_profile_prompt_data`` 会在副本上做预算压缩；对外暴露的
    # data 必须与实际发送给模型的 JSON 完全一致，避免诊断和生成出现偏差。
    packed_data = json.loads(serialized)
    selected_counts = {section: len(packed_data[section]) for section in SECTION_LIMITS}
    omitted_counts = {
        section: max(0, len(full[section]) - selected_counts[section])
        for section in SECTION_LIMITS
    }
    return ProfileSelection(
        data=packed_data,
        serialized=serialized,
        focus=focus,
        selected_counts=selected_counts,
        omitted_counts=omitted_counts,
    )


def build_general_profile_context(
    profile: ProfileOut,
    max_chars: int = 12_000,
    *,
    include_references: bool = False,
) -> ProfileSelection:
    """构建**通用简历**的候选资料：不按岗位筛选，也不排序。

    做的是"全貌优先"：每个栏目按用户在资料页里的录入顺序取到该栏目上限，
    保留简历自己的求职意向与完整个人总结，校园经历同样保留（奖项在岗位路径上也会
    保留，见 ``_select_entries``）。

    **不要退化成"传一个空 focus 走岗位路径"**：那条路径在无信号时的行为并不是
    "保留全部"——它会丢掉校园经历、清空个人总结、并且只保留被证据提到的技能
    （见 ``_take_entries`` 的说明）。
    """
    full = build_profile_prompt_data(profile, include_references=include_references)
    selected: dict[str, Any] = {
        key: value for key, value in full.items() if key not in SECTION_LIMITS
    }
    # 求职意向沿用资料原文，不替换成任何岗位名；总结也保留用户自己写的那份。
    selected["summary"] = full["summary"]
    for section in ("educations", "experiences", "campus_experiences", "projects", "awards"):
        selected[section] = [
            _prepare_general_reference_excerpt(item)
            if include_references and section in _REFERENCE_SECTIONS
            else item
            for item in _take_entries(full[section], section)
        ]
    selected["skills"] = _take_entries(full["skills"], "skills")
    selected = build_llm_profile_prompt_data(selected)
    return _assemble_selection(full, selected, _EMPTY_FOCUS, max_chars)


def build_targeted_profile_prompt_data(
    profile: ProfileOut, job: JobOut, *, include_references: bool = False
) -> dict[str, Any]:
    """公开的纯函数入口，便于测试岗位不同导致的候选资料差异。"""
    return build_targeted_profile_context(
        profile, job, include_references=include_references
    ).data


__all__ = [
    "JobFocus",
    "ProfileSelection",
    "build_profile_prompt_data",
    "build_llm_profile_prompt_data",
    "build_job_focus",
    "build_job_prompt_text",
    "build_general_profile_context",
    "build_targeted_profile_context",
    "build_targeted_profile_prompt_data",
    "serialize_profile_prompt_data",
    "split_lines",
    "split_commas",
    "SECTION_LIMITS",
    "SECTION_PRIMARY_FIELDS",
    "DOMAIN_SIGNALS",
    "DOMAIN_CONTEXT_SIGNALS",
    "SKILL_DOMAIN_HINTS",
    "_TITLE_SPLIT_RE",
    "_ASCII_TERM_RE",
    "_LIST_DETAIL_FIELDS",
    "_OPTIONAL_TOP_LEVEL_FIELDS",
    "_LLM_PROFILE_FIELDS",
    "_MIN_PROFILE_CONTEXT_CHARS",
    "_REFERENCE_SECTIONS",
    "_REFERENCE_CONTENT_KEY",
    "_REFERENCE_FILE_KEY",
    "_REFERENCE_EXCERPT_MAX_CHARS",
    "_REFERENCE_FACT_MAX_CHARS",
    "_REFERENCE_FACT_LIMIT",
    "_REFERENCE_INSTRUCTION_RE",
    "_REFERENCE_META_RE",
    "_MARKDOWN_LIST_PREFIX_RE",
    "_MARKDOWN_TABLE_DIVIDER_RE",
    "_reference_fields",
    "_unique",
    "_contains",
    "_job_text",
    "_item_text",
    "_skill_domain_score",
    "_score_item",
    "_matched_skills",
    "_select_ranked_items",
    "_prioritize_item_details",
    "_select_summary",
    "_safe_reference_blocks",
    "_strip_markdown",
    "_clean_reference_fact_line",
    "_reference_fact_candidates",
    "_select_reference_facts",
    "_reference_chunks",
    "_select_reference_excerpt",
    "_prepare_reference_excerpt",
    "_select_entries",
    "_select_skills",
    "_dump",
    "_trim_text",
    "_trim_middle",
    "_drop_one_detail",
    "_trim_all_strings",
]
