"""岗位信号提取、资料相关性评分和候选条目选择。"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from ..schemas.job import JobOut
from ..schemas.profile import ProfileOut
from .jd_parser import parse_jd
from .profile_relevance_constants import (
    DOMAIN_CONTEXT_SIGNALS,
    DOMAIN_SIGNALS,
    SECTION_LIMITS,
    SECTION_PRIMARY_FIELDS,
    SKILL_DOMAIN_HINTS,
    JobFocus,
    _ASCII_TERM_RE,
    _LIST_DETAIL_FIELDS,
    _TITLE_SPLIT_RE,
)


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip().casefold()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value.strip())
    return result


def _contains(text: str, term: str) -> bool:
    """匹配短英文词时使用边界，避免 ``C`` 命中 ``CapCut``。"""
    text = text.casefold()
    term = term.strip().casefold()
    if not term or (not _ASCII_TERM_RE.search(term) and len(term) < 2):
        return False
    if _ASCII_TERM_RE.search(term):
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text) is not None
    return term in text


def _job_text(job: JobOut) -> str:
    # 公司名不参与匹配，避免资料中恰好出现同名公司而抬高无关经历。
    return "\n".join(
        value
        for value in (job.title, job.description, job.requirements, job.additional_info)
        if value
    )


def build_job_focus(job: JobOut, profile: ProfileOut | None = None) -> JobFocus:
    """提取岗位技能、方向和标题短语；所有信号都来自岗位文本。"""
    text = _job_text(job)
    parsed = parse_jd(text)
    parsed_skills = [item.name for item in parsed["skills"]]
    saved_skills = [
        item.name if hasattr(item, "name") else str(item.get("name", ""))
        for item in (job.keywords or [])
    ]
    skills = _unique(parsed_skills + saved_skills)

    # 用户自定义技能不一定在内置词典中；若其名称出现在 JD，就把它作为硬信号。
    if profile is not None:
        skills.extend(
            item.name
            for item in profile.skills
            if item.name and _contains(text, item.name)
        )
        skills = _unique(skills)

    domains = [
        domain
        for domain, signals in DOMAIN_SIGNALS.items()
        if any(_contains(text, signal) for signal in signals)
    ]
    title_terms = [term for term in _TITLE_SPLIT_RE.split(job.title) if len(term.strip()) >= 2]
    domain_terms = [
        signal
        for domain in domains
        for signal in DOMAIN_SIGNALS[domain]
        if _contains(text, signal)
    ]
    terms = _unique(skills + title_terms + domain_terms)
    return JobFocus(skills=tuple(skills), domains=tuple(domains), terms=tuple(terms))


def _item_text(item: dict[str, Any]) -> str:
    return json.dumps(item, ensure_ascii=False)


def _skill_domain_score(name: str, domains: tuple[str, ...]) -> int:
    return sum(
        4
        for domain in domains
        if any(_contains(name, hint) for hint in SKILL_DOMAIN_HINTS.get(domain, ()))
    )


def _score_item(item: dict[str, Any], section: str, focus: JobFocus) -> int:
    text = _item_text(item)
    score = 0
    for skill in focus.skills:
        if _contains(text, skill):
            score += 12
    for term in focus.terms:
        if term.casefold() in {skill.casefold() for skill in focus.skills}:
            continue
        if _contains(text, term):
            score += 4 if section in {"experiences", "projects", "campus_experiences"} else 3
    for domain, signals in DOMAIN_SIGNALS.items():
        if domain not in focus.domains:
            continue
        score += sum(2 for signal in signals if _contains(text, signal))
        score += sum(
            1
            for signal in DOMAIN_CONTEXT_SIGNALS.get(domain, ())
            if _contains(text, signal)
        )
    if section == "skills":
        score += _skill_domain_score(item.get("name", ""), focus.domains)
    return score


def _matched_skills(item: dict[str, Any], focus: JobFocus) -> set[str]:
    """返回该条资料明确覆盖的 JD 技能，用于避免 Top-K 重复命中同一项。"""
    text = _item_text(item)
    return {skill.casefold() for skill in focus.skills if _contains(text, skill)}


def _select_ranked_items(
    ranked: list[tuple[int, dict[str, Any], int, set[str]]], limit: int
) -> list[dict[str, Any]]:
    """先用有限名额覆盖更多直接技能，再按总相关度补齐。"""
    selected_indexes: set[int] = set()
    uncovered = {skill for _, _, _, skills in ranked for skill in skills}

    while len(selected_indexes) < limit:
        choices = [item for item in ranked if item[0] not in selected_indexes]
        if not choices:
            break
        index, _, _, skills = max(
            choices,
            key=lambda item: (len(item[3] & uncovered), item[2], -item[0]),
        )
        selected_indexes.add(index)
        uncovered -= skills

    # ``ranked`` 本身已经按相关度排序；上一步完成技能覆盖后保留这个顺序。
    return [item for index, item, _, _ in ranked if index in selected_indexes]


def _prioritize_item_details(
    item: dict[str, Any], section: str, focus: JobFocus
) -> dict[str, Any]:
    """将直接命中 JD 的要点前置，供后续预算压缩优先保留。"""
    result = deepcopy(item)
    for field in _LIST_DETAIL_FIELDS:
        values = result.get(field)
        if not isinstance(values, list):
            continue
        result[field] = [
            value
            for _, value in sorted(
                enumerate(values),
                key=lambda pair: (
                    -_score_item({field: pair[1]}, section, focus),
                    pair[0],
                ),
            )
        ]
    return result


def _select_summary(summary: str, focus: JobFocus) -> str:
    """只保留与岗位有明确交集的个人总结句，避免全量总结绕过筛选。"""
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？!?])|[\r\n]+", summary)
        if sentence.strip()
    ]
    matching = [
        sentence
        for sentence in sentences
        if _score_item({"summary": sentence}, "projects", focus) > 0
    ]
    return " ".join(matching[:2])


def _select_entries(
    items: list[dict[str, Any]], section: str, focus: JobFocus
) -> list[dict[str, Any]]:
    primary_field = SECTION_PRIMARY_FIELDS[section]
    valid_items = [item for item in items if str(item.get(primary_field, "")).strip()]
    if not valid_items:
        return []
    ranked = sorted(
        (
            (index, item, _score_item(item, section, focus), _matched_skills(item, focus))
            for index, item in enumerate(valid_items)
        ),
        key=lambda item: (-item[2], item[0]),
    )
    limit = SECTION_LIMITS[section]
    matching = [item for item in ranked if item[2] > 0]
    if matching:
        # 有明确匹配时不混入零分条目，避免"资料库越全，简历越跑题"。
        return _select_ranked_items(matching, limit)
    if section in {"campus_experiences", "awards"}:
        # 校园/奖项不是每个岗位都需要，用无关条目填充反而稀释重点。
        return []
    if section == "educations":
        # 教育背景是校招简历的基础信息，即使 JD 未命中课程也保留一条。
        return [ranked[0][1]]
    if focus.skills or focus.domains or focus.terms:
        # 已经能识别岗位要求时，不用资料录入顺序填充无关经历/项目。
        return []
    # 排名顺序本身传给模型，首项就是最值得优先呈现的事实。
    return [item for _, item, _, _ in ranked[:limit]]


def _select_skills(
    items: list[dict[str, Any]], evidence: dict[str, Any], focus: JobFocus
) -> list[dict[str, Any]]:
    evidence_text = _item_text(evidence)
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, item in enumerate(item for item in items if str(item.get("name", "")).strip()):
        score = _score_item(item, "skills", focus)
        if item.get("name") and _contains(evidence_text, item["name"]):
            score += 5
        ranked.append((score, index, item))
    ranked.sort(key=lambda value: (-value[0], value[1]))
    matching = [item for score, _, item in ranked if score > 0]
    if matching:
        return matching[: SECTION_LIMITS["skills"]]
    if focus.skills or focus.domains or focus.terms:
        return []
    # JD 未给出可识别信号时保留有限技能作为兜底，避免生成空技能区。
    return [item for _, _, item in ranked[: SECTION_LIMITS["skills"]]]
