"""把模型简历结果锚定回用户资料中的可验证事实。"""

from __future__ import annotations

import json

from ...schemas.job import JobOut
from ...schemas.profile import ProfileOut
from ...schemas.resume import ResumeContent
from . import resume_grounding_helpers as _grounding_helpers
from ..profile.profile_context import build_profile_prompt_data
from .resume_content import coerce_resume
from .resume_grounding_helpers import (
    _build_grounded_summary,
    _enhance_or_restore_list,
    _find_source,
    _ground_list,
    _ground_or_restore_list,
    _normalize_fact,
    _reference_fallback_facts,
    _selected_data_with_reference_fallbacks,
    _similar,
    _similar_skill,
    _source_evidence_text,
    _source_list,
    _source_value,
    _unsupported_quantified_values,
)

# Keep the historical private symbol importable while the implementation lives
# in the dedicated helper module.
_REFERENCE_FALLBACK_LIMITS = _grounding_helpers._REFERENCE_FALLBACK_LIMITS

def restore_selected_sections(
    resume: ResumeContent,
    selected_data: dict,
    *,
    enhance: bool = False,
    enhancement_level: str = "balanced",
) -> ResumeContent:
    """回填模型错误遗漏的岗位候选区块。"""
    fallback_source = (
        _selected_data_with_reference_fallbacks(selected_data, enhancement_level)
        if enhance
        else selected_data
    )
    fallback = coerce_resume(
        {
            "education": fallback_source.get("educations", []),
            "experience": fallback_source.get("experiences", []),
            "campus_experience": fallback_source.get("campus_experiences", []),
            "projects": fallback_source.get("projects", []),
            "skills": fallback_source.get("skills", []),
            "awards": fallback_source.get("awards", []),
        }
    )
    sections = {
        "education": "educations",
        "experience": "experiences",
        "campus_experience": "campus_experiences",
        "projects": "projects",
        "skills": "skills",
        "awards": "awards",
    }
    updates = {
        output_field: getattr(fallback, output_field)
        for output_field, source_field in sections.items()
        if selected_data.get(source_field) and not getattr(resume, output_field)
    }
    return resume.model_copy(update=updates) if updates else resume


def ground_resume_facts(
    resume: ResumeContent,
    profile: ProfileOut,
    job: JobOut | None,
    selected_data: dict | None = None,
    *,
    enhance: bool = False,
    enhancement_level: str = "balanced",
) -> ResumeContent:
    """把模型结果中的可验证字段锚定回资料库。

    ``job is None`` 表示通用简历：求职意向沿用资料里用户自己写的那份。
    """
    source_data = selected_data or build_profile_prompt_data(profile)
    result = resume.model_copy(
        update={
            "name": profile.name,
            "gender": profile.gender,
            "birth_year": profile.birth_year,
            "phone": profile.phone,
            "email": profile.email,
            "city": profile.city,
            "job_intent": (job.title if job else "") or profile.job_intent,
        }
    )
    grounded_summary = _build_grounded_summary(source_data, job)
    summary_evidence = json.dumps(source_data, ensure_ascii=False)
    summary = resume.summary.strip() if enhance else ""
    if not summary or _unsupported_quantified_values(summary, summary_evidence):
        summary = grounded_summary
    result = result.model_copy(update={"summary": summary})

    education_items = []
    for item in result.education:
        source = _find_source(item, source_data.get("educations", []), "school", "major")
        if source is None:
            continue
        source_achievements = _source_list(source, "achievements")
        achievements = (
            _enhance_or_restore_list(
                item.achievements,
                source_achievements,
                _source_evidence_text(source, ("achievements",)),
            )
            if enhance
            else _ground_or_restore_list(item.achievements, source_achievements)
        )
        if enhance and not achievements:
            achievements = _reference_fallback_facts(source, enhancement_level)
        education_items.append(
            item.model_copy(
                update={
                    "school": _source_value(source, "school"),
                    "major": _source_value(source, "major"),
                    "degree": _source_value(source, "degree"),
                    "start_date": _source_value(source, "start_date"),
                    "end_date": _source_value(source, "end_date"),
                    "gpa": _source_value(source, "gpa"),
                    "courses": _ground_or_restore_list(item.courses, _source_list(source, "courses")),
                    "achievements": achievements,
                }
            )
        )
    result = result.model_copy(update={"education": education_items})

    experience_items = []
    for item in result.experience:
        source = _find_source(item, source_data.get("experiences", []), "company", "role")
        if source is None:
            continue
        source_description = _source_list(source, "description")
        description = (
            _enhance_or_restore_list(
                item.description,
                source_description,
                _source_evidence_text(source, ("description",)),
            )
            if enhance
            else _ground_or_restore_list(item.description, source_description)
        )
        if enhance and not description:
            description = _reference_fallback_facts(source, enhancement_level)
        experience_items.append(
            item.model_copy(
                update={
                    "company": _source_value(source, "company"),
                    "role": _source_value(source, "role"),
                    "start_date": _source_value(source, "start_date"),
                    "end_date": _source_value(source, "end_date"),
                    "description": description,
                }
            )
        )
    result = result.model_copy(update={"experience": experience_items})

    campus_items = []
    for item in result.campus_experience:
        source = _find_source(
            item, source_data.get("campus_experiences", []), "organization", "role"
        )
        if source is None:
            continue
        source_description = _source_list(source, "description")
        description = (
            _enhance_or_restore_list(
                item.description,
                source_description,
                _source_evidence_text(source, ("description",)),
            )
            if enhance
            else _ground_or_restore_list(item.description, source_description)
        )
        if enhance and not description:
            description = _reference_fallback_facts(source, enhancement_level)
        campus_items.append(
            item.model_copy(
                update={
                    "organization": _source_value(source, "organization"),
                    "role": _source_value(source, "role"),
                    "start_date": _source_value(source, "start_date"),
                    "end_date": _source_value(source, "end_date"),
                    "description": description,
                }
            )
        )
    result = result.model_copy(update={"campus_experience": campus_items})

    project_items = []
    for item in result.projects:
        source = _find_source(item, source_data.get("projects", []), "name", "role")
        if source is None:
            continue
        source_description = _source_list(source, "description")
        source_highlights = _source_list(source, "highlights")
        source_evidence = _source_evidence_text(source, ("description", "highlights"))
        description = (
            _enhance_or_restore_list(item.description, source_description, source_evidence)
            if enhance
            else _ground_or_restore_list(item.description, source_description)
        )
        highlights = (
            _enhance_or_restore_list(item.highlights, source_highlights, source_evidence)
            if enhance
            else _ground_or_restore_list(item.highlights, source_highlights)
        )
        if enhance and not description and not highlights:
            description = _reference_fallback_facts(source, enhancement_level)
        project_items.append(
            item.model_copy(
                update={
                    "name": _source_value(source, "name"),
                    "role": _source_value(source, "role"),
                    "start_date": _source_value(source, "start_date"),
                    "end_date": _source_value(source, "end_date"),
                    "tech_stack": _ground_or_restore_list(
                        item.tech_stack, _source_list(source, "tech_stack")
                    ),
                    "description": description,
                    "highlights": highlights,
                }
            )
        )
    result = result.model_copy(update={"projects": project_items})

    skill_items = []
    for item in result.skills:
        source = next(
            (
                skill
                for skill in source_data.get("skills", [])
                if _similar_skill(item.name, _source_value(skill, "name"))
            ),
            None,
        )
        if source is None:
            continue
        skill_items.append(
            item.model_copy(
                update={
                    "name": _source_value(source, "name"),
                    "level": _source_value(source, "level"),
                }
            )
        )
    result = result.model_copy(update={"skills": skill_items})

    award_items = []
    for item in result.awards:
        source = _find_source(item, source_data.get("awards", []), "name")
        if source is None:
            continue
        award_items.append(
            item.model_copy(
                update={
                    "name": _source_value(source, "name"),
                    "date": _source_value(source, "date"),
                    "description": _source_value(source, "description"),
                }
            )
        )
    return result.model_copy(update={"awards": award_items})


__all__ = [
    "restore_selected_sections",
    "ground_resume_facts",
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
