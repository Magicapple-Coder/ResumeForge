"""按目标岗位从个人资料中筛选候选事实。

个人资料是长期维护的"事实库"，而一份简历只应该携带与当前岗位相关的
一部分内容。本模块只做确定性的候选检索和预算控制，不改写资料，也不依赖
大模型，因此可以离线测试：模型收到的内容一定是资料库中已有的条目。
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from ..schemas.job import JobOut
from ..schemas.profile import ProfileOut
from .jd_parser import parse_jd

# 这些上限是"一份简历"的候选上限，不是资料库的存储上限。
SECTION_LIMITS = {
    "educations": 2,
    "experiences": 3,
    "campus_experiences": 2,
    "projects": 3,
    "skills": 14,
    "awards": 3,
}

SECTION_PRIMARY_FIELDS = {
    "educations": "school",
    "experiences": "company",
    "campus_experiences": "organization",
    "projects": "name",
    "skills": "name",
    "awards": "name",
}

# 岗位方向词只用于低权重的语义补充；硬技能仍然优先使用 JD 技能解析结果。
DOMAIN_SIGNALS: dict[str, tuple[str, ...]] = {
    "ai_algorithm": (
        "算法",
        "机器学习",
        "深度学习",
        "自然语言处理",
        "计算机视觉",
        "大模型",
        "LLM",
        "AIGC",
        "RAG",
        "AI Agent",
        "智能体",
        "推荐系统",
        "多模态",
        "模型训练",
        "推理",
    ),
    "backend": (
        "后端",
        "服务端",
        "微服务",
        "分布式",
        "高并发",
        "接口开发",
        "服务开发",
        "数据库",
        "系统设计",
    ),
    "frontend_client": (
        "前端",
        "客户端",
        "移动端",
        "桌面端",
        "Web 开发",
        "界面开发",
        "交互开发",
    ),
    "data": (
        "数据分析",
        "数据工程",
        "数据挖掘",
        "商业分析",
        "指标体系",
        "数据可视化",
    ),
    "product_operations": (
        "产品经理",
        "产品运营",
        "用户研究",
        "需求分析",
        "竞品分析",
        "活动策划",
        "内容运营",
        "增长运营",
        "用户增长",
    ),
    "testing": ("测试开发", "软件测试", "自动化测试", "质量保证", "测试工程师"),
}

# 这类词能强化已经识别出的方向，但过于宽泛，不能单独把 JD 归到某个方向。
DOMAIN_CONTEXT_SIGNALS: dict[str, tuple[str, ...]] = {
    "product_operations": ("活动", "内容", "推广", "公众号", "宣传", "协作"),
}

# 当 JD 没有明确写出某个技能，但岗位方向很明确时，用于给技能一个较小的
# 先验分数。这里只放常见类别，不会压过 JD 中的直接技能命中。
SKILL_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "ai_algorithm": (
        "Python",
        "PyTorch",
        "TensorFlow",
        "机器学习",
        "深度学习",
        "NLP",
        "LLM",
        "大模型",
        "Transformer",
        "RAG",
    ),
    "backend": (
        "Python",
        "Java",
        "Go",
        "C++",
        "FastAPI",
        "Django",
        "Spring Boot",
        "MySQL",
        "Redis",
        "Docker",
        "Linux",
    ),
    "frontend_client": (
        "JavaScript",
        "TypeScript",
        "React",
        "Vue",
        "Flutter",
        "Electron",
        "CSS3",
        "HTML5",
    ),
    "data": (
        "Python",
        "SQL",
        "MySQL",
        "Spark",
        "Flink",
        "数据分析",
        "数据挖掘",
    ),
    "product_operations": (
        "用户研究",
        "活动策划",
        "内容运营",
        "Excel",
        "Figma",
        "数据分析",
    ),
    "testing": ("Python", "Java", "Selenium", "自动化测试", "接口测试"),
}

_TITLE_SPLIT_RE = re.compile(r"[\s\-_/|,，、；;（）()：:]+")
_ASCII_TERM_RE = re.compile(r"[A-Za-z]")
_LIST_DETAIL_FIELDS = ("courses", "achievements", "description", "highlights")
_OPTIONAL_TOP_LEVEL_FIELDS = ("summary", "github", "personal_website", "target_city")
_LLM_PROFILE_FIELDS = (
    "target_city",
    "job_intent",
    "summary",
    "educations",
    "experiences",
    "campus_experiences",
    "projects",
    "skills",
    "awards",
)
_MIN_PROFILE_CONTEXT_CHARS = 1_000
_REFERENCE_SECTIONS = ("educations", "experiences", "campus_experiences", "projects")
_REFERENCE_CONTENT_KEY = "_reference_content"
_REFERENCE_FILE_KEY = "_reference_file_name"
_REFERENCE_EXCERPT_MAX_CHARS = 1_800
_REFERENCE_FACT_MAX_CHARS = 320
_REFERENCE_FACT_LIMIT = 5
_REFERENCE_INSTRUCTION_RE = re.compile(
    r"(?:忽略|绕过).{0,24}(?:系统|规则|指令|要求|限制)|"
    r"(?:系统|开发者|用户)\s*(?:消息|指令)|"
    r"(?:执行|遵循).{0,16}(?:以下|上述|本文).{0,8}(?:命令|指令)|"
    r"(?:虚构|编造).{0,24}(?:经历|成绩|成果|数据|数字)|"
    r"(?:请勿|不要|无需).{0,24}(?:虚构|编造|弱化|执行)",
    re.IGNORECASE,
)
_REFERENCE_META_RE = re.compile(
    r"用途说明|事实性总结|供后续|简历(?:包装|优化|措辞)|"
    r"面试(?:准备|要点)|可直接(?:提炼|引用|使用)|不是(?:系统|用户)指令",
    re.IGNORECASE,
)
_MARKDOWN_LIST_PREFIX_RE = re.compile(r"^(?:[-+*]\s+|\d+(?:[.)、]|、)\s*)")
_MARKDOWN_TABLE_DIVIDER_RE = re.compile(r"^:?-{3,}:?$")


@dataclass(frozen=True)
class JobFocus:
    """从岗位标题/JD 中提取的可解释匹配信号。"""

    skills: tuple[str, ...]
    domains: tuple[str, ...]
    terms: tuple[str, ...]


@dataclass(frozen=True)
class ProfileSelection:
    """候选资料及其诊断信息。``serialized`` 一定是完整合法 JSON。"""

    data: dict[str, Any]
    serialized: str
    focus: JobFocus
    selected_counts: dict[str, int]
    omitted_counts: dict[str, int]


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


def _safe_reference_blocks(content: str) -> list[str]:
    """切分参考文件并移除含明显提示注入的整个段落。"""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    return [
        block.replace("```", "").strip()
        for block in re.split(r"\n\s*\n+", normalized)
        if block.strip() and _REFERENCE_INSTRUCTION_RE.search(block) is None
    ]


def _strip_markdown(value: str) -> str:
    value = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", value).strip()


def _clean_reference_fact_line(line: str) -> str:
    """把 Markdown 行转换为可直接追溯的事实句，丢弃标题和元说明。"""
    stripped = line.strip()
    if (
        not stripped
        or stripped.startswith(("#", ">"))
        or re.fullmatch(r"[-*_]{3,}", stripped)
        or _REFERENCE_META_RE.search(stripped)
    ):
        return ""

    if stripped.startswith("|") and stripped.endswith("|"):
        cells = [_strip_markdown(cell) for cell in stripped.strip("|").split("|")]
        if not cells or all(_MARKDOWN_TABLE_DIVIDER_RE.fullmatch(cell) for cell in cells):
            return ""
        if cells[0] in {"层级", "技术", "指标", "数值", "项目", "说明"}:
            return ""
        stripped = f"{cells[0]}：{'、'.join(cell for cell in cells[1:] if cell)}"
    else:
        stripped = _MARKDOWN_LIST_PREFIX_RE.sub("", stripped)

    cleaned = _strip_markdown(stripped).strip(" -：:")
    if (
        len(cleaned) < 12
        or _REFERENCE_META_RE.search(cleaned)
        or _REFERENCE_INSTRUCTION_RE.search(cleaned)
    ):
        return ""
    return _trim_text(cleaned, _REFERENCE_FACT_MAX_CHARS)


def _reference_fact_candidates(content: str) -> list[str]:
    """从安全段落中提取自包含的事实行，保留原文而不做语义扩写。"""
    candidates: list[str] = []
    seen: set[str] = set()
    for block in _safe_reference_blocks(content):
        for line in block.splitlines():
            fact = _clean_reference_fact_line(line)
            normalized = re.sub(r"\s+", "", fact).casefold()
            if not fact or normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(fact)
    return candidates


def _select_reference_facts(content: str, section: str, focus: JobFocus) -> list[str]:
    """选取少量 JD 相关事实，供模型使用并作为空输出时的确定性回退。"""
    ranked: list[tuple[int, str, int, set[str]]] = []
    for index, fact in enumerate(_reference_fact_candidates(content)):
        score = _score_item({"reference_fact": fact}, section, focus)
        if score <= 0:
            continue
        matched_signals = {
            f"term:{term.casefold()}" for term in focus.terms if _contains(fact, term)
        }
        matched_signals.update(
            f"domain:{domain}"
            for domain in focus.domains
            if any(_contains(fact, signal) for signal in DOMAIN_SIGNALS[domain])
        )
        ranked.append((index, fact, score, matched_signals))

    selected: list[str] = []
    remaining = list(ranked)
    uncovered = {f"term:{term.casefold()}" for term in focus.terms}
    uncovered.update(f"domain:{domain}" for domain in focus.domains)
    while remaining and len(selected) < _REFERENCE_FACT_LIMIT:
        choice = max(
            remaining,
            key=lambda item: (len(item[3] & uncovered), item[2], -item[0]),
        )
        remaining.remove(choice)
        _, fact, _, matched_signals = choice
        selected.append(fact)
        uncovered -= matched_signals
    return selected


def _reference_chunks(content: str) -> list[str]:
    """按 Markdown 段落切分，并在进入 Prompt 前丢弃明显的指令注入。"""
    return [_trim_text(block, 700) for block in _safe_reference_blocks(content)]


def _select_reference_excerpt(content: str, section: str, focus: JobFocus) -> str:
    """选择直接命中 JD 的参考段落，并保持其在原文中的顺序。"""
    ranked = [
        (index, chunk, _score_item({"reference": chunk}, section, focus))
        for index, chunk in enumerate(_reference_chunks(content))
    ]
    matching = sorted(
        (item for item in ranked if item[2] > 0),
        key=lambda item: (-item[2], item[0]),
    )
    selected_indexes: set[int] = set()
    used_chars = 0
    for index, chunk, _ in matching:
        separator_size = 2 if selected_indexes else 0
        if selected_indexes and used_chars + separator_size + len(chunk) > _REFERENCE_EXCERPT_MAX_CHARS:
            continue
        selected_indexes.add(index)
        used_chars += separator_size + len(chunk)
        if used_chars >= _REFERENCE_EXCERPT_MAX_CHARS:
            break
    return "\n\n".join(
        chunk for index, chunk, _ in ranked if index in selected_indexes
    )


def _prepare_reference_excerpt(
    item: dict[str, Any], section: str, focus: JobFocus
) -> dict[str, Any]:
    """移除内部原文，只暴露可追溯的岗位相关节选与事实。"""
    result = deepcopy(item)
    content = str(result.pop(_REFERENCE_CONTENT_KEY, ""))
    file_name = str(result.pop(_REFERENCE_FILE_KEY, ""))
    excerpt = _select_reference_excerpt(content, section, focus)
    facts = _select_reference_facts(content, section, focus)
    if excerpt or facts:
        result["reference_file_name"] = file_name
    if excerpt:
        result["reference_excerpt"] = excerpt
    if facts:
        result["reference_facts"] = facts
    return result


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


def _dump(data: dict[str, Any]) -> str:
    # Prompt 不需要缩进；紧凑序列化可以为事实本身省出更多上下文空间。
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _trim_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    cut = value[:max_chars]
    if "\n" in cut:
        cut = cut.rsplit("\n", 1)[0]
    return f"{cut.rstrip()}…" if cut.rstrip() else ""


def _trim_middle(value: str, max_chars: int) -> str:
    """保留超长文本的开头和结尾，避免遗漏写在末尾的硬性要求。"""
    if len(value) <= max_chars:
        return value
    if max_chars < 8:
        return _trim_text(value, max_chars)
    head_size = max_chars * 2 // 3
    tail_size = max_chars - head_size - 1
    return f"{value[:head_size].rstrip()}…{value[-tail_size:].lstrip()}"


def build_job_prompt_text(job: JobOut, max_chars: int) -> str:
    """在固定预算中优先保留任职要求，再补充职位描述。

    JD 的团队介绍往往很长，而关键技能和硬性条件通常位于 requirements；
    不能把二者拼接后直接切片，否则职位要求可能完全消失。
    """
    requirements = job.requirements.strip()
    description = job.description.strip()
    additional_info = job.additional_info.strip()
    overhead = len("任职要求（优先）：\n\n\n职位描述：\n\n\n其他招聘信息：\n")
    available = max(0, max_chars - overhead)
    if not requirements:
        description_budget = available if not additional_info else available * 3 // 4
        description_text = _trim_middle(description, description_budget)
        additional_text = _trim_middle(
            additional_info, max(0, available - len(description_text))
        )
        result = f"职位描述：\n{description_text}"
        if additional_text:
            result += f"\n\n其他招聘信息：\n{additional_text}"
        return result

    requirement_budget = min(
        len(requirements),
        max(available * 3 // 5, min(available, 1_200)),
    )
    requirement_text = _trim_middle(requirements, requirement_budget)
    remaining = max(0, available - len(requirement_text))
    description_budget = remaining if not additional_info else remaining * 3 // 4
    description_text = _trim_middle(description, description_budget)
    additional_text = _trim_middle(
        additional_info, max(0, remaining - len(description_text))
    )
    result = f"任职要求（优先）：\n{requirement_text}\n\n职位描述：\n{description_text}"
    if additional_text:
        result += f"\n\n其他招聘信息：\n{additional_text}"
    return result


def _drop_one_detail(data: dict[str, Any]) -> bool:
    """从候选尾部逐条删减要点，优先保留排名靠前的事实。"""
    # 参考节选只用于美化，不应在预算不足时挤掉用户资料中的核心事实。
    for section in reversed(_REFERENCE_SECTIONS):
        for item in reversed(data.get(section) or []):
            excerpt = item.get("reference_excerpt")
            if not isinstance(excerpt, str) or not excerpt:
                continue
            if len(excerpt) > 360:
                item["reference_excerpt"] = _trim_text(excerpt, max(360, len(excerpt) // 2))
            else:
                item.pop("reference_excerpt", None)
                if not item.get("reference_facts"):
                    item.pop("reference_file_name", None)
            return True
    for section in reversed(_REFERENCE_SECTIONS):
        for item in reversed(data.get(section) or []):
            facts = item.get("reference_facts")
            if not isinstance(facts, list) or not facts:
                continue
            facts.pop()
            if not facts:
                item.pop("reference_facts", None)
                if not item.get("reference_excerpt"):
                    item.pop("reference_file_name", None)
            return True
    for section in ("awards", "campus_experiences", "experiences", "projects", "educations"):
        entries = data.get(section) or []
        for item in reversed(entries):
            for field in _LIST_DETAIL_FIELDS:
                values = item.get(field)
                if not isinstance(values, list) or not values:
                    continue
                if len(values) > 1:
                    values.pop()
                    return True
                if len(values[0]) > 240:
                    values[0] = _trim_text(values[0], 240)
                    return True
    return False


def _trim_all_strings(value: Any, max_chars: int) -> Any:
    """极端长输入的最后兜底；常规资料不会触发这一层。"""
    if isinstance(value, str):
        return _trim_text(value, max_chars)
    if isinstance(value, list):
        return [_trim_all_strings(item, max_chars) for item in value]
    if isinstance(value, dict):
        return {key: _trim_all_strings(item, max_chars) for key, item in value.items()}
    return value


def serialize_profile_prompt_data(data: dict[str, Any], max_chars: int) -> str:
    """在字段/要点边界上压缩资料，返回不超过预算的合法 JSON。

    不能对最终 JSON 做字符切片，否则多条经历靠后时会得到半个 JSON 或直接
    丢掉技能区。压缩只作用于传给模型的副本，原始资料不受影响。
    """
    if max_chars < _MIN_PROFILE_CONTEXT_CHARS:
        raise ValueError(f"资料上下文预算不能小于 {_MIN_PROFILE_CONTEXT_CHARS} 个字符")

    candidate = deepcopy(data)
    serialized = _dump(candidate)
    if len(serialized) <= max_chars:
        return serialized

    # 先去掉候选条目中排名靠后的细节，再缩短超长的自由文本。
    while len(serialized) > max_chars and _drop_one_detail(candidate):
        serialized = _dump(candidate)

    for field in _OPTIONAL_TOP_LEVEL_FIELDS:
        if len(serialized) <= max_chars:
            break
        value = candidate.get(field)
        if isinstance(value, str) and value:
            candidate[field] = _trim_text(value, 400)
            serialized = _dump(candidate)

    # 极端情况下单个字段本身就很长，逐级收紧每个自由文本字段；字段名、
    # 组织/项目名和日期不主动删除，避免模型失去事实锚点。
    for limit in (800, 400, 200):
        if len(serialized) <= max_chars:
            break
        for section in ("educations", "experiences", "campus_experiences", "projects", "awards"):
            for item in candidate.get(section, []):
                for field in _LIST_DETAIL_FIELDS:
                    values = item.get(field)
                    if isinstance(values, list):
                        item[field] = [_trim_text(value, limit) for value in values if value]
        serialized = _dump(candidate)

    # 受数据库字段长度限制，正常资料不会走到这里；这个兜底仍然保持 JSON
    # 完整，宁可省略可选总结，也不让请求携带非法半截数据。
    if len(serialized) > max_chars:
        candidate["summary"] = ""
        candidate["github"] = ""
        candidate["personal_website"] = ""
        candidate["target_city"] = ""
        serialized = _dump(candidate)
    if len(serialized) > max_chars:
        # 最后按条目从低优先级尾部删除，至少保留每个非空区块的首条事实。
        for section in ("awards", "campus_experiences", "experiences", "projects", "educations"):
            entries = candidate.get(section) or []
            while len(serialized) > max_chars and len(entries) > 1:
                entries.pop()
                serialized = _dump(candidate)
    if len(serialized) > max_chars:
        for limit in (128, 64, 32, 16):
            candidate = _trim_all_strings(candidate, limit)
            serialized = _dump(candidate)
            if len(serialized) <= max_chars:
                break
    if len(serialized) > max_chars:
        # 极端输入只保留岗位意图和各区块首条；身份与联系方式不属于模型上下文。
        candidate = {
            "target_city": "",
            "job_intent": _trim_text(str(candidate.get("job_intent", "")), 64),
            "summary": "",
            **{
                section: (candidate.get(section) or [])[:1]
                for section in SECTION_LIMITS
            },
        }
        candidate = _trim_all_strings(candidate, 32)
        serialized = _dump(candidate)
    if len(serialized) > max_chars:
        raise ValueError("个人资料基础字段过长，无法在安全预算内生成简历")
    return serialized


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
    selected_counts = {section: len(selected[section]) for section in SECTION_LIMITS}
    omitted_counts = {
        section: max(0, len(full[section]) - selected_counts[section]) for section in SECTION_LIMITS
    }
    serialized = serialize_profile_prompt_data(selected, max_chars)
    # ``serialize_profile_prompt_data`` 会在副本上做预算压缩；对外暴露的
    # data 必须与实际发送给模型的 JSON 完全一致，避免诊断和生成出现偏差。
    packed_data = json.loads(serialized)
    selected_counts = {section: len(packed_data[section]) for section in SECTION_LIMITS}
    omitted_counts = {
        section: max(0, len(full[section]) - selected_counts[section]) for section in SECTION_LIMITS
    }
    return ProfileSelection(
        data=packed_data,
        serialized=serialized,
        focus=focus,
        selected_counts=selected_counts,
        omitted_counts=omitted_counts,
    )


def build_targeted_profile_prompt_data(
    profile: ProfileOut, job: JobOut, *, include_references: bool = False
) -> dict[str, Any]:
    """公开的纯函数入口，便于测试岗位不同导致的候选资料差异。"""
    return build_targeted_profile_context(
        profile, job, include_references=include_references
    ).data
