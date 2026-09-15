"""岗位与个人资料 AI 抽取结果的字段边界、事实锚定和合并。"""

import re
from typing import Any
from urllib.parse import urlsplit

from ..schemas.job import JobTextParseResult
from ..schemas.profile import ProfileTextParseResult
from .llm.base import LLMError

_JOB_FIELDS = (
    "title",
    "company",
    "location",
    "salary",
    "job_type",
    "description",
    "requirements",
    "additional_info",
    "source_url",
    "posted_at",
    "status",
)
_JOB_TEXT_LIMITS = {
    "title": 128,
    "company": 128,
    "location": 64,
    "salary": 64,
    "job_type": 32,
    "description": 200_000,
    "requirements": 200_000,
    "additional_info": 200_000,
    "source_url": 512,
    "posted_at": 32,
    "status": 16,
}
_JOB_TYPES = {"校招", "实习", "社招", "其他"}

_PROFILE_BASIC_LIMITS = {
    "name": 64,
    "gender": 64,
    "birth_year": 32,
    "phone": 32,
    "email": 128,
    "city": 64,
    "target_city": 64,
    "job_intent": 128,
    "personal_website": 256,
    "github": 256,
    "summary": 200_000,
}
_PROFILE_ENTRY_LIMITS = {
    "educations": {
        "school": 128,
        "major": 128,
        "degree": 32,
        "start_date": 32,
        "end_date": 32,
        "gpa": 64,
        "courses": 200_000,
        "achievements": 200_000,
    },
    "experiences": {
        "company": 128,
        "role": 128,
        "start_date": 32,
        "end_date": 32,
        "description": 200_000,
    },
    "campus_experiences": {
        "organization": 128,
        "role": 128,
        "start_date": 32,
        "end_date": 32,
        "description": 200_000,
    },
    "projects": {
        "name": 128,
        "role": 64,
        "start_date": 32,
        "end_date": 32,
        "tech_stack": 10_000,
        "description": 200_000,
        "highlights": 200_000,
    },
    "skills": {"name": 64, "level": 32},
    "awards": {"name": 128, "date": 32, "description": 2_000},
}
_IDENTITY_FIELDS = {
    "educations": ("school", "major"),
    "experiences": ("company", "role"),
    "campus_experiences": ("organization", "role"),
    "projects": ("name", "role"),
    "skills": ("name",),
    "awards": ("name",),
}
_TOKEN_SPLIT_RE = re.compile(r"[,，、;；/|]+")


def _bounded_text(value: Any, limit: int, state: dict[str, bool]) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if not isinstance(value, (str, int, float)):
        return ""
    text = str(value).strip()
    if len(text) > limit:
        state["truncated"] = True
        return text[:limit]
    return text


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _is_grounded(value: str, source_text: str) -> bool:
    normalized = _normalized(value)
    return bool(normalized) and normalized in _normalized(source_text)


def _pick_grounded(value: str, fallback: str, source_text: str) -> str:
    if value and _is_grounded(value, source_text):
        return value
    return fallback


def _safe_source_url(value: str, source_text: str) -> str:
    if not value or not _is_grounded(value, source_text):
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    return value


def normalize_job_result(
    data: dict[str, Any], local: JobTextParseResult, source_text: str
) -> JobTextParseResult:
    state = {"truncated": False}
    values = {
        field: _bounded_text(data.get(field), _JOB_TEXT_LIMITS[field], state)
        for field in _JOB_FIELDS
    }
    for field in ("title", "company", "location", "salary"):
        values[field] = _pick_grounded(values[field], getattr(local, field), source_text)
    values["job_type"] = values["job_type"] if values["job_type"] in _JOB_TYPES else local.job_type
    values["source_url"] = local.source_url or _safe_source_url(values["source_url"], source_text)
    values["posted_at"] = _pick_grounded(values["posted_at"], local.posted_at, source_text)
    values["status"] = local.status
    for field in ("description", "requirements", "additional_info"):
        values[field] = _pick_grounded(values[field], getattr(local, field), source_text)
    if not any(values[field] for field in ("title", "company", "description", "requirements")):
        raise LLMError("模型未识别到有效岗位字段，请重试")
    warnings = ["AI 结果已通过字段和来源校验，请核对后保存。"]
    if state["truncated"]:
        warnings.append("部分 AI 识别字段超过可保存长度，已截断，请核对。")
    return JobTextParseResult.model_validate(
        {**values, "warnings": warnings, "recognition_source": "ai"}
    )


def _entry_values(section: str, value: Any, state: dict[str, bool]) -> list[dict[str, str]]:
    if isinstance(value, dict):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value[:200]
        if len(value) > 200:
            state["truncated"] = True
    elif section == "skills" and isinstance(value, str):
        raw_items = [{"name": token.strip()} for token in _TOKEN_SPLIT_RE.split(value) if token.strip()]
    else:
        raw_items = []

    limits = _PROFILE_ENTRY_LIMITS[section]
    result = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        normalized = {
            field: _bounded_text(item.get(field), limit, state) for field, limit in limits.items()
        }
        if any(normalized.values()):
            result.append(normalized)
    return result


def _entry_anchor(section: str, item: dict[str, Any]) -> str:
    for field in _IDENTITY_FIELDS[section]:
        value = item.get(field, "")
        if value:
            return _normalized(value)
    return ""


def _ground_entries(
    section: str, entries: list[dict[str, str]], source_text: str
) -> list[dict[str, str]]:
    """丢弃无身份锚点条目，并移除未被原文支持的单个字段。"""
    grounded = []
    for item in entries:
        anchors = [item.get(field, "") for field in _IDENTITY_FIELDS[section]]
        if any(_is_grounded(anchor, source_text) for anchor in anchors if len(anchor) >= 2):
            grounded.append(
                {
                    field: value if _is_grounded(value, source_text) else ""
                    for field, value in item.items()
                }
            )
    return grounded


def _merge_entries(
    section: str, ai_entries: list[dict[str, str]], local_entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not ai_entries:
        return local_entries
    local_by_anchor = {
        anchor: item for item in local_entries if (anchor := _entry_anchor(section, item))
    }
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for ai_item in ai_entries:
        anchor = _entry_anchor(section, ai_item)
        local_item = local_by_anchor.get(anchor)
        if local_item is None:
            merged.append(ai_item)
        else:
            # 已通过原文锚定的 AI 字段可纠正本地分类；空字段仍保留本地草稿。
            merged.append(
                {
                    **local_item,
                    **{field: value for field, value in ai_item.items() if value},
                }
            )
        if anchor:
            seen.add(anchor)
    for item in local_entries:
        anchor = _entry_anchor(section, item)
        if not anchor or anchor not in seen:
            merged.append(item)
            if anchor:
                seen.add(anchor)
    return merged[:200]


def normalize_profile_result(
    data: dict[str, Any], local: ProfileTextParseResult, source_text: str
) -> ProfileTextParseResult:
    if isinstance(data.get("profile"), dict):
        data = data["profile"]
    state = {"truncated": False}
    local_data = local.model_dump()
    values = {
        field: _bounded_text(data.get(field), limit, state)
        for field, limit in _PROFILE_BASIC_LIMITS.items()
    }
    for field in _PROFILE_BASIC_LIMITS:
        values[field] = _pick_grounded(values[field], getattr(local, field), source_text)
    if not values["summary"]:
        values["summary"] = local.summary

    for section in _PROFILE_ENTRY_LIMITS:
        ai_entries = _ground_entries(
            section, _entry_values(section, data.get(section), state), source_text
        )
        values[section] = _merge_entries(section, ai_entries, local_data.get(section, []))

    if not any(
        [values["name"], values["summary"], *(values[section] for section in _PROFILE_ENTRY_LIMITS)]
    ):
        raise LLMError("模型未识别到有效个人资料字段，请重试")
    warnings = ["AI 结果已通过字段和来源校验，请核对后保存。"]
    if state["truncated"]:
        warnings.append("部分 AI 识别字段超过可保存长度，已截断，请核对。")
    return ProfileTextParseResult.model_validate(
        {
            **values,
            "photo": "",
            "section_order": list(local.section_order),
            "warnings": warnings,
            "recognition_source": "ai",
        }
    )
