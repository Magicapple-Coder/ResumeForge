"""将用户粘贴的个人资料拆成可编辑草稿。

解析器只使用本地规则，不调用网络或大模型。它优先识别明确的分区标题和字段标签，
无法确定的内容保留在对应经历的描述中，最终仍由用户在资料页核对后保存。
"""

import re
from functools import lru_cache

from ..schemas.profile import ProfileTextParseResult


_SECTION_ALIASES = {
    "educations": (
        "教育经历",
        "教育背景",
        "学历经历",
        "学习经历",
        "教育信息",
        "学历背景",
        "教育履历",
        "教育与培训",
        "学历信息",
        "education",
        "education background",
        "education and training",
        "education & training",
    ),
    "experiences": (
        "实习经历",
        "工作经历",
        "任职经历",
        "工作履历",
        "职业经历",
        "工作经验",
        "任职履历",
        "工作与实习",
        "经历概览",
        "实践经历",
        "科研经历",
        "任职/实习经历",
        "实习/工作经验",
        "实习/工作经历",
        "工作/实习经历",
        "professional experience",
        "experience",
        "work experience",
        "work history",
        "professional history",
        "internship experience",
        "internships",
        "employment history",
        "employment",
    ),
    "campus_experiences": (
        "校园经历",
        "学生工作",
        "社团经历",
        "校内经历",
        "校园实践",
        "学生经历",
        "校园活动",
        "校园与社团",
        "学生组织经历",
        "社会实践",
        "志愿服务",
        "campus experience",
        "campus activities",
        "student activities",
        "student leadership",
        "leadership experience",
        "extracurricular experience",
        "extracurricular activities",
        "campus involvement",
    ),
    "projects": (
        "项目经历",
        "项目经验",
        "项目实践",
        "项目履历",
        "项目经验及实践",
        "项目与实践",
        "作品与项目",
        "projects",
        "projects & practice",
        "projects and practice",
        "project & practice",
        "project experience",
        "project and practice",
        "portfolio projects",
        "selected projects",
        "project highlights",
    ),
    "skills": (
        "专业技能",
        "技能清单",
        "技能",
        "技术栈",
        "技术能力",
        "专业能力",
        "核心技能",
        "编程技能",
        "工具技能",
        "IT技能",
        "能力特长",
        "技能特长",
        "专业特长",
        "核心能力",
        "职业技能",
        "技术专长",
        "语言能力",
        "skills",
        "technical skills",
        "technical abilities",
        "technical expertise",
        "technical proficiencies",
        "skills & certifications",
        "skills and certifications",
        "programming languages",
        "tools & technologies",
        "skills & tools",
        "competencies",
    ),
    "awards": (
        "荣誉奖项",
        "获奖情况",
        "获奖经历",
        "奖项",
        "荣誉",
        "奖励情况",
        "awards",
        "honors",
        "certifications",
        "certificates",
    ),
    "summary": (
        "个人总结",
        "自我评价",
        "个人总结/自我评价",
        "个人总结 / 自我评价",
        "个人简介",
        "个人概述",
        "职业简介",
        "个人亮点",
        "职业总结",
        "职业目标",
        "summary",
        "profile",
        "career summary",
        "professional summary",
        "professional profile",
        "about me",
    ),
}

# 这些标题不是表单分区，但出现时应结束上一分区，避免“基本信息”被
# 当成上一条经历的正文。它们仍由全局字段/正文启发式解析。
_RESET_SECTION_ALIASES = (
    "基本信息",
    "基本资料",
    "个人信息",
    "个人概况",
    "联系方式",
    "contact",
    "personal information",
)

_BASIC_LABELS = {
    "name": ("姓名", "名字", "真实姓名", "姓名拼音", "name", "full name", "candidate name"),
    "gender": ("性别", "gender"),
    "birth_year": ("出生年份", "出生年月", "出生日期", "生日", "出生信息", "birth"),
    "phone": (
        "手机号",
        "手机号码",
        "手机",
        "电话",
        "联系电话",
        "联系方式",
        "电话号",
        "phone",
        "mobile",
        "phone number",
        "telephone",
        "contact number",
    ),
    "email": (
        "邮箱",
        "电子邮箱",
        "电子邮件",
        "Email",
        "E-mail",
        "email",
        "mail",
        "email address",
    ),
    "city": (
        "所在城市",
        "现居城市",
        "所在地",
        "现居地",
        "现居",
        "当前城市",
        "居住地",
        "居住城市",
        "所在地城市",
        "籍贯",
        "出生地",
        "city",
        "current city",
        "current location",
        "location",
    ),
    "target_city": (
        "意向城市",
        "目标城市",
        "期望城市",
        "工作城市",
        "目标地点",
        "target city",
        "preferred location",
        "desired city",
    ),
    "job_intent": (
        "求职意向",
        "求职方向",
        "目标职位",
        "应聘职位",
        "意向职位",
        "目标岗位",
        "期望岗位",
        "期望职位",
        "职位意向",
        "career objective",
        "target role",
        "desired role",
        "objective",
    ),
    "personal_website": ("个人网站", "个人主页", "博客", "作品集", "portfolio", "website"),
    "github": ("GitHub", "Github", "github"),
}

_MONTH_NAME = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE_TOKEN = rf"(?:\d{{4}}(?:[./年-]\d{{1,2}})?(?:[./月-]\d{{1,2}})?|{_MONTH_NAME}\s+\d{{4}})"
_DATE_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE_TOKEN})\s*"
    rf"(?:至|到|[-—–－~～]|\bto\b)\s*"
    rf"(?P<end>{_DATE_TOKEN}|至今|现在|present|current|now)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(_DATE_TOKEN, re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[\s-]?)?1[3-9](?:[\s-]?\d){9}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
# 限制数字序号长度，避免把 ``2025.06-至今`` 的年份误当作列表编号剥掉。
_BULLET_RE = re.compile(r"^\s*(?:[-*•·]|\d{1,3}[、.)）.]|[一二三四五六七八九十]+[、.)）.])\s*")
_ENTRY_SEPARATOR_RE = re.compile(r"\s*(?:\||｜|丨|·|•|—|–|－|/|／|~|～|\s+-\s+)\s*")
# 普通英文名称中可能含有连字符；仅把带空格的横线，或中文字段之间的
# 无空格横线当作条目分隔符。日期范围已在调用方先移除。
_HEADER_SEPARATOR_RE = re.compile(
    r"\s*(?:\||｜|丨|·|•|—|–|－|/|／|~|～|\s+-\s+|(?<=[\u4e00-\u9fff])-(?=[\u4e00-\u9fffA-Za-z]))\s*"
)

_NUMBERED_HEADING_RE = re.compile(
    r"^(?:第\s*)?(?:\d+|[一二三四五六七八九十百]+)\s*(?:[、.)）.]|、)\s*"
)
_INLINE_LABEL_SEPARATOR_RE = re.compile(r"\s*(?:\||｜|丨|;|；|,|，)\s*")
_BASIC_UNLABELED_CITY_RE = re.compile(
    r"(?:北京|上海|天津|重庆|深圳|广州|杭州|成都|武汉|西安|南京|苏州|长沙|厦门|合肥|郑州|青岛|济南|大连|宁波|东莞|佛山|珠海|无锡|福州|昆明|南昌|沈阳|石家庄|哈尔滨|香港|澳门|台北|兰州|太原|南宁|海口|贵阳|乌鲁木齐|呼和浩特|温州|常州|嘉兴|绍兴|扬州|Beijing|Shanghai|Tianjin|Chongqing|Shenzhen|Guangzhou|Hangzhou|Chengdu|Wuhan|Xi'an|Nanjing|Suzhou|Remote|Hybrid)",
    re.IGNORECASE,
)
_BASIC_NAME_RE = re.compile(r"^[\u4e00-\u9fff]{2,6}(?:\s+[A-Za-z][A-Za-z .'-]{1,30})?$")
_BASIC_ENGLISH_NAME_RE = re.compile(
    r"^[A-Za-z][A-Za-z.'-]{1,30}(?:\s+[A-Za-z][A-Za-z.'-]{1,30}){1,3}$"
)
_PROFILE_ENGLISH_TITLE_RE = re.compile(
    r"\b(?:engineer|developer|programmer|architect|analyst|designer|scientist|"
    r"researcher|manager|consultant|specialist|intern|operator|lead|director|"
    r"technician|support|sales|recruiter|secretary|president|treasurer|"
    r"coordinator|administrator|volunteer|fellow)\b",
    re.IGNORECASE,
)
_ENGLISH_COMPANY_HINT_RE = re.compile(
    r"\b(?:inc(?:orporated)?|ltd|limited|llc|corp(?:oration)?|company|group|holdings?|"
    r"technolog(?:y|ies)|tech|software|systems?|solutions?|studio|labs?|consulting)\b",
    re.IGNORECASE,
)
_NON_NAME_MARKERS = (
    "教育",
    "经历",
    "简历",
    "求职",
    "应聘",
    "意向",
    "工程师",
    "开发",
    "岗位",
    "职位",
    "联系方式",
    "电话",
    "邮箱",
    "城市",
    "地址",
    "个人",
    "基本",
)
_SKILL_LEVEL_RE = re.compile(
    r"^(熟练掌握|熟练使用|熟练|精通|掌握|熟悉|了解|入门|精通使用|proficient|advanced|intermediate|beginner|basic)$",
    re.IGNORECASE,
)
_SKILL_LEADING_LEVEL_RE = re.compile(
    r"^(?P<level>熟练掌握|熟练使用|熟练|精通|掌握|熟悉|了解|入门|精通使用|proficient|advanced|intermediate|beginner|basic)\s*[:：、,，]?\s*(?P<skills>.+)$",
    re.IGNORECASE,
)

_DEGREE_TERMS = (
    "本科",
    "大学本科",
    "硕士",
    "博士",
    "专科",
    "大专",
    "学士",
    "研究生",
    "bachelor",
    "master",
    "phd",
    "doctorate",
    "associate",
)


def _normalize_lines(text: str) -> list[str]:
    # 仅归一化全角拉丁字母/数字和不可见空白，保留中文标点的原始语义。
    normalized_chars: list[str] = []
    for char in text:
        codepoint = ord(char)
        if char == "\u3000":
            normalized_chars.append(" ")
        elif (
            0xFF10 <= codepoint <= 0xFF19
            or 0xFF21 <= codepoint <= 0xFF3A
            or 0xFF41 <= codepoint <= 0xFF5A
        ):
            normalized_chars.append(chr(codepoint - 0xFEE0))
        else:
            normalized_chars.append(char)
    normalized = "".join(normalized_chars)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00a0", " ").replace("\u200b", "")
    normalized = normalized.replace("\u2028", "\n").replace("\u2029", "\n")
    lines: list[str] = []
    previous_blank = False
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            if lines and not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        lines.append(line)
        previous_blank = False
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _clean_line(line: str) -> str:
    return _BULLET_RE.sub("", line.lstrip("# ")).strip()


def _compact_heading(value: str) -> str:
    """统一标题的编号、括号和中英文空白，容纳不同模板的复制结果。"""
    candidate = _NUMBERED_HEADING_RE.sub("", value.strip())
    candidate = candidate.rstrip("：:").strip()
    # 常见模板会在中文标题后附 ``(Education)`` 或 ``/ English``。
    english_section_words = (
        r"education(?:\s+(?:background|and\s+training))?|"
        r"(?:work|professional|campus|leadership|internship|extracurricular)\s+experience|"
        r"(?:work|professional|employment)\s+history|"
        r"projects?(?:\s+(?:and|&)\s+practice|\s+experience)?|"
        r"portfolio\s+projects?|"
        r"(?:technical\s+)?(?:skills?|expertise|proficiencies?)|"
        r"skills?\s+(?:and|&)\s+certifications|"
        r"programming\s+languages|tools\s+(?:and|&)\s+technologies|"
        r"awards?|honors?|certificates?|certifications?|summary|profile"
    )
    candidate = re.sub(
        rf"\s*[（(](?:{english_section_words})[）)]\s*$", "", candidate, flags=re.IGNORECASE
    )
    candidate = re.sub(
        rf"\s*(?:/|｜|\|)\s*(?:{english_section_words})\s*$", "", candidate, flags=re.IGNORECASE
    )
    candidate = re.sub(
        rf"^(?:{english_section_words})\s*(?:/|｜|\|)\s*", "", candidate, flags=re.IGNORECASE
    )
    return re.sub(r"[\s（）()【】\[\]·•_-]", "", candidate).casefold()


_COMPACT_SECTION_ALIASES = {
    key: {_compact_heading(alias) for alias in aliases} for key, aliases in _SECTION_ALIASES.items()
}
_COMPACT_RESET_ALIASES = {_compact_heading(alias) for alias in _RESET_SECTION_ALIASES}


def _heading_parts(line: str) -> tuple[str | None, str]:
    clean = _clean_line(line)
    # 先尝试完整标题；随后处理“技能：Python、SQL”这种标题和内容同在一行。
    compact = _compact_heading(clean)
    for key, aliases in _COMPACT_SECTION_ALIASES.items():
        if compact in aliases:
            return key, ""

    numbered_removed = _NUMBERED_HEADING_RE.sub("", clean, count=1)
    for separator in ("：", ":"):
        if separator not in numbered_removed:
            continue
        heading, content = numbered_removed.split(separator, 1)
        heading_compact = _compact_heading(heading)
        for key, aliases in _COMPACT_SECTION_ALIASES.items():
            if heading_compact in aliases:
                return key, content.strip()
    # “教育背景 / Education” 和 “Projects - 项目经历” 等模板用横线连接
    # 中英文标题；只有两侧都能映射到同一分区时才接受，避免误切普通正文。
    for separator in ("/", "／", "|", "｜", "-", "—", "–"):
        if separator not in numbered_removed:
            continue
        left, right = (part.strip() for part in numbered_removed.split(separator, 1))
        left_key = next(
            (
                key
                for key, aliases in _COMPACT_SECTION_ALIASES.items()
                if _compact_heading(left) in aliases
            ),
            None,
        )
        right_key = next(
            (
                key
                for key, aliases in _COMPACT_SECTION_ALIASES.items()
                if _compact_heading(right) in aliases
            ),
            None,
        )
        if left_key and right_key and left_key == right_key:
            return left_key, ""
    return None, ""


def _heading_key(line: str) -> str | None:
    return _heading_parts(line)[0]


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


@lru_cache(maxsize=64)
def _field_start_pattern(labels: tuple[str, ...]) -> re.Pattern[str]:
    """缓存字段起始匹配器，粘贴大段文本时避免逐行重复编译。"""
    alternatives = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    return re.compile(rf"^(?:{alternatives})(?:\s*[:：]|\s+)", re.IGNORECASE)


def _starts_with_field(line: str, labels: tuple[str, ...]) -> bool:
    return bool(_field_start_pattern(labels).match(_clean_line(line)))


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


def _infer_section_from_unlabeled_sequence(
    lines: list[str], index: int
) -> tuple[str, tuple[int, int]] | None:
    """从“组织/公司 + 角色 + 独立日期”三行结构补齐缺失分区标题。"""
    date_line = _clean_line(lines[index])
    if _DATE_RANGE_RE.fullmatch(date_line) is None:
        return None

    previous_indices = [
        previous_index
        for previous_index in range(index - 1, -1, -1)
        if _clean_line(lines[previous_index])
    ][:2]
    if len(previous_indices) != 2:
        return None
    role_index, subject_index = previous_indices
    role = _clean_line(lines[role_index])
    subject = _clean_line(lines[subject_index])
    if not _looks_like_profile_role_line(role):
        return None
    if (
        len(subject) > 96
        or (
            _BASIC_NAME_RE.fullmatch(subject)
            and not re.search(r"公司|集团|科技|工作室|银行|研究院|事务所|企业", subject)
        )
        # 两词英文公司名（如 ``Example Technology``）与英文人名形态相同。
        # 仅在缺少公司后缀/行业词时继续按人名处理，避免无标题英文经历整体丢失。
        or (
            _BASIC_ENGLISH_NAME_RE.fullmatch(subject)
            and _ENGLISH_COMPANY_HINT_RE.search(subject) is None
        )
        or _is_header_metadata_line(subject)
        or re.search(r"[。！？!?]", subject)
    ):
        return None

    context = f"{subject}\n{role}"
    if re.search(
        r"学生会|团委|团支部|团支书|社团|Student\s+Union|Campus|Club|"
        r"Student\s+Association|校内",
        context,
        re.IGNORECASE,
    ):
        return "campus_experiences", (subject_index, role_index)
    if re.search(r"项目|平台|系统|应用|小程序|Project|App|Platform|System", subject, re.IGNORECASE):
        return "projects", (subject_index, role_index)
    if re.search(
        r"大学|学院|University|College|本科|硕士|博士|Bachelor|Master", context, re.IGNORECASE
    ):
        return "educations", (subject_index, role_index)
    return "experiences", (subject_index, role_index)


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


def _starts_explicit_section_transition(line: str, section: str) -> bool:
    """判断显式分区后的强字段是否足以开始另一个分区。

    已有分区标题时，普通日期、角色和技能词的证据不足以切换分区；但
    ``项目名称：``、``公司：`` 这类唯一字段通常表示用户省略了下一个
    标题，应该优先恢复为新的结构化记录。
    """
    labels_by_section = {
        "educations": (
            "学校",
            "院校",
            "学校名称",
            "school",
            "university",
            "college",
        ),
        "experiences": (
            "公司",
            "公司名称",
            "企业",
            "企业名称",
            "就职公司",
            "所在公司",
            "单位",
            "雇主",
            "company",
            "enterprise",
            "employer",
        ),
        "campus_experiences": (
            "组织",
            "组织名称",
            "社团",
            "社团名称",
            "学生组织",
            "所在组织",
            "学生会",
            "团委",
            "organization",
            "organization name",
            "student union",
            "club",
        ),
        "projects": ("项目名称", "项目标题", "project name"),
        "skills": (
            "专业技能",
            "技能清单",
            "技能特长",
            "skills",
            "technical skills",
            "programming languages",
        ),
    }
    return _starts_with_field(line, labels_by_section.get(section, ()))


def _is_context_detail_field(line: str, section: str) -> bool:
    """判断无标题分区中仍属于当前条目的通用字段。"""
    shared_entry_labels = (
        "角色",
        "担任角色",
        "职位",
        "岗位",
        "职务",
        "role",
        "position",
        "position name",
        "work position",
        "job position",
        "job title",
        "period",
        "时间",
        "周期",
        "duration",
        "description",
        "描述",
        "responsibilities",
        "职责",
        "工作内容",
        "工作描述",
        "work content",
        "employment",
        "employment dates",
        "employment date",
        "work dates",
        "work date",
        "job dates",
        "study period",
        "study dates",
        "入职时间",
        "入职日期",
        "就业时间",
        "就职时间",
        "参与时间",
        "参与日期",
        "任职日期",
    )
    labels_by_section = {
        "educations": (
            "专业",
            "所学专业",
            "学历",
            "学位",
            "核心课程",
            "课程",
            "major",
            "degree",
            "courses",
            "time",
            "period",
        ),
        "experiences": shared_entry_labels + ("任职时间", "任职期间", "工作内容"),
        "campus_experiences": shared_entry_labels
        + ("校园活动", "活动内容", "参与时间", "参与日期"),
        "projects": shared_entry_labels
        + ("项目周期", "项目时间", "项目描述", "项目内容", "项目成果", "亮点"),
    }
    return _starts_with_field(line, labels_by_section.get(section, ()))


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {key: [] for key in _SECTION_ALIASES}
    current: str | None = None
    # 明确分区标题具有更高可信度；进入该分区后，条目中的日期、学校名或
    # 技能词只应作为内容解析，不能再次触发跨分区推断。无标题粘贴文本
    # 仍通过 ``current_explicit=False`` 保留按强信号切换分区的能力。
    current_explicit = False
    for index, line in enumerate(lines):
        clean = _clean_line(line)
        # 在项目块内，未编号的“技术栈：...”属于该项目。编号标题仍优先视为
        # 新分区，以支持“4. 技术能力：...”这样的简历模板。
        if (
            current == "projects"
            and _is_project_detail_line(clean)
            and _NUMBERED_HEADING_RE.match(line) is None
        ):
            sections[current].append(line)
            continue
        key, inline_content = _heading_parts(line)
        if key is not None:
            current = key
            current_explicit = True
            if inline_content:
                sections[key].append(inline_content)
            continue
        if _compact_heading(clean) in _COMPACT_RESET_ALIASES:
            current = None
            current_explicit = False
            continue
        inferred = _infer_section_for_unlabeled_line(clean)
        sequence_indices: tuple[int, int] | None = None
        if inferred is None and current is None:
            sequence = _infer_section_from_unlabeled_sequence(lines, index)
            if sequence is not None:
                inferred, sequence_indices = sequence
        # 无标题文本中的“项目名称/组织名称 -> 角色 -> 周期”字段会被通用
        # ``role/period`` 规则暂时归到工作经历；在当前上下文已明确时，这些
        # 字段没有足够证据启动新分区，应保留在当前条目中。
        if (
            current is not None
            and not current_explicit
            and inferred != current
            and _is_context_detail_field(clean, current)
        ):
            inferred = None
        if inferred is not None and (
            current is None
            or (
                inferred != current
                and (
                    _starts_explicit_section_transition(clean, inferred)
                    if current_explicit
                    else (
                        re.match(r"^[^：:]{1,32}\s*[:：]", clean) is not None
                        or _looks_like_unlabeled_entry_line(clean)
                        or (inferred == "skills" and _looks_like_skill_list(clean))
                    )
                )
            )
        ):
            current = inferred
            current_explicit = False
            if sequence_indices is not None:
                sections[current].extend(
                    lines[sequence_index] for sequence_index in sequence_indices
                )
            sections[current].append(line)
            continue
        if current is not None:
            sections[current].append(line)
    return sections


@lru_cache(maxsize=64)
def _label_value_pattern(labels: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(label) for label in labels)
    return re.compile(
        rf"^(?:{alternatives})(?:\s*[:：]\s*|\s+)(?P<value>.+?)\s*$",
        re.IGNORECASE,
    )


def _label_value(line: str, labels: tuple[str, ...]) -> str:
    match = _label_value_pattern(labels).match(line)
    return match.group("value").strip() if match else ""


@lru_cache(maxsize=64)
def _label_matches_pattern(labels: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    return re.compile(rf"(?<![\w\u4e00-\u9fff])(?:{alternatives})(?=\s*[:：]|\s+|$)", re.IGNORECASE)


def _label_matches(line: str, labels: tuple[str, ...]) -> list[tuple[int, int, str]]:
    """返回一行中所有字段标签的位置，支持 ``姓名 张三 手机 138...``。"""
    matches = list(_label_matches_pattern(labels).finditer(line))
    return [(match.start(), match.end(), match.group(0)) for match in matches]


def _extract_inline_labeled_values(line: str) -> dict[str, str]:
    """解析同一行的多个基本字段，不把后续标签吞进当前字段值。"""
    matches: list[tuple[int, int, str, str]] = []
    for field, labels in _BASIC_LABELS.items():
        for start, end, label in _label_matches(line, labels):
            # ``Project Name:``/``Company Name:`` 中的裸 ``Name`` 不是候选人
            # 姓名字段；完整的 ``project name``/``candidate name`` 别名会在
            # 更长匹配中优先保留，因此这里只过滤带英文前缀的短别名。
            if field == "name" and label.casefold() == "name":
                prefix = line[:start].rstrip()
                if prefix and prefix[-1].isalnum():
                    continue
            matches.append((start, end, field, label))
    # 同一位置可能同时匹配大小写别名，最长别名优先；之后按文本位置排序。
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str, str]] = []
    for match in matches:
        if selected and match[0] < selected[-1][1]:
            continue
        selected.append(match)

    values: dict[str, str] = {}
    for index, (start, end, field, _label) in enumerate(selected):
        value_start = end
        while value_start < len(line) and line[value_start] in " \t:：":
            value_start += 1
        value_end = selected[index + 1][0] if index + 1 < len(selected) else len(line)
        value = line[value_start:value_end].strip(" \t:：|｜丨;；,，")
        if value and field not in values:
            values[field] = value
    return values


def _extract_unlabeled_basic(lines: list[str], values: dict[str, str]) -> None:
    """从简历模板常见的联系方式行补齐没有字段标签的基本信息。"""
    preamble: list[str] = []
    for line in lines:
        if _heading_key(line) is not None:
            break
        if _compact_heading(_clean_line(line)) in _COMPACT_RESET_ALIASES:
            continue
        preamble.append(_clean_line(line))

    full_text = "\n".join(preamble)
    if not values["gender"]:
        match = re.search(r"(?<![男女])([男女])(?:性)?(?:\s|$|[|｜丨,，;；])", full_text)
        if match:
            values["gender"] = match.group(1)
        else:
            match = re.search(
                r"(?<![A-Za-z])(?P<gender>female|male|woman|man|non[- ]binary)(?![A-Za-z])",
                full_text,
                re.IGNORECASE,
            )
            if match:
                values["gender"] = match.group("gender")
    if not values["birth_year"]:
        match = re.search(r"((?:19|20)\d{2}\s*(?:年出生|年生|年|出生))", full_text)
        if match:
            values["birth_year"] = match.group(1).replace(" ", "")
        else:
            # 只有身份首行明确出现 born，或首行同时包含姓名/联系方式等
            # 身份信号时，才把独立四位年份当作出生年；否则项目/任职日期
            # 中的年份不应污染基本资料。
            identity_line = preamble[0] if preamble else ""
            has_identity_signal = bool(
                _PHONE_RE.search(identity_line)
                or _EMAIL_RE.search(identity_line)
                or re.search(r"(?:男|女|male|female|born|出生)", identity_line, re.IGNORECASE)
            )
            year_source = identity_line if has_identity_signal else ""
            match = re.search(
                r"(?:\bborn\s*)?((?:19|20)\d{2})(?:\s*(?:year|born))?\b",
                year_source,
                re.IGNORECASE,
            )
            if match:
                values["birth_year"] = match.group(1)
    if not values["city"]:
        # 只接受独立城市 token，避免把“意向城市：北京”误写为现居城市。
        for line in preamble:
            for token in re.split(r"[\s|｜丨,，;；]+", line):
                city_match = _BASIC_UNLABELED_CITY_RE.fullmatch(token.rstrip("市"))
                if city_match:
                    values["city"] = city_match.group(0)
                    break
            if values["city"]:
                break

    if not values["name"]:
        has_identity_context = bool(
            _PHONE_RE.search(full_text)
            or _EMAIL_RE.search(full_text)
            or values["gender"]
            or values["birth_year"]
            or values["city"]
        )
        for line in preamble:
            # 常见简历首行会用空格排列“姓名 性别 城市 电话”；先只取行首
            # 的短中文姓名，避免把后面的学校或岗位描述当成姓名。
            leading_name = re.match(r"^([\u4e00-\u9fff]{2,6})(?=\s+|[|｜丨,，;；]|$)", line)
            if (
                leading_name
                and (has_identity_context or line == preamble[0])
                and not any(marker in leading_name.group(1) for marker in _NON_NAME_MARKERS)
            ):
                values["name"] = leading_name.group(1)
                return
            candidate = line
            candidate = _PHONE_RE.sub("", candidate)
            candidate = _EMAIL_RE.sub("", candidate)
            candidate = _URL_RE.sub("", candidate)
            tokens = [
                token.strip()
                for token in _INLINE_LABEL_SEPARATOR_RE.split(candidate)
                if token.strip()
            ]
            for token in tokens:
                token = re.sub(r"(?:男|女)(?:性)?$", "", token).strip()
                token = re.sub(r"(?:19|20)\d{2}\s*年?(?:出生|年生)?$", "", token).strip()
                if (
                    (has_identity_context or line == preamble[0])
                    and (_BASIC_NAME_RE.fullmatch(token) or _BASIC_ENGLISH_NAME_RE.fullmatch(token))
                    and not _PROFILE_ENGLISH_TITLE_RE.search(token)
                    and not any(marker in token for marker in _NON_NAME_MARKERS)
                ):
                    values["name"] = token
                    return


def _extract_basic(lines: list[str]) -> dict[str, str]:
    values = {field: "" for field in _BASIC_LABELS}
    for line in lines:
        inline_values = _extract_inline_labeled_values(line)
        for field, value in inline_values.items():
            if value and not values[field]:
                values[field] = value
        for field, labels in _BASIC_LABELS.items():
            value = _label_value(line, labels)
            if value and not values[field]:
                values[field] = value

    full_text = "\n".join(lines)
    # “联系方式：手机 / 邮箱”可能被整体识别为一个标签值；二次提取保证
    # phone/email 字段始终只保存对应格式，不把另一字段或分隔符带进去。
    phone_source = values["phone"] or full_text
    phone_match = _PHONE_RE.search(phone_source)
    if phone_match:
        phone_digits = re.sub(r"\D", "", phone_match.group(0))
        values["phone"] = phone_digits[2:] if phone_digits.startswith("86") else phone_digits
    else:
        values["phone"] = ""
    email_source = values["email"] or full_text
    email_match = _EMAIL_RE.search(email_source)
    values["email"] = email_match.group(0) if email_match else ""
    if not values["github"]:
        match = re.search(r"https?://(?:www\.)?github\.com/[^\s<>\"']+", full_text, re.IGNORECASE)
        values["github"] = match.group(0).rstrip(".,;，。；") if match else ""
    if not values["personal_website"]:
        urls = _URL_RE.findall(full_text)
        values["personal_website"] = next(
            (url.rstrip(".,;，。；") for url in urls if "github.com" not in url.lower()), ""
        )
    _extract_unlabeled_basic(lines, values)
    return values


def _split_entry_blocks(lines: list[str], kind: str = "") -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                blocks.append(current)
                current = []
            continue
        if current and _looks_like_entry_header(line, kind):
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _looks_like_entry_header(line: str, kind: str = "") -> bool:
    clean = _clean_line(line)
    if not clean or len(clean) > 180:
        return False
    # 新条目的第一行应与解析阶段认可的字段别名保持一致。这里不能只列
    # 几个中文写法，否则连续粘贴的 ``Company:`` / ``就职公司：`` 会被
    # 合并为一条经历，第二段内容也随之丢失。
    primary_label = _ENTRY_HEADER_PATTERNS.get(kind, _ENTRY_HEADER_PATTERNS["default"])
    # “学历：硕士”“任职时间：...”等同一条记录的字段可能包含日期或学位词，
    # 必须先排除，避免被后面的通用日期/学历启发式误切成新记录。
    if _is_header_metadata_line(clean):
        return bool(primary_label.match(clean))
    date_match = _DATE_RANGE_RE.search(clean)
    if date_match:
        # 只把带有结构分隔符、日期位于行首/行尾的短行当作经历头部。
        # 正文中的“2024-2025 完成迁移”也含日期，但不应因此切断当前条目。
        prefix = clean[: date_match.start()].strip(" \t|｜丨·•—–－/~～")
        suffix = clean[date_match.end() :].strip(" \t|｜丨·•—–－/~～")
        if not prefix and not suffix:
            return False
        if len(clean) > 160 or re.search(r"[。！？!?]", clean):
            return False
        return bool(
            prefix
            and (re.search(r"[|｜丨·•/／~～—–－-]", prefix + suffix) or not suffix)
            or suffix
            and (re.search(r"[|｜丨·•/／~～—–－-]", prefix + suffix) or not prefix)
        )
    if primary_label.match(clean):
        return True
    has_unspaced_hyphen = bool(re.search(r"(?<!\d)-(?!\d)", clean))
    if _ENTRY_SEPARATOR_RE.search(clean) or has_unspaced_hyphen:
        # 分隔符只有在短标题中才有足够结构信号；正文中的“技术/业务”不应
        # 让当前条目被误切开。
        return (
            len(clean) <= 128
            and not re.search(r"[。！？!?]", clean)
            and not re.match(r"^(?:负责|参与|协助|完成|实现|使用|开发|设计|优化)", clean)
        )
    if kind == "education":
        return bool(
            re.search(r"(?:本科|硕士|博士|专科|学士|研究生)", clean)
            and len(clean) <= 100
            and not re.search(r"[。！？!?]", clean)
        )
    return False


_HEADER_LABEL_ALIASES = {
    "school": (
        "学校",
        "院校",
        "学校名称",
        "毕业院校",
        "毕业学校",
        "graduated from",
        "school",
        "university",
        "college",
    ),
    "major": ("专业", "所学专业", "专业名称", "major", "field of study"),
    "degree": ("学历", "学位", "学历学位", "degree", "education"),
    "company": (
        "公司",
        "单位",
        "公司名称",
        "企业",
        "企业名称",
        "就职公司",
        "任职单位",
        "所在公司",
        "雇主",
        "employer name",
        "company",
        "company name",
        "enterprise",
        "employer",
        "organization name",
        "organization",
    ),
    "organization": (
        "组织",
        "组织/部门",
        "组织名称",
        "社团",
        "社团名称",
        "学生组织",
        "所在组织",
        "组织机构",
        "学生会",
        "团委",
        "部门",
        "organization",
        "department",
        "club",
        "student union",
        "organization name",
    ),
    "role": (
        "职位",
        "岗位",
        "职位名称",
        "岗位名称",
        "职务",
        "角色",
        "担任角色",
        "职称",
        "工作职位",
        "工作岗位",
        "work position",
        "job position",
        "担任职务",
        "职位名称",
        "岗位名称",
        "role",
        "position",
        "position name",
        "job title",
        "title",
    ),
    "project": (
        "项目",
        "项目名称",
        "项目标题",
        "项目名",
        "project",
        "project name",
        "project title",
    ),
}

# 按经历类型预编译条目起始字段，既与字段提取共用同一份别名，又避免在
# 每一行粘贴文本上重复拼接大正则。
_ENTRY_HEADER_FIELDS_BY_KIND = {
    "education": ("school",),
    "experience": ("company",),
    "campus": ("organization",),
    "project": ("project",),
    "default": ("school", "company", "organization", "project"),
}
_ENTRY_HEADER_PATTERNS = {
    kind: re.compile(
        rf"^(?:{'|'.join(re.escape(label) for field in fields for label in sorted(_HEADER_LABEL_ALIASES[field], key=len, reverse=True))})\s*[:：]",
        re.IGNORECASE,
    )
    for kind, fields in _ENTRY_HEADER_FIELDS_BY_KIND.items()
}
_HEADER_BOUNDARY_LABELS = (
    *(label for labels in _HEADER_LABEL_ALIASES.values() for label in labels),
    "时间",
    "起止时间",
    "任职时间",
    "任职期间",
    "任职周期",
    "在职时间",
    "工作时间",
    "入职时间",
    "入职日期",
    "就业时间",
    "就职时间",
    "参与时间",
    "参与日期",
    "工作日期",
    "就业日期",
    "任职日期",
    "项目期间",
    "项目日期",
    "学习期间",
    "学习日期",
    "项目周期",
    "项目时间",
    "项目起止时间",
    "就读时间",
    "学习时间",
    "周期",
    "日期",
    "time",
    "period",
    "employment period",
    "work period",
    "duration",
    "date",
    "dates",
    "employment dates",
    "employment date",
    "work dates",
    "work date",
    "job dates",
    "study period",
    "study dates",
    "start date",
    "end date",
)


def _header_labeled_value(line: str, field: str) -> str:
    """从带多个字段的经历头部提取指定值，例如“公司：A 职位：B”。"""
    all_labels = sorted(set(_HEADER_BOUNDARY_LABELS), key=len, reverse=True)
    alternatives = "|".join(re.escape(label) for label in all_labels)
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_])(?P<label>{alternatives})\s*[:：]\s*",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(line))
    if not matches:
        return ""
    selected: list[re.Match[str]] = []
    for match in matches:
        # “项目名称”与“项目”等标签可能在同一位置起始；词典按长度排序，
        # 仅保留最长标签，避免短标签提前截断字段值。
        if selected and match.start() < selected[-1].end():
            continue
        selected.append(match)

    labels = {label.casefold() for label in _HEADER_LABEL_ALIASES[field]}
    for index, match in enumerate(selected):
        if match.group("label").casefold() not in labels:
            continue
        value_end = selected[index + 1].start() if index + 1 < len(selected) else len(line)
        value = line[match.end() : value_end]
        # 日期已由专门逻辑提取，不能残留在公司、项目或角色字段中。
        return _DATE_RANGE_RE.sub("", value).strip(" \t|｜丨;,；，/／-—–－~～")
    return ""


def _block_labeled_value(block: list[str], field: str) -> str:
    for line in block:
        value = _header_labeled_value(line, field)
        if value:
            return value
    return ""


def _is_header_metadata_line(line: str) -> bool:
    labels = "|".join(
        re.escape(label) for label in sorted(set(_HEADER_BOUNDARY_LABELS), key=len, reverse=True)
    )
    return bool(re.match(rf"^(?:{labels})\s*[:：]", _clean_line(line), re.IGNORECASE))


def _parse_header(line: str) -> tuple[list[str], str, str]:
    clean = _clean_line(line)
    date_match = _DATE_RANGE_RE.search(clean)
    start_date = date_match.group("start") if date_match else ""
    end_date = date_match.group("end") if date_match else ""
    if date_match:
        clean = (clean[: date_match.start()] + clean[date_match.end() :]).strip(
            " -—–－~～|｜丨·/／"
        )
    # 日期已先移除，因此此处可以兼容未加空格的 ``公司-岗位-时间`` 格式，
    # 又不会把年月中的连字符切开。
    parts = [part.strip() for part in _HEADER_SEPARATOR_RE.split(clean) if part.strip()]
    if len(parts) == 1:
        parts = [part.strip() for part in re.split(r"\s{2,}|\t+", clean) if part.strip()]
    return parts, start_date, end_date


def _compact_header_fields(line: str, kind: str) -> dict[str, str]:
    """保守拆解“日期 学校 专业 学历”这类无分隔符的单行头部。

    仅在存在日期、没有显式分隔符且教育行包含学历词时启用；工作和项目行
    也要求至少有两个短 token，避免把自然语言描述拆成公司/项目名称。
    """
    clean = _clean_line(line)
    date_match = _DATE_RANGE_RE.search(clean)
    if date_match is None:
        return {}
    body = (clean[: date_match.start()] + clean[date_match.end() :]).strip(" -—–－~～|｜丨·•/／")
    if not body or re.search(r"[|｜丨/／·•—–－~～-]", body) or re.search(r"[:：]", body):
        return {}
    tokens = body.split()
    if len(tokens) < 2 or any(len(token) > 64 for token in tokens):
        return {}

    if kind == "education":
        degree_index = next(
            (
                index
                for index, token in enumerate(tokens)
                if any(term.casefold() in token.casefold() for term in _DEGREE_TERMS)
            ),
            -1,
        )
        if degree_index < 2:
            return {}
        # 英文院校名通常由多个词组成；优先把 University/College/Institute
        # 及其前缀一起作为学校，其余部分才是专业，避免只取首个词。
        school_end = 1
        for index, token in enumerate(tokens[:degree_index], start=1):
            if re.fullmatch(r"(?:university|college|institute|school)", token, re.IGNORECASE):
                school_end = index
                break
        if school_end >= degree_index:
            school_end = 1
        return {
            "school": " ".join(tokens[:school_end]),
            "major": " ".join(tokens[school_end:degree_index]),
            "degree": tokens[degree_index],
            "start_date": date_match.group("start"),
            "end_date": date_match.group("end"),
        }

    if kind in {"experience", "project"} and len(tokens) >= 2:
        body_text = " ".join(tokens)
        # 英文职位通常以 Engineer/Developer/Manager 等词结尾；保留其
        # 前面的方向词（如 Backend），把前面的词作为公司/项目名。
        english_role = re.search(
            r"\b(?:backend|frontend|full[- ]?stack|software|data|machine\s+learning|ai|ml|mobile|web|devops)?\s*"
            r"(?:engineer|developer|programmer|architect|analyst|designer|scientist|researcher|"
            r"manager|consultant|specialist|intern|lead|director|technician)\b",
            body_text,
            re.IGNORECASE,
        )
        if english_role and english_role.start() > 0:
            first = body_text[: english_role.start()].strip()
            role = body_text[english_role.start() :].strip()
            if first and role:
                return {
                    "first": first,
                    "role": role,
                    "start_date": date_match.group("start"),
                    "end_date": date_match.group("end"),
                }
        chinese_role = re.search(
            r"(?:后端|前端|全栈|算法|软件|数据|产品|项目|测试|研发|运维|网络|客户端)?"
            r"(?:工程师|开发|程序员|架构师|分析师|经理|负责人|专员|研究员|设计师|实习生|助理|顾问)",
            body_text,
        )
        if chinese_role and chinese_role.start() > 0:
            first = body_text[: chinese_role.start()].strip()
            role = body_text[chinese_role.start() :].strip()
            if first and role:
                return {
                    "first": first,
                    "role": role,
                    "start_date": date_match.group("start"),
                    "end_date": date_match.group("end"),
                }
        return {
            "first": tokens[0],
            "role": " ".join(tokens[1:]),
            "start_date": date_match.group("start"),
            "end_date": date_match.group("end"),
        }
    return {}


def _find_date_range(lines: list[str], start: str, end: str) -> tuple[str, str]:
    if start or end:
        return start, end
    match = _DATE_RANGE_RE.search(" ".join(lines))
    return (match.group("start"), match.group("end")) if match else ("", "")


_PROFILE_CHINESE_ROLE_RE = re.compile(
    r"(?:工程师|开发|程序员|架构师|分析师|经理|负责人|主管|总监|专员|研究员|"
    r"设计师|实习生|助理|顾问|运营|产品|测试|算法|部长|主席|团支书|书记|"
    r"秘书|志愿者|干事|会长|班长|委员|老师|讲师)"
)


def _looks_like_profile_role_line(line: str) -> bool:
    """识别无标签条目中的角色行，避免把公司/项目名当成角色。"""
    clean = _clean_line(line)
    if (
        not clean
        or len(clean) > 96
        or _DATE_RANGE_RE.fullmatch(clean)
        or _is_header_metadata_line(clean)
        or re.search(r"[。！？!?]", clean)
        or re.match(r"^(?:负责|参与|协助|完成|实现|使用|开发|设计|优化|承担)", clean)
    ):
        return False
    return bool(_PROFILE_CHINESE_ROLE_RE.search(clean) or _PROFILE_ENGLISH_TITLE_RE.search(clean))


def _infer_unlabeled_header(
    block: list[str],
) -> tuple[str, str, str, str, list[str]]:
    """从“公司名 / 角色 / 日期 / 描述”连续文本中恢复条目头部。"""
    clean_block = [_clean_line(line) for line in block if _clean_line(line)]
    if len(clean_block) < 2:
        return "", "", "", "", clean_block

    date_index = next(
        (index for index, line in enumerate(clean_block) if _DATE_RANGE_RE.fullmatch(line)),
        None,
    )
    date_start = date_end = ""
    if date_index is not None:
        date_match = _DATE_RANGE_RE.fullmatch(clean_block[date_index])
        if date_match:
            date_start = date_match.group("start")
            date_end = date_match.group("end")

    first_index = next(
        (
            index
            for index, line in enumerate(clean_block)
            if index != date_index and not _is_header_metadata_line(line)
        ),
        None,
    )
    if first_index is None:
        return "", "", date_start, date_end, clean_block

    role_index = next(
        (
            index
            for index, line in enumerate(clean_block)
            if index > first_index and index != date_index and _looks_like_profile_role_line(line)
        ),
        None,
    )
    if role_index is None:
        return "", "", date_start, date_end, clean_block

    ignored = {first_index, role_index}
    if date_index is not None:
        ignored.add(date_index)
    details = [line for index, line in enumerate(clean_block) if index not in ignored]
    return clean_block[first_index], clean_block[role_index], date_start, date_end, details


def _detail_groups(lines: list[str]) -> tuple[list[str], list[str], list[str], str, str, str]:
    description: list[str] = []
    highlights: list[str] = []
    tech_stack: list[str] = []
    courses: list[str] = []
    achievements: list[str] = []
    gpa = ""
    active = description
    for raw_line in lines:
        line = _clean_line(raw_line)
        if not line:
            continue
        match = re.match(r"^([^：:]{1,32})\s*[:：]\s*(.+)$", line)
        if match:
            label = match.group(1).strip().lower()
            value = match.group(2).strip()
            if any(
                term in label
                for term in (
                    "技术栈",
                    "技术",
                    "工具",
                    "技术方案",
                    "tech stack",
                    "technical stack",
                    "tech skills",
                    "technologies",
                    "tools",
                )
            ):
                tech_stack.extend(_split_tokens(value))
                continue
            if any(
                term in label
                for term in (
                    "亮点",
                    "成果",
                    "结果",
                    "业绩",
                    "highlights",
                    "achievements",
                    "results",
                )
            ):
                active = highlights
                highlights.append(value)
                continue
            if any(term in label for term in ("课程", "核心课", "courses", "coursework")):
                courses.extend(_split_tokens(value))
                continue
            if any(term in label for term in ("绩点", "排名", "成绩", "gpa", "rank", "grade")):
                gpa = value
                continue
            if any(term in label for term in ("奖项", "荣誉", "award", "honor")):
                achievements.append(value)
                continue
            if any(
                term in label
                for term in (
                    "描述",
                    "职责",
                    "工作内容",
                    "项目内容",
                    "description",
                    "responsibilities",
                    "duties",
                    "content",
                )
            ):
                active = description
                description.append(value)
                continue
        active.append(line)
    return description, highlights, tech_stack, "、".join(courses), "\n".join(achievements), gpa


def _split_tokens(value: str) -> list[str]:
    # 斜杠通常是分隔符，但 CI/CD 是一个完整技能；先保护它，避免被拆成
    # 两个无意义的 “CI”/“CD” 标签。
    protected = re.sub(r"\bCI\s*/\s*CD\b", "CI_CD", value, flags=re.IGNORECASE)
    return [
        token.strip().replace("CI_CD", "CI/CD").replace("ci_cd", "CI/CD")
        for token in re.split(
            r"[,，、/|｜;；&\n]+|\s+(?:and|以及|及)\s+",
            protected,
            flags=re.IGNORECASE,
        )
        if token.strip()
    ]


def _normalize_skill_name(value: str) -> str:
    """保留用户的自定义技能，同时统一高置信度的常见技术写法。"""
    compact = re.sub(r"[\s._-]+", "", value).casefold()
    if re.fullmatch(r"python3\d{0,2}", compact):
        return "Python"
    if re.fullmatch(r"java(?:8|11|17|21)", compact):
        return "Java"
    if re.fullmatch(r"(?:react|vue)\d{1,2}", compact):
        return "React" if compact.startswith("react") else "Vue"
    if re.fullmatch(r"ci/cd(?:pipelines?)?", compact):
        return "CI/CD"
    aliases = {
        "py": "Python",
        "python3": "Python",
        "python语言": "Python",
        "golang": "Go",
        "go语言": "Go",
        "cpp": "C++",
        "c++语言": "C++",
        "js": "JavaScript",
        "javascript": "JavaScript",
        "javascript语言": "JavaScript",
        "typescript": "TypeScript",
        "typescript语言": "TypeScript",
        "reactjs": "React",
        "react16": "React",
        "react17": "React",
        "react18": "React",
        "reactnative": "React Native",
        "vuejs": "Vue",
        "vue2": "Vue",
        "vue3": "Vue",
        "angularjs": "Angular",
        "nodejs": "Node.js",
        "nextjs": "Next.js",
        "sveltejs": "Svelte",
        "tailwindcss": "Tailwind CSS",
        "html5": "HTML5",
        "html": "HTML5",
        "css3": "CSS3",
        "css": "CSS3",
        "springboot": "Spring Boot",
        "springcloud": "Spring Cloud",
        "mybatis": "MyBatis",
        "django": "Django",
        "flask": "Flask",
        "expressjs": "Express",
        "mysql数据库": "MySQL",
        "mysql8": "MySQL",
        "mysql": "MySQL",
        "postgres": "PostgreSQL",
        "postgresql数据库": "PostgreSQL",
        "postgresql": "PostgreSQL",
        "sqlite3": "SQLite",
        "sqlite": "SQLite",
        "mongodb": "MongoDB",
        "mongo": "MongoDB",
        "rabbitmq": "RabbitMQ",
        "apachekafka": "Kafka",
        "kafka": "Kafka",
        "redis": "Redis",
        "elasticsearch": "Elasticsearch",
        "websocket": "WebSocket",
        "grpc": "gRPC",
        "k8s": "Kubernetes",
        "kubernetes": "Kubernetes",
        "vue": "Vue",
        "react": "React",
        "fastapi": "FastAPI",
        "pytorch": "PyTorch",
        "torch": "PyTorch",
        "tensorflow": "TensorFlow",
        "tf": "TensorFlow",
        "opencv": "OpenCV",
        "cv2": "OpenCV",
        "sklearn": "Scikit-learn",
        "scikitlearn": "Scikit-learn",
        "xgboost": "XGBoost",
        "机器学习": "机器学习",
        "深度学习": "深度学习",
        "自然语言处理": "自然语言处理",
        "nlp": "自然语言处理",
        "计算机视觉": "计算机视觉",
        "机器视觉": "计算机视觉",
        "cv": "计算机视觉",
        "大语言模型": "大模型",
        "大型语言模型": "大模型",
        "llm": "大模型",
        "检索增强生成": "RAG",
        "检索增强": "RAG",
        "rag": "RAG",
        "智能体": "Agent",
        "aigc": "AIGC",
        "生成式人工智能": "AIGC",
        "生成式ai": "AIGC",
        "docker": "Docker",
        "linux": "Linux",
        "git": "Git",
        "terraform": "Terraform",
        "microservices": "微服务",
        "微服务架构": "微服务",
        "distributedsystems": "分布式",
        "分布式系统": "分布式",
        "restapi": "RESTful",
        "restfulapi": "RESTful",
        "csharp": "C#",
        "dotnet": ".NET",
        "net": ".NET",
        "sql": "SQL",
        "cicd": "CI/CD",
        "ci/cd": "CI/CD",
        "ci/cdpipelines": "CI/CD",
        "devops": "DevOps",
    }
    return aliases.get(compact, value.strip())


def _skill_name_and_level(token: str, inherited_level: str = "") -> tuple[str, str]:
    """支持括号、前后缀和破折号等技能等级表述。"""
    clean = token.strip().strip("-—–－:：")
    clean = re.sub(r"\s*等(?:编程语言|开发语言|技术|工具|框架)?$", "", clean).strip()
    if not clean:
        return "", ""

    bracketed = re.match(r"^(?P<name>.+?)[（(]\s*(?P<level>[^()（）]+?)\s*[）)]$", clean)
    if bracketed and _SKILL_LEVEL_RE.fullmatch(bracketed.group("level").strip()):
        return _normalize_skill_name(bracketed.group("name")), bracketed.group("level").strip()

    trailing = re.match(
        r"^(?P<name>.+?)\s*(?:[-—–－:：]|\s+)\s*(?P<level>熟练掌握|熟练使用|熟练|精通|掌握|熟悉|了解|入门|精通使用|proficient|advanced|intermediate|beginner|basic)$",
        clean,
        re.IGNORECASE,
    )
    if trailing:
        return _normalize_skill_name(trailing.group("name")), trailing.group("level")

    leading = _SKILL_LEADING_LEVEL_RE.match(clean)
    if leading:
        return _normalize_skill_name(leading.group("skills")), leading.group("level")
    return _normalize_skill_name(clean), inherited_level


def _parse_education(lines: list[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for block in _split_entry_blocks(lines, "education"):
        parts, start, end = _parse_header(block[0])
        compact = _compact_header_fields(block[0], "education")
        details, _highlights, _tech, courses, achievements, gpa = _detail_groups(
            [line for line in block[1:] if not _is_header_metadata_line(line)]
        )
        school = (
            _block_labeled_value(block, "school")
            or compact.get("school", "")
            or (parts[0] if parts else "")
        )
        major = (
            _block_labeled_value(block, "major")
            or compact.get("major", "")
            or (parts[1] if len(parts) > 1 else "")
        )
        degree = (
            _block_labeled_value(block, "degree")
            or compact.get("degree", "")
            or next(
                (
                    part
                    for part in parts
                    if any(term.casefold() in part.casefold() for term in _DEGREE_TERMS)
                ),
                "",
            )
        )
        start, end = _find_date_range(
            block, compact.get("start_date", start), compact.get("end_date", end)
        )
        if not achievements and details:
            achievements = "\n".join(details)
        if school or major or degree or details:
            result.append(
                {
                    "school": school,
                    "major": major,
                    "degree": degree,
                    "start_date": start,
                    "end_date": end,
                    "gpa": gpa,
                    "courses": courses,
                    "achievements": achievements,
                    "reference_file_name": "",
                    "reference_content": "",
                }
            )
    return result


def _parse_experience(lines: list[str], campus: bool = False) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for block in _split_entry_blocks(lines, "campus" if campus else "experience"):
        parts, start, end = _parse_header(block[0])
        compact = _compact_header_fields(block[0], "experience")
        labeled_first = _block_labeled_value(block, "organization" if campus else "company")
        labeled_role = _block_labeled_value(block, "role")
        inferred_first = inferred_role = ""
        inferred_start = inferred_end = ""
        inferred_details: list[str] | None = None
        if (
            len(parts) <= 1
            and not labeled_first
            and not compact.get("first")
            and not labeled_role
            and not compact.get("role")
        ):
            (
                inferred_first,
                inferred_role,
                inferred_start,
                inferred_end,
                inferred_details,
            ) = _infer_unlabeled_header(block)
        detail_lines = (
            inferred_details
            if inferred_details is not None
            else [line for line in block[1:] if not _is_header_metadata_line(line)]
        )
        description, _highlights, _tech, _courses, _achievements, _gpa = _detail_groups(
            detail_lines
        )
        start, end = _find_date_range(
            block, compact.get("start_date", start), compact.get("end_date", end)
        )
        first = labeled_first or compact.get("first", "") or inferred_first
        first = first or (parts[0] if parts else "")
        role = labeled_role or compact.get("role", "") or inferred_role
        role = role or (parts[1] if len(parts) > 1 else "")
        if inferred_start and not start:
            start = inferred_start
        if inferred_end and not end:
            end = inferred_end
        if first or role or description:
            item = {
                "role": role,
                "start_date": start,
                "end_date": end,
                "description": "\n".join(description),
                "reference_file_name": "",
                "reference_content": "",
            }
            item["organization" if campus else "company"] = first
            result.append(item)
    return result


def _parse_projects(lines: list[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for block in _split_entry_blocks(lines, "project"):
        parts, start, end = _parse_header(block[0])
        compact = _compact_header_fields(block[0], "project")
        labeled_name = _block_labeled_value(block, "project")
        labeled_role = _block_labeled_value(block, "role")
        inferred_name = inferred_role = ""
        inferred_start = inferred_end = ""
        inferred_details: list[str] | None = None
        if (
            len(parts) <= 1
            and not labeled_name
            and not compact.get("first")
            and not labeled_role
            and not compact.get("role")
        ):
            (
                inferred_name,
                inferred_role,
                inferred_start,
                inferred_end,
                inferred_details,
            ) = _infer_unlabeled_header(block)
        detail_lines = (
            inferred_details
            if inferred_details is not None
            else [line for line in block[1:] if not _is_header_metadata_line(line)]
        )
        description, highlights, tech_stack, _courses, _achievements, _gpa = _detail_groups(
            detail_lines
        )
        start, end = _find_date_range(
            block, compact.get("start_date", start), compact.get("end_date", end)
        )
        name = (
            labeled_name or compact.get("first", "") or inferred_name or (parts[0] if parts else "")
        )
        role = (
            labeled_role
            or compact.get("role", "")
            or inferred_role
            or (parts[1] if len(parts) > 1 else "")
        )
        if inferred_start and not start:
            start = inferred_start
        if inferred_end and not end:
            end = inferred_end
        if name or role or description or highlights:
            result.append(
                {
                    "name": name,
                    "role": role,
                    "start_date": start,
                    "end_date": end,
                    "tech_stack": "、".join(tech_stack),
                    "description": "\n".join(description),
                    "highlights": "\n".join(highlights),
                    "reference_file_name": "",
                    "reference_content": "",
                }
            )
    return result


def _parse_skills(lines: list[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    indices_by_name: dict[str, int] = {}
    for line in lines:
        clean = _clean_line(line)
        if not clean:
            continue
        label_match = re.match(r"^([^：:]{1,32})\s*[:：]\s*(.+)$", clean)
        label_key = label_match.group(1).casefold() if label_match else ""
        if label_match and any(
            term.casefold() in label_key
            for term in (
                "技能",
                "技术",
                "语言",
                "工具",
                "框架",
                "数据库",
                "中间件",
                "前端",
                "后端",
                "云原生",
                "人工智能",
                "机器学习",
                "自然语言",
                "计算机视觉",
                "大模型",
                "certification",
                "certifications",
                "technical",
                "tech",
                "technology",
                "expertise",
                "proficiencies",
                "programming",
                "language",
                "languages",
                "database",
                "framework",
                "frontend",
                "backend",
                "cloud",
                "tools",
            )
        ):
            clean = label_match.group(2)
        inherited_level = ""
        leading_level = _SKILL_LEADING_LEVEL_RE.match(clean)
        if leading_level:
            inherited_level = leading_level.group("level")
            clean = leading_level.group("skills")
        for token in _split_tokens(clean):
            name, level = _skill_name_and_level(token, inherited_level)
            key = name.casefold()
            if not name or len(name) > 64:
                continue
            existing_index = indices_by_name.get(key)
            if existing_index is None:
                indices_by_name[key] = len(result)
                result.append({"name": name, "level": level})
            elif level and not result[existing_index]["level"]:
                # 同一技能在“技能清单”和“熟练程度”两处都出现时，保留更完整的等级。
                result[existing_index]["level"] = level
    return result


def _parse_awards(lines: list[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for block in _split_entry_blocks(lines, "award"):
        clean = " ".join(_clean_line(line) for line in block if line).strip()
        if not clean:
            continue
        date_match = _DATE_RE.search(clean)
        date = date_match.group(0) if date_match else ""
        header = _DATE_RE.sub("", clean, count=1).strip(" -—–|｜丨·") if date else clean
        parts, _start, _end = _parse_header(header)
        name = parts[0] if parts else header
        description = "、".join(parts[1:]) if len(parts) > 1 else ""
        result.append({"name": name, "date": date, "description": description})
    return result


_PARSED_BASIC_FIELD_LIMITS = {
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
}
_PARSED_ENTRY_FIELD_LIMITS = {
    "educations": {
        "reference_file_name": 255,
        "reference_content": 200_000,
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
        "reference_file_name": 255,
        "reference_content": 200_000,
        "company": 128,
        "role": 128,
        "start_date": 32,
        "end_date": 32,
        "description": 200_000,
    },
    "campus_experiences": {
        "reference_file_name": 255,
        "reference_content": 200_000,
        "organization": 128,
        "role": 128,
        "start_date": 32,
        "end_date": 32,
        "description": 200_000,
    },
    "projects": {
        "reference_file_name": 255,
        "reference_content": 200_000,
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
_MAX_PARSED_SECTION_ITEMS = 200


def _bound_parse_result(
    basic: dict[str, str],
    summary: str,
    sections: dict[str, list[dict[str, str]]],
) -> tuple[dict[str, str], str, dict[str, list[dict[str, str]]], bool]:
    """让不可信粘贴文本始终符合可保存 Schema 的长度与数量边界。"""
    truncated = False

    def bounded(value: str, limit: int) -> str:
        nonlocal truncated
        if len(value) > limit:
            truncated = True
            return value[:limit]
        return value

    safe_basic = {
        field: bounded(str(value or ""), limit)
        for field, limit in _PARSED_BASIC_FIELD_LIMITS.items()
        for value in [basic.get(field, "")]
    }
    safe_sections: dict[str, list[dict[str, str]]] = {}
    for section, limits in _PARSED_ENTRY_FIELD_LIMITS.items():
        entries = sections[section]
        if len(entries) > _MAX_PARSED_SECTION_ITEMS:
            truncated = True
        safe_sections[section] = [
            {
                field: bounded(str(entry.get(field, "") or ""), limit)
                for field, limit in limits.items()
            }
            for entry in entries[:_MAX_PARSED_SECTION_ITEMS]
        ]
    return safe_basic, bounded(summary, 200_000), safe_sections, truncated


def parse_profile_text(text: str) -> ProfileTextParseResult:
    """解析一段个人资料，返回可直接回填表单的结构化草稿。"""
    lines = _normalize_lines(text or "")
    sections = _split_sections(lines)
    basic = _extract_basic(lines)
    summary_lines = [_clean_line(line) for line in sections["summary"] if line]
    summary = "\n".join(summary_lines).strip()
    parsed_sections = {
        "educations": _parse_education(sections["educations"]),
        "experiences": _parse_experience(sections["experiences"]),
        "campus_experiences": _parse_experience(sections["campus_experiences"], campus=True),
        "projects": _parse_projects(sections["projects"]),
        "skills": _parse_skills(sections["skills"]),
        "awards": _parse_awards(sections["awards"]),
    }
    basic, summary, parsed_sections, was_truncated = _bound_parse_result(
        basic, summary, parsed_sections
    )
    result = ProfileTextParseResult(
        **basic,
        summary=summary,
        **parsed_sections,
    )
    warnings: list[str] = []
    if not result.name:
        warnings.append("未识别到姓名，请手动填写。")
    if not any(
        (
            result.educations,
            result.experiences,
            result.campus_experiences,
            result.projects,
            result.skills,
            result.awards,
            result.summary,
        )
    ):
        warnings.append("未识别到教育、经历、项目、技能或总结分区，请核对标题格式。")
    if was_truncated:
        warnings.append("部分识别字段超过可保存长度，已截断，请核对。")
    result.warnings = warnings
    return result
