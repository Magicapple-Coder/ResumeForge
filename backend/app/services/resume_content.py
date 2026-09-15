"""模型简历 JSON 的容错解析和结构化转换。"""

import json
import re

from ..schemas.resume import ResumeContent
from .profile_context import split_lines


# 简历结构中的"列表字段"，宽松校验时字符串会被拆分补全。
_LIST_FIELDS = {
    "education": {
        "str_fields": {"school", "major", "degree", "start_date", "end_date", "gpa"},
        "list_fields": {"courses", "achievements"},
    },
    "experience": {
        "str_fields": {"company", "role", "start_date", "end_date"},
        "list_fields": {"description"},
    },
    "campus_experience": {
        "str_fields": {"organization", "role", "start_date", "end_date"},
        "list_fields": {"description"},
    },
    "projects": {
        "str_fields": {"name", "role", "start_date", "end_date"},
        "list_fields": {"tech_stack", "description", "highlights"},
    },
}

# 兼容新模块内更直观的名称，同时让旧门面继续暴露 ``_LIST_FIELDS``。
LIST_FIELDS = _LIST_FIELDS


def extract_json(text: str) -> dict | None:
    """从模型输出中提取 JSON 对象。"""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and isinstance(data.get("resume"), dict):
        data = data["resume"]
    return data if isinstance(data, dict) else None


def _string_list(value) -> list[str]:
    """宽松转字符串数组：列表取字符串元素，字符串按行拆分，其他返回空。"""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return split_lines(value)
    return []


def _item_list(value, str_fields: set[str], list_fields: set[str]) -> list[dict]:
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    result = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        item = {
            field: entry.get(field) if isinstance(entry.get(field), str) else ""
            for field in str_fields
        }
        for field in list_fields:
            item[field] = _string_list(entry.get(field))
        result.append(item)
    return result


def coerce_resume(data: dict | None) -> ResumeContent:
    """宽松校验：字段缺失补默认值、类型不对尽量修正。"""
    data = data or {}

    def as_str(value) -> str:
        return value if isinstance(value, str) else ""

    sections = {}
    for section, config in _LIST_FIELDS.items():
        sections[section] = _item_list(
            data.get(section), config["str_fields"], config["list_fields"]
        )
    skills = [
        {"name": item.get("name", ""), "level": item.get("level", "")}
        for item in _item_list(data.get("skills"), {"name", "level"}, set())
    ]
    awards = [
        {
            "name": item.get("name", ""),
            "date": item.get("date", ""),
            "description": item.get("description", ""),
        }
        for item in _item_list(data.get("awards"), {"name", "date", "description"}, set())
    ]
    return ResumeContent(
        name=as_str(data.get("name")),
        gender=as_str(data.get("gender")),
        birth_year=as_str(data.get("birth_year")),
        phone=as_str(data.get("phone")),
        email=as_str(data.get("email")),
        city=as_str(data.get("city")),
        job_intent=as_str(data.get("job_intent")),
        summary=as_str(data.get("summary")),
        education=sections["education"],
        experience=sections["experience"],
        campus_experience=sections["campus_experience"],
        projects=sections["projects"],
        skills=skills,
        awards=awards,
    )
