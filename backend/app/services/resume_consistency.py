"""生成简历与候选资料之间的一致性检查。"""

from __future__ import annotations

import json

from ..schemas.profile import ProfileOut
from ..schemas.resume import ResumeContent
from .profile_context import build_profile_prompt_data
from .resume_grounding import (
    _find_source,
    _similar,
    _similar_skill,
    _source_evidence_text,
    _unsupported_quantified_values,
)


def check_consistency(
    resume: ResumeContent,
    profile: ProfileOut,
    selected_data: dict | None = None,
    *,
    source_label: str | None = None,
) -> list[str]:
    """校验生成结果是否出现候选资料中不存在的信息（防 AI 虚构）。

    ``source_label`` 用于替换警告里的资料来源说法：通用简历没有岗位，说"本岗位候选资料"
    会让用户以为简历是针对某个岗位筛过的。
    """
    warnings: list[str] = []
    source_data = selected_data or build_profile_prompt_data(profile)
    label = source_label or ("本岗位候选资料" if selected_data is not None else "个人资料")
    known_schools = [item["school"] for item in source_data["educations"] if item.get("school")]
    known_companies = [item["company"] for item in source_data["experiences"] if item.get("company")]
    known_campus_organizations = [
        item["organization"]
        for item in source_data["campus_experiences"]
        if item.get("organization")
    ]
    known_projects = [item["name"] for item in source_data["projects"] if item.get("name")]
    known_skills = [item["name"] for item in source_data["skills"] if item.get("name")]
    known_awards = [item["name"] for item in source_data["awards"] if item.get("name")]

    for edu in resume.education:
        if edu.school and not any(_similar(edu.school, s) for s in known_schools):
            warnings.append(
                f"教育经历中出现{label}未包含的学校「{edu.school}」，请核对是否为虚构"
            )
    for exp in resume.experience:
        if exp.company and not any(_similar(exp.company, c) for c in known_companies):
            warnings.append(
                f"实习/工作经历中出现{label}未包含的公司「{exp.company}」，请核对是否为虚构"
            )
        source = _find_source(exp, source_data["experiences"], "company", "role")
        if source:
            unsupported = _unsupported_quantified_values(
                exp.description, _source_evidence_text(source, ("description",))
            )
            if unsupported:
                warnings.append(
                    f"实习/工作经历「{exp.company}」出现资料未提供的量化结果「{'、'.join(unsupported)}」"
                )
    for item in resume.campus_experience:
        if item.organization and not any(
            _similar(item.organization, organization)
            for organization in known_campus_organizations
        ):
            warnings.append(
                f"校园经历中出现{label}未包含的组织「{item.organization}」，请核对是否为虚构"
            )
        source = _find_source(item, source_data["campus_experiences"], "organization", "role")
        if source:
            unsupported = _unsupported_quantified_values(
                item.description, _source_evidence_text(source, ("description",))
            )
            if unsupported:
                warnings.append(
                    f"校园经历「{item.organization}」出现资料未提供的量化结果「{'、'.join(unsupported)}」"
                )
    for project in resume.projects:
        if project.name and not any(_similar(project.name, p) for p in known_projects):
            warnings.append(
                f"项目经历中出现{label}未包含的项目「{project.name}」，请核对是否为虚构"
            )
        source = _find_source(project, source_data["projects"], "name", "role")
        if source:
            source_text = _source_evidence_text(source, ("description", "highlights"))
            unsupported = _unsupported_quantified_values(
                project.description + project.highlights, source_text
            )
            if unsupported:
                warnings.append(
                    f"项目经历「{project.name}」出现资料未提供的量化结果「{'、'.join(unsupported)}」"
                )
    for skill in resume.skills:
        if skill.name and not any(_similar_skill(skill.name, known) for known in known_skills):
            warnings.append(
                f"专业技能中出现{label}未包含的技能「{skill.name}」，请核对是否为虚构"
            )
    for award in resume.awards:
        if award.name and not any(_similar(award.name, known) for known in known_awards):
            warnings.append(
                f"荣誉奖项中出现{label}未包含的奖项「{award.name}」，请核对是否为虚构"
            )
    unsupported_summary = _unsupported_quantified_values(
        resume.summary, json.dumps(source_data, ensure_ascii=False)
    )
    if unsupported_summary:
        warnings.append(
            f"个人总结出现资料未提供的量化结果「{'、'.join(unsupported_summary)}」"
        )
    return warnings


__all__ = ["check_consistency"]
