"""无标题资料的基础信号识别。"""

import re

from .entry_constants import _DATE_RANGE_RE, _PROFILE_ENGLISH_TITLE_RE
from .normalization import _clean_line, _starts_with_field


def _is_project_detail_line(line: str) -> bool:
    """“技术栈：...”是项目字段，不应在项目块中误切为技能分区。"""
    return bool(
        re.match(
            r"^(?:技术栈|技术能力|技术方案|开发工具|使用工具|"
            r"tech\s+stack|technical\s+stack|technologies|technology|tech\s+skills|"
            r"development\s+tools|tools)\s*[:：]",
            line,
            re.IGNORECASE,
        )
    )


def _infer_section_for_unlabeled_line(line: str) -> str | None:
    """从没有分区标题的复制文本中识别强信号字段。"""
    clean = _clean_line(line)
    if not clean:
        return None

    if _starts_with_field(
        clean,
        (
            "项目",
            "项目名称",
            "项目标题",
            "项目描述",
            "项目内容",
            "项目成果",
            "亮点",
            "技术栈",
            "tech stack",
            "technologies",
            "project",
            "project name",
            "project description",
            "highlights",
        ),
    ):
        return "projects"
    if _starts_with_field(
        clean,
        (
            "学校",
            "院校",
            "学校名称",
            "专业",
            "所学专业",
            "学历",
            "学位",
            "毕业院校",
            "毕业学校",
            "graduated from",
            "核心课程",
            "school",
            "university",
            "college",
            "major",
            "degree",
            "courses",
            "study period",
            "study dates",
            "time",
            "period",
        ),
    ):
        return "educations"
    if _starts_with_field(
        clean,
        (
            "组织",
            "组织名称",
            "社团",
            "社团名称",
            "学生组织",
            "校园组织",
            "所在组织",
            "团委",
            "团支部",
            "学生会",
            "organization",
            "organization name",
            "student organization",
            "student union",
            "club",
        ),
    ):
        return "campus_experiences"
    if _starts_with_field(
        clean,
        (
            "公司",
            "公司名称",
            "企业",
            "企业名称",
            "就职公司",
            "所在公司",
            "单位",
            "雇主",
            "任职单位",
            "任职时间",
            "任职期间",
            "入职时间",
            "入职日期",
            "职位",
            "岗位",
            "职务",
            "工作职位",
            "工作岗位",
            "work position",
            "job position",
            "担任职务",
            "角色",
            "职责",
            "工作内容",
            "work content",
            "公司",
            "company",
            "enterprise",
            "employer",
            "position",
            "role",
            "period",
            "responsibilities",
            "description",
            "employment",
            "employment dates",
            "work dates",
            "work date",
        ),
    ):
        return "experiences"
    if _starts_with_field(
        clean,
        (
            "技能",
            "技能特长",
            "专业技能",
            "技术栈",
            "技术能力",
            "编程语言",
            "工具",
            "框架",
            "数据库",
            "skills",
            "technical",
            "expertise",
            "proficiencies",
            "programming languages",
            "languages",
            "tools",
        ),
    ):
        return "skills"

    # 没有“校园经历”标题时，这些组织名称是比通用的 role/period 更强的
    # 校园信号。优先归到校园经历，避免学生会干部被当成工作经历。
    if re.search(
        r"学生会|团委|团支部|团支书|社团|校学生会|学院学生会|Student\s+Union|"
        r"Campus|Club|Student\s+Association|校内",
        clean,
        re.IGNORECASE,
    ):
        return "campus_experiences"

    date_match = _DATE_RANGE_RE.search(clean)
    if date_match:
        lowered = clean.casefold()
        if any(
            term in lowered
            for term in ("大学", "学院", "university", "college", "degree", "本科", "硕士", "博士")
        ):
            return "educations"
        if any(term in lowered for term in ("项目", "project", "app", "platform", "平台")):
            return "projects"
        if _PROFILE_ENGLISH_TITLE_RE.search(clean) or any(
            term in clean for term in ("公司", "单位", "实习", "任职", "工程师", "开发")
        ):
            return "experiences"

    # 只有明显的技能词串才启用技能兜底；普通一句话不会被误归类。
    if (
        len(clean) <= 180
        and not re.search(r"[。！？!?]", clean)
        and re.search(
            r"(?:Python|JavaScript|TypeScript|Java|Golang|React|Vue(?:\.js)?|"
            r"Fast\s*API|MySQL|PostgreSQL|Kubernetes|K8s|Docker|Linux|SQL|Git)",
            clean,
            re.IGNORECASE,
        )
    ):
        return "skills"

    return None


def _looks_like_unlabeled_entry_line(line: str) -> bool:
    """仅把带结构分隔符的短日期行视为新条目，避免正文日期触发换区。"""
    clean = _clean_line(line)
    match = _DATE_RANGE_RE.search(clean)
    if match is None or len(clean) > 160 or re.search(r"[。！？!?]", clean):
        return False
    prefix = clean[: match.start()].strip(" \t|｜丨·•—–－/~～")
    suffix = clean[match.end() :].strip(" \t|｜丨·•—–－/~～")
    return bool(prefix and (re.search(r"[|｜丨·•/／~～—–－-]", prefix + suffix) or not suffix))


def _looks_like_skill_list(line: str) -> bool:
    clean = _clean_line(line)
    if len(clean) > 160 or re.search(r"[。！？!?]", clean):
        return False
    tokens = [token.strip() for token in re.split(r"[,，、/|｜;；&]+", clean) if token.strip()]
    if len(tokens) < 2:
        return False
    known = sum(
        bool(
            re.search(
                r"(?:Python|Java|JavaScript|TypeScript|Golang|Go|C\+\+|React|Vue(?:\.js)?|"
                r"Angular|Node(?:\.js|JS)?|Fast\s*API|MySQL|PostgreSQL|SQLite|Redis|Kafka|"
                r"Kubernetes|K8s|Docker|Linux|Git|SQL|PyTorch|TensorFlow|RAG|LLM|AIGC)",
                token,
                re.IGNORECASE,
            )
        )
        for token in tokens
    )
    return known >= 2 and known >= len(tokens) - 1
