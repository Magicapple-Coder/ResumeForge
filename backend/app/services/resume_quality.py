"""带参考文件的简历生成质量门槛。"""

from ..schemas.job import JobOut
from ..schemas.resume import ResumeContent
from .resume_grounding import (
    _build_grounded_summary,
    _find_source,
    _normalize_fact,
    _source_list,
    _source_value,
)


def _quality_reference_points(source: dict) -> list[str]:
    """读取条目中的附件事实，去掉空值并保持原顺序。"""
    return [
        value.strip()
        for value in _source_list(source, "reference_facts")
        if isinstance(value, str) and value.strip()
    ]


def _quality_generated_points(item, fields: tuple[str, ...]) -> list[str]:
    """合并模型输出的描述性字段，供质量门槛做确定性检查。"""
    points: list[str] = []
    for field in fields:
        values = getattr(item, field, [])
        if isinstance(values, list):
            points.extend(
                value.strip()
                for value in values
                if isinstance(value, str) and value.strip()
            )
    return points


def _quality_shortfalls(
    resume: ResumeContent,
    selected_data: dict,
    job: JobOut | None = None,
) -> list[str]:
    """找出附件事实没有被充分改写的项目内容。"""
    shortfalls: list[str] = []
    generated_projects = resume.projects
    reference_projects = [
        source
        for source in selected_data.get("projects", [])
        if _quality_reference_points(source)
    ]

    for source in reference_projects:
        source_name = _source_value(source, "name") or "未命名项目"
        generated = next(
            (
                item
                for item in generated_projects
                if _find_source(item, [source], "name", "role") is not None
            ),
            None,
        )
        if generated is None:
            shortfalls.append(f"项目「{source_name}」未出现在输出中")
            continue

        points = _quality_generated_points(generated, ("description", "highlights"))
        unique_points = {_normalize_fact(point) for point in points if _normalize_fact(point)}
        reference_facts = _quality_reference_points(source)
        required = min(3, len(reference_facts))
        if len(unique_points) < required:
            shortfalls.append(
                f"项目「{source_name}」只有 {len(unique_points)} 条有效要点，至少需要 {required} 条"
            )
        if len(reference_facts) >= 3 and (not generated.description or not generated.highlights):
            shortfalls.append(f"项目「{source_name}」没有合理分配项目描述与成果亮点")

        source_has_original_details = bool(
            _source_list(source, "description") or _source_list(source, "highlights")
        )
        normalized_references = {
            _normalize_fact(fact) for fact in reference_facts if _normalize_fact(fact)
        }
        if (
            not source_has_original_details
            and points
            and normalized_references
            and all(_normalize_fact(point) in normalized_references for point in points)
        ):
            shortfalls.append(f"项目「{source_name}」的要点仍是附件原文，尚未完成岗位化改写")

    if reference_projects and shortfalls:
        grounded_summary = _build_grounded_summary(selected_data, job) if job else ""
        if not resume.summary.strip():
            shortfalls.append("个人总结为空，未概括与目标岗位相关的能力")
        elif grounded_summary and resume.summary.strip() == grounded_summary.strip():
            shortfalls.append("个人总结只是系统兜底文本，未体现岗位化表达")
    return shortfalls


quality_shortfalls = _quality_shortfalls

__all__ = ["_quality_shortfalls", "quality_shortfalls", "_quality_reference_points", "_quality_generated_points"]
