"""匹配度参考分：五维本地规则打分，只读、仅展示、带免责。

与"五类结论 + 准入闸门"完全解耦：结论由 ``models.apply.admission_of`` 收口，本模块
**不复制、不重写**那套映射，只在结论之上附加一个 0-100 的参考分供用户自我评估。参考分
是**派生值**：不落库、不回写 ``job_match_analysis.result``，每次都从当前结论与来源文本
现算，避免陈旧分数。

固定 5 维常量表 ``MATCH_SCORE_DIMENSIONS``（``list[DimensionSpec]``），预留扩展——新增
维度只需向表中追加一条并给 ``_SUB_SCORERS`` 注册一个同 key 的打分函数。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from ..schemas.job_match import JobMatchResult, MatchReferenceScore, MatchScoreDimension

# 面向用户的免责文案：参考分是估算，不代表真实 ATS 解析率或投递成功概率。
_DISCLAIMER = (
    "本参考分由本地规则估算，仅供展示与自我评估，不代表真实 ATS 解析结果或投递成功概率；"
    "投递准入仍以五类匹配结论为准。"
)

# 信号缺失时的中性分：不把"没信息"误报成"不匹配"。
_NEUTRAL_SCORE = 50

# 单条匹配状态 → 0-1 的达成度（**只用于展示分，不改变准入结论**）。
_STATUS_ATTAINMENT = {
    "matched": 1.0,
    "expression_gap": 0.6,
    "evidence_insufficient": 0.4,
    "to_confirm": 0.3,
    "real_gap": 0.0,
}

# 关键词提取时剔除的常见停用词（避免把"经验/能力"这类词算成命中）。
_STOP_TOKENS = {
    "的", "与", "和", "及", "等", "或", "熟悉", "精通", "优先", "经验", "以上",
    "相关", "能力", "负责", "要求", "任职", "岗位", "工作", "具有", "具备", "有",
    "年", "加分", "者", "优先考虑",
}


@dataclass(frozen=True)
class DimensionSpec:
    """一个打分维度的元数据：``key`` 定位打分函数，``weight`` 用于加权求和。"""

    key: str
    label: str
    weight: float


MATCH_SCORE_DIMENSIONS: list[DimensionSpec] = [
    DimensionSpec(key="skill_coverage", label="技能覆盖", weight=0.25),
    DimensionSpec(key="experience_years", label="年限", weight=0.15),
    DimensionSpec(key="project_relevance", label="项目相关度", weight=0.20),
    DimensionSpec(key="hard_gate", label="硬性门槛", weight=0.20),
    DimensionSpec(key="jd_keyword_coverage", label="JD 关键词覆盖", weight=0.20),
]


def _clamp(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _attainment(condition: Any) -> float:
    return _STATUS_ATTAINMENT.get(getattr(condition, "status", ""), 0.3)


def _normalize(value: str) -> str:
    return "".join(str(value).split()).casefold()


def _jd_tokens(job_payload: dict[str, Any]) -> set[str]:
    """从 JD 里提取关键词集合（含中文与英文，过滤停用词）。"""
    text = " ".join(
        str(job_payload.get(key, ""))
        for key in ("description", "requirements", "additional_info")
    )
    tokens: set[str] = set()
    for item in re.findall(r"[\w\u4e00-\u9fff]+", text):
        token = item.casefold()
        if len(token) < 2 or token in _STOP_TOKENS:
            continue
        tokens.add(token)
    return tokens


def _required_years(job_payload: dict[str, Any]) -> int | None:
    text = " ".join(
        str(job_payload.get(key, ""))
        for key in ("description", "requirements", "additional_info")
    )
    matches = re.findall(r"(\d+)\s*年", text)
    if not matches:
        return None
    return max(int(value) for value in matches)


def _year(value: str) -> int | None:
    match = re.search(r"(\d{4})", str(value or ""))
    return int(match.group(1)) if match else None


def _estimate_years(profile_text: str, resume_text: str) -> float:
    """粗略估算工作年限：从资料 / 简历 JSON 里取经历起止年份求和。"""
    entries: list[tuple[int | None, int | None]] = []
    for text in (profile_text, resume_text):
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        candidates: list[Any] = list(data.get("experiences") or [])
        content = data.get("content")
        if isinstance(content, dict):
            candidates.extend(content.get("experience") or [])
        for item in candidates:
            if not isinstance(item, dict):
                continue
            start = _year(item.get("start_date", ""))
            if start is None:
                continue
            entries.append((start, _year(item.get("end_date", ""))))
    total = 0.0
    for start, end in entries:
        if end is not None and end > start:
            total += end - start
        else:
            total += 0.5
    return round(total, 1)


def _project_tokens(resume_text: str) -> set[str]:
    """从简历 JSON 里取项目名与技术栈，作为"项目相关度"的比对键。"""
    tokens: set[str] = set()
    try:
        data = json.loads(resume_text)
    except (json.JSONDecodeError, TypeError):
        return tokens
    if not isinstance(data, dict):
        return tokens
    content = data.get("content", data)
    projects = content.get("projects") or [] if isinstance(content, dict) else []
    for project in projects:
        if not isinstance(project, dict):
            continue
        name = project.get("name", "")
        if name:
            tokens.add(_normalize(name))
        for tech in project.get("tech_stack") or []:
            if tech:
                tokens.add(_normalize(str(tech)))
    return tokens


def _score_skill_coverage(
    result: JobMatchResult,
    job_payload: dict[str, Any],
    profile_text: str,
    resume_text: str,
) -> tuple[int, str]:
    conditions = [*result.core_abilities, *result.bonus_items]
    if not conditions:
        return _NEUTRAL_SCORE, "无核心能力/加分项条目，无法估算"
    total = sum(_attainment(item) for item in conditions)
    matched = sum(1 for item in conditions if item.status == "matched")
    return _clamp(total / len(conditions) * 100), f"核心/加分项共 {len(conditions)} 条，已匹配 {matched} 条"


def _score_experience_years(
    result: JobMatchResult,
    job_payload: dict[str, Any],
    profile_text: str,
    resume_text: str,
) -> tuple[int, str]:
    required = _required_years(job_payload)
    actual = _estimate_years(profile_text, resume_text)
    if required is None:
        return _NEUTRAL_SCORE, "JD 未写明年限要求，无法比较"
    if actual <= 0:
        return 0, f"要求约 {required} 年，简历中未识别到工作年限"
    ratio = min(actual / required, 1.0)
    return _clamp(ratio * 100), f"约 {actual} 年 / 要求 {required} 年"


def _score_project_relevance(
    result: JobMatchResult,
    job_payload: dict[str, Any],
    profile_text: str,
    resume_text: str,
) -> tuple[int, str]:
    project_tokens = _project_tokens(resume_text)
    jd_tokens = _jd_tokens(job_payload)
    if not project_tokens:
        return _NEUTRAL_SCORE, "简历中未识别到项目，无法估算相关度"
    matched = sorted(project_tokens & jd_tokens)
    score = _clamp(len(matched) / max(1, len(project_tokens)) * 100)
    evidence = f"项目关键词命中 {len(matched)}/{len(project_tokens)}"
    if matched:
        evidence += f"：{'、'.join(matched[:5])}"
    return score, evidence


def _score_hard_gate(
    result: JobMatchResult,
    job_payload: dict[str, Any],
    profile_text: str,
    resume_text: str,
) -> tuple[int, str]:
    hard = result.hard_conditions
    if result.hard_gate == "met":
        return 100, "硬性门槛已满足"
    if result.hard_gate == "unmet":
        return 0, "存在不满足的硬性条件"
    if not hard:
        return _NEUTRAL_SCORE, "未识别到硬性条件"
    total = sum(_attainment(item) for item in hard)
    return _clamp(total / len(hard) * 100), f"硬性条件 {len(hard)} 条，结论未明确"


def _score_jd_keyword_coverage(
    result: JobMatchResult,
    job_payload: dict[str, Any],
    profile_text: str,
    resume_text: str,
) -> tuple[int, str]:
    jd_tokens = _jd_tokens(job_payload)
    if not jd_tokens:
        return _NEUTRAL_SCORE, "JD 中未提取到关键词"
    personal = _normalize(f"{profile_text}\n{resume_text}")
    covered = [token for token in jd_tokens if token in personal]
    score = _clamp(len(covered) / len(jd_tokens) * 100)
    return score, f"JD 关键词命中 {len(covered)}/{len(jd_tokens)}"


# 打分函数统一签名：key → (result, job_payload, profile_text, resume_text) -> (score, evidence)。
_SUB_SCORERS: dict[str, Callable[..., tuple[int, str]]] = {
    "skill_coverage": _score_skill_coverage,
    "experience_years": _score_experience_years,
    "project_relevance": _score_project_relevance,
    "hard_gate": _score_hard_gate,
    "jd_keyword_coverage": _score_jd_keyword_coverage,
}


def score_match_result(
    result: JobMatchResult,
    job_payload: dict[str, Any],
    profile_text: str,
    resume_text: str,
) -> MatchReferenceScore:
    """计算 0-100 参考分与 5 个分项（纯本地规则，不落库、不改变准入结论）。"""
    dimensions: list[MatchScoreDimension] = []
    total = 0.0
    for spec in MATCH_SCORE_DIMENSIONS:
        scorer = _SUB_SCORERS.get(spec.key)
        if scorer is None:
            continue
        sub_score, evidence = scorer(result, job_payload, profile_text, resume_text)
        dimensions.append(
            MatchScoreDimension(
                key=spec.key,
                label=spec.label,
                score=sub_score,
                weight=spec.weight,
                evidence=evidence,
            )
        )
        total += sub_score * spec.weight
    return MatchReferenceScore(score=_clamp(total), dimensions=dimensions, disclaimer=_DISCLAIMER)


__all__ = [
    "DimensionSpec",
    "MATCH_SCORE_DIMENSIONS",
    "score_match_result",
]
