"""简历生成核心流程。

职责：拼装 Prompt -> 调用 LLM（流式）-> 解析/校验 JSON -> 一致性检查。
对外只产出异步事件流（dict），由 API 层负责转发为 SSE 与落库，
本模块不直接接触数据库，保持可单测。
"""
import json
import logging
import re
from collections.abc import AsyncIterator
from copy import deepcopy
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..schemas.job import JobOut
from ..schemas.profile import ProfileOut
from ..schemas.resume import GenerateOptions, ResumeContent
from .llm.base import BaseLLMProvider, LLMError
from .profile_relevance import (
    build_job_prompt_text,
    build_profile_prompt_data,
    build_targeted_profile_context,
    split_commas as _split_commas,
    split_lines,
)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

logger = logging.getLogger(__name__)

# Keep the historical import path used by integrations and tests while making
# the dependency usage explicit to Ruff and future maintainers.
split_commas = _split_commas

# 控制总输入体积：先筛选资料，再为 JD 保留独立预算，避免超长资料/JD 挤掉彼此。
MAX_JD_CHARS = 5_000
MAX_PROFILE_CHARS = 9_000

# 三档只控制对描述性字段的改写幅度；结构化事实始终由代码强制锚定。
ENHANCEMENT_LEVEL_GUIDES = {
    "light": (
        "轻度美化：只优化语序、动词和专业表达，保持原有要点数量与职责边界；"
        "每条内容应能直接对应原资料或参考事实。原描述为空但存在 reference_facts 时，"
        "提炼 1-2 条最相关事实，不能继续留空。"
    ),
    "balanced": (
        "均衡美化：可围绕 JD 重组原有事实，补足动作、方法和业务目的，使表达更扎实；"
        "允许合并同一条目内的相关证据，但不得推导未明确提供的结果。含 reference_facts "
        "的相关条目在可用事实达到 2 条时，应将 description/highlights 合计写成 2-4 条。"
    ),
    "strong": (
        "深度美化：充分挖掘同一条目及 reference_facts/reference_excerpt 中的岗位相关证据，"
        "以专业简历语言展开技术决策、实施过程和价值，可以增加描述要点。存在至少 3 条 "
        "reference_facts 时，"
        "必须将 description/highlights 合计写成 3-5 条；不足 3 条时全部使用，不得为凑数"
        "虚构。每个事实都必须能追溯到该条目来源。"
    ),
}

_REFERENCE_FALLBACK_LIMITS = {"light": 2, "balanced": 3, "strong": 5}

_ENHANCEMENT_DISABLED_GUIDE = (
    "美化拓展已关闭：只能选择、排序并精确回填候选资料中的原文要点；"
    "不得合并、改写或扩充 description、highlights 和 summary。"
)

# 简历结构中的"列表字段"，宽松校验时字符串会被拆分补全
_LIST_FIELDS = {
    "education": {"str_fields": {"school", "major", "degree", "start_date", "end_date", "gpa"},
                  "list_fields": {"courses", "achievements"}},
    "experience": {"str_fields": {"company", "role", "start_date", "end_date"},
                   "list_fields": {"description"}},
    "campus_experience": {"str_fields": {"organization", "role", "start_date", "end_date"},
                           "list_fields": {"description"}},
    "projects": {"str_fields": {"name", "role", "start_date", "end_date"},
                 "list_fields": {"tech_stack", "description", "highlights"}},
}


def extract_json(text: str) -> dict | None:
    """从模型输出中提取 JSON 对象。

    容忍：Markdown 代码块包裹、前后杂文本、外层 {"resume": {...}} 包装。
    """
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
    # 部分模型会额外套一层 "resume" 包装
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
        item = {field: entry.get(field) if isinstance(entry.get(field), str) else "" for field in str_fields}
        for field in list_fields:
            item[field] = _string_list(entry.get(field))
        result.append(item)
    return result


def coerce_resume(data: dict | None) -> ResumeContent:
    """宽松校验：字段缺失补默认值、类型不对尽量修正，保证格式问题永不导致崩溃。"""
    data = data or {}

    def as_str(value) -> str:
        return value if isinstance(value, str) else ""

    sections = {}
    for section, config in _LIST_FIELDS.items():
        sections[section] = _item_list(data.get(section), config["str_fields"], config["list_fields"])
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


def _similar(a: str, b: str) -> bool:
    """双向包含判断，容忍模型对名称的轻度改写（如「XX大学（双一流）」）。"""
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
        source
        for source in sources
        if _similar(name, _source_value(source, name_field))
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
    """把模型选中的要点映射回同一来源的原始事实。

    只接受完整原文或其明确的子片段，并始终输出原始要点。这样模型可以选择
    要点，却无法借由「Python」扩写成「Python、Kubernetes」等混合事实。
    """
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
    """找出候选事实中没有出现过的量化结果。

    对描述的语义改写无法做完全自动的真伪判断，但具体数字、比例和次数最容易
    被模型凭空补出，也最容易造成求职风险，因此单独做确定性保护。
    """
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
    """优先保留模型明确选择的事实；无法验证时回填来源，避免空白或虚构。"""
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


def _build_grounded_summary(selected_data: dict, job: JobOut) -> str:
    """用已选事实生成不依赖模型自由发挥的岗位摘要。"""
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
    if evidence:
        sentences.append(f"面向{job.title}，具备{'、'.join(evidence)}等相关经历。")
    else:
        sentences.append(f"面向{job.title}求职。")
    if skills:
        sentences.append(f"已掌握{'、'.join(skills)}等与岗位匹配的技能。")
    return "".join(sentences)


def _reference_fallback_facts(source: dict, enhancement_level: str) -> list[str]:
    """返回已清洗且实际进入候选上下文的附件事实，不重新读取附件原文。"""
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


def restore_selected_sections(
    resume: ResumeContent,
    selected_data: dict,
    *,
    enhance: bool = False,
    enhancement_level: str = "balanced",
) -> ResumeContent:
    """回填模型错误遗漏的岗位候选区块。

    模型偶尔会在 JSON 格式正确的情况下把经历、项目或技能数组全部留空。
    候选资料已经是按岗位筛选后的真实事实。关闭美化时只回填原始字段；开启
    美化时，原字段为空的条目可回填已清洗并实际进入上下文的附件事实。
    """
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
    job: JobOut,
    selected_data: dict | None = None,
    *,
    enhance: bool = False,
    enhancement_level: str = "balanced",
) -> ResumeContent:
    """把模型结果中的可验证字段锚定回资料库。

    名称、角色、日期、技能和技术栈始终回填为候选资料的原始事实。美化关闭
    时描述也精确回填；开启时 description/highlights/summary 可基于同条目的
    录入事实、参考事实和节选改写，但无来源的量化结果会被过滤。找不到候选源的条目
    会被丢弃，对应提醒由生成前的 ``check_consistency`` 保留给用户。
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
            "job_intent": job.title or profile.job_intent,
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
        source = _find_source(item, source_data.get("campus_experiences", []), "organization", "role")
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


def check_consistency(
    resume: ResumeContent, profile: ProfileOut, selected_data: dict | None = None
) -> list[str]:
    """校验生成结果是否出现候选资料中不存在的信息（防 AI 虚构）。

    仅当资料中已有对应条目时才比对；空值条目不参与检查。
    """
    warnings: list[str] = []
    source_data = selected_data or build_profile_prompt_data(profile)
    source_label = "本岗位候选资料" if selected_data is not None else "个人资料"
    known_schools = [item["school"] for item in source_data["educations"] if item.get("school")]
    known_companies = [item["company"] for item in source_data["experiences"] if item.get("company")]
    known_campus_organizations = [
        item["organization"] for item in source_data["campus_experiences"] if item.get("organization")
    ]
    known_projects = [item["name"] for item in source_data["projects"] if item.get("name")]
    known_skills = [item["name"] for item in source_data["skills"] if item.get("name")]
    known_awards = [item["name"] for item in source_data["awards"] if item.get("name")]

    for edu in resume.education:
        if edu.school and not any(_similar(edu.school, s) for s in known_schools):
            warnings.append(f"教育经历中出现{source_label}未包含的学校「{edu.school}」，请核对是否为虚构")
    for exp in resume.experience:
        if exp.company and not any(_similar(exp.company, c) for c in known_companies):
            warnings.append(f"实习/工作经历中出现{source_label}未包含的公司「{exp.company}」，请核对是否为虚构")
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
            _similar(item.organization, organization) for organization in known_campus_organizations
        ):
            warnings.append(f"校园经历中出现{source_label}未包含的组织「{item.organization}」，请核对是否为虚构")
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
            warnings.append(f"项目经历中出现{source_label}未包含的项目「{project.name}」，请核对是否为虚构")
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
            warnings.append(f"专业技能中出现{source_label}未包含的技能「{skill.name}」，请核对是否为虚构")
    for award in resume.awards:
        if award.name and not any(_similar(award.name, known) for known in known_awards):
            warnings.append(f"荣誉奖项中出现{source_label}未包含的奖项「{award.name}」，请核对是否为虚构")
    unsupported_summary = _unsupported_quantified_values(
        resume.summary, json.dumps(source_data, ensure_ascii=False)
    )
    if unsupported_summary:
        warnings.append(f"个人总结出现资料未提供的量化结果「{'、'.join(unsupported_summary)}」")
    return warnings


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
    """找出附件事实没有被充分改写的项目内容。

    该检查必须发生在 ``ground_resume_facts``/``restore_selected_sections`` 之前：
    这些函数会把附件原文确定性回填，回填后再检查会把「模型只原样复制事实」误判为
    合格。这里只检查项目，避免强制重试不含项目附件的普通简历。
    """
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
                f"项目「{source_name}」只有 {len(unique_points)} 条有效要点，"
                f"至少需要 {required} 条"
            )
        if len(reference_facts) >= 3 and (not generated.description or not generated.highlights):
            shortfalls.append(
                f"项目「{source_name}」没有合理分配项目描述与成果亮点"
            )

        # 原项目没有可供改写的描述时，模型若把附件逐条原样抄回，内容虽然数量达标，
        # 仍然没有完成用户选择的「美化拓展」，应给它一次机会重新组织表达。
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

    # 摘要短板只在项目本身已经触发重试时附带提示；避免一个合法的详细项目
    # 因模型省略摘要而额外消耗一次请求。
    if reference_projects and shortfalls:
        grounded_summary = _build_grounded_summary(selected_data, job) if job else ""
        if not resume.summary.strip():
            shortfalls.append("个人总结为空，未概括与目标岗位相关的能力")
        elif grounded_summary and resume.summary.strip() == grounded_summary.strip():
            shortfalls.append("个人总结只是系统兜底文本，未体现岗位化表达")
    return shortfalls


class ResumeGenerator:
    """简历生成器：一次生成 = 一条事件流。"""

    def __init__(self, provider: BaseLLMProvider):
        self.provider = provider
        # StrictUndefined：模板变量缺失时立即报错，而不是静默渲染成空
        self._env = Environment(
            loader=FileSystemLoader(PROMPTS_DIR),
            undefined=StrictUndefined,
            autoescape=False,  # Prompt 是纯文本，无需转义
        )

    async def generate(
        self, profile: ProfileOut, job: JobOut, options: GenerateOptions
    ) -> AsyncIterator[dict]:
        """执行生成流程，依次产出事件。

        事件类型：
        - progress: {"type", "message"}   阶段提示
        - delta:    {"type", "text"}      模型流式输出片段
        - done:     {"type", "resume", "warnings"}  解析成功
        - error:    {"type", "message"}   失败（友好提示，由 API 层直接转发）
        """
        enhancement_guide = (
            ENHANCEMENT_LEVEL_GUIDES[options.enhancement_level]
            if options.enhance
            else _ENHANCEMENT_DISABLED_GUIDE
        )

        yield {"type": "progress", "message": "正在分析岗位要求与资料匹配度…"}
        selection = build_targeted_profile_context(
            profile,
            job,
            max_chars=MAX_PROFILE_CHARS,
            include_references=options.enhance,
        )
        counts = selection.selected_counts
        reference_count = sum(
            1
            for section in ("educations", "experiences", "campus_experiences", "projects")
            for item in selection.data.get(section, [])
            if item.get("reference_facts") or item.get("reference_excerpt")
        )
        reference_message = (
            f"；已提取 {reference_count} 份总结文件中的岗位相关事实"
            if options.enhance and reference_count
            else ""
        )
        yield {
            "type": "progress",
            "message": (
                "已从完整资料中筛选 "
                f"{counts['experiences']} 段实习/工作、{counts['projects']} 个项目、"
                f"{counts['campus_experiences']} 段校园经历和 {counts['skills']} 项技能"
                f"{reference_message}"
            ),
        }
        system_prompt = self._load_prompt("resume_generate_system.md")
        user_prompt = self._env.get_template("resume_generate_user.md").render(
            profile_json=selection.serialized,
            job=job,
            jd=build_job_prompt_text(job, MAX_JD_CHARS),
            enhancement_guide=enhancement_guide,
            enhancement_enabled=options.enhance,
            focus_skills="、".join(selection.focus.skills) or "未识别到明确技能，请以 JD 原文为准",
            focus_domains="、".join(selection.focus.domains) or "通用岗位",
            omitted_count=sum(selection.omitted_counts.values()),
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        yield {"type": "progress", "message": f"正在调用模型 {self.provider.config.model} 生成简历…"}
        parts: list[str] = []
        async for delta in self.provider.stream_chat(messages):
            parts.append(delta)
            yield {"type": "delta", "text": delta}

        raw = "".join(parts)
        resume = self._parse(raw)

        # 输出不是合法 JSON：用修复 Prompt 重试一次，仍然失败则降级报错
        if resume is None:
            yield {"type": "progress", "message": "输出格式不符合要求，正在自动修复…"}
            fix_prompt = self._env.get_template("resume_fix_json.md").render(raw=raw[:6000])
            try:
                fixed = await self.provider.chat([{"role": "user", "content": fix_prompt}])
            except LLMError as exc:
                yield {"type": "error", "message": f"自动修复调用失败：{exc}"}
                return
            resume = self._parse(fixed)

        if resume is None:
            yield {"type": "error", "message": "模型输出未能解析为有效 JSON，请更换模型或重试"}
            return

        # strong 美化且带附件事实时，先检查模型是否真正完成了岗位化改写。
        # 必须在 grounding/restore 前检查，否则确定性回填会掩盖模型输出过于简略的问题。
        has_reference_facts = any(
            _source_list(item, "reference_facts")
            for section in ("educations", "experiences", "campus_experiences", "projects")
            for item in selection.data.get(section, [])
        )
        quality_enabled = (
            options.enhance
            and options.enhancement_level == "strong"
            and has_reference_facts
        )
        quality_shortfalls = (
            _quality_shortfalls(resume, selection.data, job) if quality_enabled else []
        )
        if quality_shortfalls:
            yield {"type": "progress", "message": "生成内容较简略，正在重新生成…"}
            reference_facts = [
                {
                    "name": _source_value(source, "name"),
                    "facts": _quality_reference_points(source),
                }
                for source in selection.data.get("projects", [])
                if _quality_reference_points(source)
            ]
            retry_prompt = self._env.get_template("resume_quality_retry.md").render(
                shortfalls="\n".join(f"- {item}" for item in quality_shortfalls),
                reference_facts=json.dumps(reference_facts, ensure_ascii=False),
            )
            retry_messages = [*messages, {"role": "user", "content": retry_prompt}]
            retry_resume: ResumeContent | None = None
            try:
                retry_raw = await self.provider.chat(retry_messages)
                retry_resume = self._parse(retry_raw)
            except Exception as exc:  # noqa: BLE001 - 质量重试失败应保留首轮结果
                logger.warning("简历质量重试失败，将沿用首轮结果：%s", exc)

            # 只有重试结果通过同一门槛才替换首轮结果；仍然稀疏时继续走现有
            # grounding/fallback，确保用户至少拿到一份可用且有事实锚定的简历。
            if retry_resume is not None and not _quality_shortfalls(
                retry_resume, selection.data, job
            ):
                resume = retry_resume

        # 先基于原始模型输出记录越界提醒，再过滤/回填本岗位候选事实。
        warnings = check_consistency(resume, profile, selection.data)
        resume = ground_resume_facts(
            resume,
            profile,
            job,
            selection.data,
            enhance=options.enhance,
            enhancement_level=options.enhancement_level,
        ).model_copy(
            update={"photo": profile.photo}
        )
        resume = restore_selected_sections(
            resume,
            selection.data,
            enhance=options.enhance,
            enhancement_level=options.enhancement_level,
        )
        yield {"type": "done", "resume": resume.model_dump(), "warnings": warnings}

    def _parse(self, raw: str) -> ResumeContent | None:
        data = extract_json(raw)
        return coerce_resume(data) if data is not None else None

    def _load_prompt(self, filename: str) -> str:
        """从 prompts/ 目录加载模板文件（模板集中管理，方便调参）。"""
        return (PROMPTS_DIR / filename).read_text(encoding="utf-8")
