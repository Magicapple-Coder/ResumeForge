"""把个人资料转换为岗位筛选和模型提示词使用的结构。"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from ..schemas.profile import ProfileOut
from .profile_relevance_constants import (
    SECTION_LIMITS,
    _LLM_PROFILE_FIELDS,
    _REFERENCE_CONTENT_KEY,
    _REFERENCE_FILE_KEY,
)


def split_lines(text: str) -> list[str]:
    """把换行文本拆成非空要点。"""
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def split_commas(text: str) -> list[str]:
    """把中英文逗号/顿号分隔的技能拆成数组。"""
    return [item.strip() for item in re.split(r"[,，、]", text) if item.strip()]


def _reference_fields(item: Any, include_references: bool) -> dict[str, str]:
    """内部保留参考原文用于检索；最终发送前会替换为岗位相关节选。"""
    if not include_references:
        return {}
    content = getattr(item, "reference_content", "").strip()
    if not content:
        return {}
    return {
        _REFERENCE_FILE_KEY: getattr(item, "reference_file_name", "").strip(),
        _REFERENCE_CONTENT_KEY: content,
    }


def build_profile_prompt_data(
    profile: ProfileOut, *, include_references: bool = False
) -> dict[str, Any]:
    """把完整资料规范化为模型可读结构；默认不携带参考文件。"""
    return {
        "name": profile.name,
        "gender": profile.gender,
        "birth_year": profile.birth_year,
        "phone": profile.phone,
        "email": profile.email,
        "city": profile.city,
        "target_city": profile.target_city,
        "job_intent": profile.job_intent,
        "personal_website": profile.personal_website,
        "github": profile.github,
        "summary": profile.summary,
        "educations": [
            {
                "school": item.school,
                "major": item.major,
                "degree": item.degree,
                "start_date": item.start_date,
                "end_date": item.end_date,
                "gpa": item.gpa,
                "courses": split_lines(item.courses),
                "achievements": split_lines(item.achievements),
                **_reference_fields(item, include_references),
            }
            for item in profile.educations
        ],
        "experiences": [
            {
                "company": item.company,
                "role": item.role,
                "start_date": item.start_date,
                "end_date": item.end_date,
                "description": split_lines(item.description),
                **_reference_fields(item, include_references),
            }
            for item in profile.experiences
        ],
        "campus_experiences": [
            {
                "organization": item.organization,
                "role": item.role,
                "start_date": item.start_date,
                "end_date": item.end_date,
                "description": split_lines(item.description),
                **_reference_fields(item, include_references),
            }
            for item in getattr(profile, "campus_experiences", [])
        ],
        "projects": [
            {
                "name": item.name,
                "role": item.role,
                "start_date": item.start_date,
                "end_date": item.end_date,
                "tech_stack": split_commas(item.tech_stack),
                "description": split_lines(item.description),
                "highlights": split_lines(item.highlights),
                **_reference_fields(item, include_references),
            }
            for item in profile.projects
        ],
        "skills": [{"name": item.name, "level": item.level} for item in profile.skills],
        "awards": [
            {"name": item.name, "date": item.date, "description": item.description}
            for item in profile.awards
        ],
    }


def build_llm_profile_prompt_data(data: dict[str, Any]) -> dict[str, Any]:
    """只保留岗位匹配需要的资料，避免把身份和联系方式发送给模型。"""
    return {
        key: deepcopy(data.get(key, [] if key in SECTION_LIMITS else ""))
        for key in _LLM_PROFILE_FIELDS
    }
