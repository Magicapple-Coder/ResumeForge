"""将用户粘贴的个人资料拆成可编辑草稿。

解析器只使用本地规则，不调用网络或大模型。它优先识别明确的分区标题和字段标签，
无法确定的内容保留在对应经历的描述中，最终仍由用户在资料页核对后保存。
"""
import re

from ..schemas.profile import ProfileTextParseResult


_SECTION_ALIASES = {
    "educations": ("教育经历", "教育背景", "学历经历", "学习经历"),
    "experiences": ("实习经历", "工作经历", "实习/工作经历", "工作/实习经历", "工作经验", "职业经历"),
    "campus_experiences": ("校园经历", "学生工作", "社团经历", "校内经历"),
    "projects": ("项目经历", "项目经验", "项目实践"),
    "skills": ("专业技能", "技能清单", "技能", "技术栈"),
    "awards": ("荣誉奖项", "获奖情况", "奖项", "荣誉"),
    "summary": ("个人总结", "自我评价", "个人总结/自我评价", "个人总结 / 自我评价", "个人简介", "个人概述"),
}

_BASIC_LABELS = {
    "name": ("姓名", "名字"),
    "gender": ("性别"),
    "birth_year": ("出生年份", "出生年月", "出生日期"),
    "phone": ("手机号", "手机", "电话", "联系电话"),
    "email": ("邮箱", "电子邮箱", "Email", "E-mail"),
    "city": ("所在城市", "现居城市", "所在地", "现居地"),
    "target_city": ("意向城市", "目标城市"),
    "job_intent": ("求职意向", "目标职位", "应聘职位", "意向职位"),
    "personal_website": ("个人网站", "个人主页", "博客"),
    "github": ("GitHub", "Github", "github"),
}

_DATE_RANGE_RE = re.compile(
    r"(?P<start>\d{4}(?:[./年-]\d{1,2})?(?:[./月-]\d{1,2})?)\s*"
    r"(?:至|到|[-—–~～])\s*"
    r"(?P<end>\d{4}(?:[./年-]\d{1,2})?(?:[./月-]\d{1,2})?|至今|现在)",
)
_DATE_RE = re.compile(r"\d{4}(?:[./年-]\d{1,2})?(?:[./月-]\d{1,2})?")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*•·]|\d+[、.)）.]|[一二三四五六七八九十]+[、.)）.])\s*")
_ENTRY_SEPARATOR_RE = re.compile(r"\s*(?:\||｜|丨|·|•|—|–| - |至)\s*")


def _normalize_lines(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00a0", " ").replace("\u200b", "")
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


def _heading_key(line: str) -> str | None:
    candidate = _clean_line(line).rstrip("：:").strip()
    compact = re.sub(r"[\s（）()【】\[\]]", "", candidate)
    for key, aliases in _SECTION_ALIASES.items():
        if compact in {re.sub(r"[\s（）()【】\[\]]", "", alias) for alias in aliases}:
            return key
    return None


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {key: [] for key in _SECTION_ALIASES}
    current: str | None = None
    for line in lines:
        key = _heading_key(line)
        if key is not None:
            current = key
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _label_value(line: str, labels: tuple[str, ...]) -> str:
    alternatives = "|".join(re.escape(label) for label in labels)
    match = re.match(
        rf"^(?:{alternatives})(?:\s*[:：]\s*|\s+)(?P<value>.+?)\s*$",
        line,
        re.IGNORECASE,
    )
    return match.group("value").strip() if match else ""


def _extract_basic(lines: list[str]) -> dict[str, str]:
    values = {field: "" for field in _BASIC_LABELS}
    for line in lines:
        for field, labels in _BASIC_LABELS.items():
            value = _label_value(line, labels)
            if value and not values[field]:
                values[field] = value

    full_text = "\n".join(lines)
    if not values["phone"]:
        match = _PHONE_RE.search(full_text)
        values["phone"] = match.group(0) if match else ""
    if not values["email"]:
        match = _EMAIL_RE.search(full_text)
        values["email"] = match.group(0) if match else ""
    if not values["github"]:
        match = re.search(r"https?://(?:www\.)?github\.com/[^\s<>\"']+", full_text, re.IGNORECASE)
        values["github"] = match.group(0).rstrip(".,;，。；") if match else ""
    if not values["personal_website"]:
        urls = _URL_RE.findall(full_text)
        values["personal_website"] = next(
            (url.rstrip(".,;，。；") for url in urls if "github.com" not in url.lower()), ""
        )
    return values


def _split_entry_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                blocks.append(current)
                current = []
            continue
        if current and _looks_like_entry_header(line):
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _looks_like_entry_header(line: str) -> bool:
    clean = _clean_line(line)
    if not clean or len(clean) > 180:
        return False
    if _DATE_RANGE_RE.search(clean) or _ENTRY_SEPARATOR_RE.search(clean):
        return True
    return bool(re.match(r"^(?:学校|公司|组织|项目名称|项目|单位)\s*[:：]", clean))


def _parse_header(line: str) -> tuple[list[str], str, str]:
    clean = _clean_line(line)
    date_match = _DATE_RANGE_RE.search(clean)
    start_date = date_match.group("start") if date_match else ""
    end_date = date_match.group("end") if date_match else ""
    if date_match:
        clean = (clean[: date_match.start()] + clean[date_match.end() :]).strip(" -—–|｜丨·")
    parts = [part.strip() for part in _ENTRY_SEPARATOR_RE.split(clean) if part.strip()]
    if len(parts) == 1:
        parts = [part.strip() for part in re.split(r"\s{2,}|\t+", clean) if part.strip()]
    return parts, start_date, end_date


def _find_date_range(lines: list[str], start: str, end: str) -> tuple[str, str]:
    if start or end:
        return start, end
    match = _DATE_RANGE_RE.search(" ".join(lines))
    return (match.group("start"), match.group("end")) if match else ("", "")


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
        match = re.match(r"^([^：:]{1,12})\s*[:：]\s*(.+)$", line)
        if match:
            label = match.group(1).strip().lower()
            value = match.group(2).strip()
            if any(term in label for term in ("技术栈", "技术", "工具")):
                tech_stack.extend(_split_tokens(value))
                continue
            if any(term in label for term in ("亮点", "成果", "结果", "业绩")):
                active = highlights
                highlights.append(value)
                continue
            if any(term in label for term in ("课程", "核心课")):
                courses.extend(_split_tokens(value))
                continue
            if any(term in label for term in ("绩点", "排名", "成绩")):
                gpa = value
                continue
            if any(term in label for term in ("奖项", "荣誉")):
                achievements.append(value)
                continue
            if any(term in label for term in ("描述", "职责", "工作内容", "项目内容")):
                active = description
                description.append(value)
                continue
        active.append(line)
    return description, highlights, tech_stack, "、".join(courses), "\n".join(achievements), gpa


def _split_tokens(value: str) -> list[str]:
    return [token.strip() for token in re.split(r"[,，、/|｜;；]+", value) if token.strip()]


def _parse_education(lines: list[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for block in _split_entry_blocks(lines):
        parts, start, end = _parse_header(block[0])
        details, _highlights, _tech, courses, achievements, gpa = _detail_groups(block[1:])
        school = _label_value(block[0], ("学校", "院校")) or (parts[0] if parts else "")
        major = _label_value(block[0], ("专业", "所学专业")) or (parts[1] if len(parts) > 1 else "")
        degree = _label_value(block[0], ("学历", "学位")) or next(
            (part for part in parts if any(term in part for term in ("本科", "硕士", "博士", "专科"))), ""
        )
        start, end = _find_date_range(block, start, end)
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
    for block in _split_entry_blocks(lines):
        parts, start, end = _parse_header(block[0])
        description, _highlights, _tech, _courses, _achievements, _gpa = _detail_groups(block[1:])
        start, end = _find_date_range(block, start, end)
        first = _label_value(block[0], ("组织", "组织/部门")) if campus else _label_value(block[0], ("公司", "单位"))
        first = first or (parts[0] if parts else "")
        role = _label_value(block[0], ("职务", "角色")) if campus else _label_value(block[0], ("职位", "岗位", "角色"))
        role = role or (parts[1] if len(parts) > 1 else "")
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
    for block in _split_entry_blocks(lines):
        parts, start, end = _parse_header(block[0])
        description, highlights, tech_stack, _courses, _achievements, _gpa = _detail_groups(block[1:])
        start, end = _find_date_range(block, start, end)
        name = _label_value(block[0], ("项目", "项目名称")) or (parts[0] if parts else "")
        role = _label_value(block[0], ("角色", "担任角色")) or (parts[1] if len(parts) > 1 else "")
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
    for line in lines:
        clean = _clean_line(line)
        if not clean:
            continue
        label_match = re.match(r"^([^：:]{1,32})\s*[:：]\s*(.+)$", clean)
        if label_match and any(term in label_match.group(1) for term in ("技能", "技术", "语言", "工具")):
            clean = label_match.group(2)
        for token in _split_tokens(clean):
            level = ""
            level_match = re.match(r"(.+?)[（(](熟练|掌握|了解|精通)[）)]$", token)
            if level_match:
                token, level = level_match.groups()
            if token and len(token) <= 64:
                result.append({"name": token.strip(), "level": level})
    return result


def _parse_awards(lines: list[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for block in _split_entry_blocks(lines):
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


def parse_profile_text(text: str) -> ProfileTextParseResult:
    """解析一段个人资料，返回可直接回填表单的结构化草稿。"""
    lines = _normalize_lines(text or "")
    sections = _split_sections(lines)
    basic = _extract_basic(lines)
    summary_lines = [_clean_line(line) for line in sections["summary"] if line]
    summary = "\n".join(summary_lines).strip()
    result = ProfileTextParseResult(
        **basic,
        summary=summary,
        educations=_parse_education(sections["educations"]),
        experiences=_parse_experience(sections["experiences"]),
        campus_experiences=_parse_experience(sections["campus_experiences"], campus=True),
        projects=_parse_projects(sections["projects"]),
        skills=_parse_skills(sections["skills"]),
        awards=_parse_awards(sections["awards"]),
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
    result.warnings = warnings
    return result
