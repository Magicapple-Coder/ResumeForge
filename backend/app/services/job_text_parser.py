"""将招聘页面复制出的纯文本解析为可编辑的岗位草稿。

解析器刻意只使用本地、可解释的规则：识别不到的内容留空，交给用户在
创建岗位前确认。它不访问网络，也不直接写数据库。
"""
import re

from ..schemas.job import JobTextParseResult


_FIELD_LIMITS = {
    "title": 128,
    "company": 128,
    "location": 64,
    "salary": 64,
    "job_type": 32,
    "source_url": 512,
    "posted_at": 32,
    "status": 16,
}

_LABELS = {
    "title": ("职位名称", "岗位名称", "招聘职位", "招聘岗位", "职位标题", "岗位标题"),
    "company": ("公司名称", "企业名称", "招聘公司", "用人单位", "公司"),
    "location": ("工作地点", "工作地址", "办公地点", "职位地点", "岗位地点", "所在城市", "地点", "城市"),
    "salary": ("薪资范围", "薪资待遇", "薪酬范围", "工资待遇", "薪酬", "薪资", "月薪", "年薪"),
    "job_type": ("招聘类型", "职位类型", "岗位类型", "工作性质", "用工性质"),
    "source_url": (
        "投递链接",
        "申请链接",
        "职位链接",
        "岗位链接",
        "招聘链接",
        "官网链接",
        "网申地址",
        "链接",
        "URL",
    ),
    "posted_at": ("发布时间", "发布日期", "更新日期", "发布于"),
    "status": ("招聘状态", "职位状态", "岗位状态", "状态"),
}


def _compile_label_pattern(labels: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(label) for label in labels)
    # 没有冒号时要求标签和值之间有空白，避免把“公司介绍”等正文误当字段。
    return re.compile(rf"^(?:{alternatives})(?:\s*[:：]\s*|\s+)(?P<value>.+?)\s*$", re.IGNORECASE)


_LABEL_PATTERNS = {field: _compile_label_pattern(labels) for field, labels in _LABELS.items()}

_DESCRIPTION_HEADING_RE = re.compile(
    r"^(?:职位描述|岗位描述|工作描述|岗位职责|职位职责|工作职责|职责描述|工作内容|岗位内容)"
    r"(?:\s*[:：]\s*|\s+|$)(?P<content>.*)$"
)
_REQUIREMENTS_HEADING_RE = re.compile(
    r"^(?:职位要求|岗位要求|任职要求|任职资格|岗位资格|职位资格|任职条件|岗位条件|招聘要求|能力要求)"
    r"(?:\s*[:：]\s*|\s+|$)(?P<content>.*)$"
)
_INLINE_SECTION_RE = re.compile(
    r"(?:^|(?<=[。；;！？!?\s]))\s*"
    r"(?P<heading>职位描述|岗位描述|工作描述|岗位职责|职位职责|工作职责|职责描述|工作内容|岗位内容|"
    r"职位要求|岗位要求|任职要求|任职资格|岗位资格|职位资格|任职条件|岗位条件|招聘要求|能力要求)"
    r"\s*[:：]\s*"
)
_OTHER_SECTION_RE = re.compile(
    r"^(?:福利待遇|薪资福利|公司介绍|企业介绍|关于我们|联系方式|投递方式|申请方式|招聘流程)\s*[:：]?\s*$"
)

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_JOB_ID_RE = re.compile(
    r"^(?:(?:职位|岗位|Job|Position)\s*(?:ID|编号|编码)|Req(?:uisition)?\s*ID)\s*[:：#]?\s*\S+",
    re.IGNORECASE,
)
_SALARY_RE = re.compile(
    r"(?:[￥¥]\s*)?\d+(?:\.\d+)?\s*(?:[kKwW万千元])?\s*"
    r"(?:-|~|～|—|–|至)\s*(?:[￥¥]\s*)?\d+(?:\.\d+)?\s*(?:[kKwW万千元])"
    r"(?:\s*/\s*(?:月|年|天|日|小时))?(?:\s*[·xX*]\s*\d{1,2}\s*薪)?"
)
_PUBLISHED_DATE_RE = re.compile(
    r"(?:发布于|发布时间\s*[:：]?)\s*"
    r"(?P<date>\d{4}(?:[./年-]\d{1,2})?(?:[./月-]\d{1,2}日?)?)"
)

_TITLE_TERMS = (
    "工程师",
    "开发",
    "算法",
    "研究员",
    "架构师",
    "设计师",
    "分析师",
    "产品经理",
    "项目经理",
    "运营",
    "测试",
    "研发",
    "顾问",
    "专员",
    "管培生",
    "实习生",
    "科学家",
    "助理",
)
_TITLE_SENTENCE_PREFIXES = ("负责", "参与", "熟悉", "掌握", "具备", "要求", "我们", "团队", "协助", "能够", "拥有")
_COMPANY_TERMS = ("公司", "集团", "银行", "研究院", "事务所", "有限公司", "股份", "科技", "网络", "智能")
_LOCATION_TERMS = (
    "北京",
    "上海",
    "天津",
    "重庆",
    "深圳",
    "广州",
    "杭州",
    "成都",
    "武汉",
    "西安",
    "南京",
    "苏州",
    "长沙",
    "厦门",
    "合肥",
    "郑州",
    "青岛",
    "济南",
    "大连",
    "宁波",
    "东莞",
    "佛山",
    "珠海",
    "无锡",
    "福州",
    "昆明",
    "南昌",
    "沈阳",
    "石家庄",
    "哈尔滨",
    "香港",
    "澳门",
    "台湾",
    "海外",
    "全国",
    "远程",
)
_NON_LOCATION_TERMS = ("负责", "要求", "经验", "学历", "招聘", "职位", "岗位", "工程师", "薪资")


def _normalize_lines(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00a0", " ").replace("\u200b", "")
    return [line.strip() for line in normalized.split("\n") if line.strip()]


def _truncate(value: str, field: str) -> str:
    return value.strip()[: _FIELD_LIMITS[field]]


def _find_url(value: str) -> str:
    match = _URL_RE.search(value)
    if match is None:
        return ""
    return match.group(0).rstrip(".,;:!?，。；：！？、)]}）】」』")


def _looks_like_title(value: str) -> bool:
    candidate = value.strip()
    if not candidate or len(candidate) > 128 or candidate.startswith(_TITLE_SENTENCE_PREFIXES):
        return False
    if re.match(r"^[（(]?\d+[、.)）]", candidate):
        return False
    return any(term in candidate for term in _TITLE_TERMS)


def _looks_like_company(value: str) -> bool:
    return any(term in value for term in _COMPANY_TERMS)


def _split_title_company(value: str) -> tuple[str, str]:
    parts = re.split(r"\s+(?:[-—–|｜@])\s+|\s*[丨｜]\s*", value.strip(), maxsplit=1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        return value.strip(), ""

    left, right = (part.strip() for part in parts)
    # “公司 - 岗位”只在左侧具有明显公司特征时反转；品牌名和技术名都可能很短，
    # 因此右侧像岗位、左侧不像岗位时，也按“公司 - 岗位”处理。
    if _looks_like_title(right) and (_looks_like_company(left) or not _looks_like_title(left)):
        return right, left
    return left, right


def _looks_like_location(value: str) -> bool:
    candidate = value.strip()
    if not candidate or len(candidate) > _FIELD_LIMITS["location"]:
        return False
    if any(term in candidate for term in _NON_LOCATION_TERMS):
        return False
    if not any(term in candidate for term in _LOCATION_TERMS):
        return False
    return not re.search(r"[。！？!?]", candidate)


def _normalize_job_type(value: str) -> str:
    if re.search(r"实习|intern", value, re.IGNORECASE):
        return "实习"
    if re.search(r"校园招聘|校招|应届|毕业生|20\d{2}\s*届|管培生", value, re.IGNORECASE):
        return "校招"
    if re.search(r"社会招聘|社招|社会人才", value, re.IGNORECASE):
        return "社招"
    return "其他"


def _normalize_status(value: str) -> str:
    if re.search(r"已关闭|停止招聘|招聘结束|已结束|已截止|职位失效|岗位失效|停止申请", value):
        return "已截止"
    return "开放中"


def _extract_labeled_fields(lines: list[str]) -> tuple[dict[str, str], set[int]]:
    values: dict[str, str] = {}
    consumed: set[int] = set()
    for index, line in enumerate(lines):
        for field, pattern in _LABEL_PATTERNS.items():
            match = pattern.match(line)
            if match is None:
                continue
            consumed.add(index)
            if field not in values:
                values[field] = match.group("value").strip()
            break
    return values, consumed


def _first_section_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if _DESCRIPTION_HEADING_RE.match(line) or _REQUIREMENTS_HEADING_RE.match(line):
            return index
    return len(lines)


def _mark_unlabeled_metadata(
    lines: list[str], values: dict[str, str], consumed: set[int], preamble_end: int
) -> None:
    for index, line in enumerate(lines[:preamble_end]):
        if index in consumed:
            continue
        if "source_url" not in values:
            url = _find_url(line)
            if url:
                values["source_url"] = url
                if url == line:
                    consumed.add(index)
                continue
        if "salary" not in values:
            salary_match = _SALARY_RE.search(line)
            if salary_match:
                values["salary"] = salary_match.group(0)
                if len(line) <= 80:
                    consumed.add(index)
                continue
        if "location" not in values and _looks_like_location(line):
            values["location"] = line
            consumed.add(index)


def _extract_title_and_company(
    lines: list[str], values: dict[str, str], consumed: set[int], preamble_end: int
) -> tuple[str, str]:
    title_value = values.get("title", "")
    company = values.get("company", "")
    if title_value:
        title, inline_company = _split_title_company(title_value)
        return title, company or inline_company

    for index, line in enumerate(lines[:preamble_end]):
        if index in consumed or _JOB_ID_RE.match(line) or _OTHER_SECTION_RE.match(line):
            continue
        if _looks_like_title(line):
            consumed.add(index)
            title, inline_company = _split_title_company(line)
            return title, company or inline_company
    return "", company


def _detect_job_type(lines: list[str], values: dict[str, str], preamble_end: int) -> str:
    labeled = values.get("job_type", "")
    if labeled:
        return _normalize_job_type(labeled)

    # 只看标题区和正文标题之前的元信息，避免“有实习经历者优先”把校招误判为实习。
    context = "\n".join(lines[:preamble_end])
    if re.search(r"(?:^|\n).*?(?:实习招聘|实习生|岗位实习|职位实习)(?:$|\n)", context, re.IGNORECASE):
        return "实习"
    if re.search(r"校园招聘|校招|应届|毕业生|20\d{2}\s*届|管培生", context, re.IGNORECASE):
        return "校招"
    if re.search(r"社会招聘|社招|社会人才", context, re.IGNORECASE):
        return "社招"
    return "其他"


def _mark_type_lines(lines: list[str], consumed: set[int], preamble_end: int) -> None:
    marker = re.compile(
        r"^(?:校园招聘|校招|社会招聘|社招|实习招聘|"
        r"20\d{2}\s*届(?:(?:暑期)?实习招聘|校园招聘|校招)?)$",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines[:preamble_end]):
        if marker.match(line):
            consumed.add(index)


def _extract_sections(lines: list[str], consumed: set[int]) -> tuple[str, str, set[int], bool]:
    description_lines: list[str] = []
    requirement_lines: list[str] = []
    section_indices: set[int] = set()
    current_section = ""
    saw_description_heading = False

    for index, line in enumerate(lines):
        inline_matches = list(_INLINE_SECTION_RE.finditer(line))
        if inline_matches:
            section_indices.add(index)
            for match_index, match in enumerate(inline_matches):
                heading = match.group("heading")
                current_section = (
                    "description" if _DESCRIPTION_HEADING_RE.match(heading) else "requirements"
                )
                if current_section == "description":
                    saw_description_heading = True
                content_end = (
                    inline_matches[match_index + 1].start()
                    if match_index + 1 < len(inline_matches)
                    else len(line)
                )
                content = line[match.end() : content_end].strip()
                if not content:
                    continue
                if current_section == "description":
                    description_lines.append(content)
                else:
                    requirement_lines.append(content)
            continue

        description_match = _DESCRIPTION_HEADING_RE.match(line)
        if description_match:
            current_section = "description"
            saw_description_heading = True
            section_indices.add(index)
            content = description_match.group("content").strip()
            if content:
                description_lines.append(content)
            continue

        requirements_match = _REQUIREMENTS_HEADING_RE.match(line)
        if requirements_match:
            current_section = "requirements"
            section_indices.add(index)
            content = requirements_match.group("content").strip()
            if content:
                requirement_lines.append(content)
            continue

        if _OTHER_SECTION_RE.match(line):
            current_section = ""
            section_indices.add(index)
            continue

        if current_section:
            section_indices.add(index)
            if index in consumed:
                continue
            if current_section == "description":
                description_lines.append(line)
            else:
                requirement_lines.append(line)

    return "\n".join(description_lines), "\n".join(requirement_lines), section_indices, saw_description_heading


def _extract_posted_at(lines: list[str], values: dict[str, str]) -> str:
    if "posted_at" in values:
        return values["posted_at"]
    for line in lines:
        match = _PUBLISHED_DATE_RE.search(line)
        if match:
            return match.group("date")
    return ""


def parse_job_text(text: str) -> JobTextParseResult:
    """解析一段招聘文本并返回岗位草稿；不会调用网络或修改数据库。"""
    lines = _normalize_lines(text or "")
    values, consumed = _extract_labeled_fields(lines)
    preamble_end = _first_section_index(lines)

    _mark_unlabeled_metadata(lines, values, consumed, preamble_end)
    title, company = _extract_title_and_company(lines, values, consumed, preamble_end)
    job_type = _detect_job_type(lines, values, preamble_end)
    _mark_type_lines(lines, consumed, preamble_end)

    description, requirements, section_indices, saw_description_heading = _extract_sections(lines, consumed)
    section_description = description.strip()

    if not saw_description_heading:
        fallback_lines = [
            line
            for index, line in enumerate(lines)
            if index not in consumed
            and index not in section_indices
            and not _OTHER_SECTION_RE.match(line)
        ]
        description = "\n".join(fallback_lines)
    else:
        # 招聘网站常把职位 ID、用工性质、部门等元信息放在正文标题之前。
        # 数据库没有对应字段，因此按原顺序并入描述，避免粘贴后信息无声丢失。
        preamble_metadata = [
            line
            for index, line in enumerate(lines[:preamble_end])
            if index not in consumed and not _OTHER_SECTION_RE.match(line)
        ]
        description = "\n".join(preamble_metadata + ([description] if description else []))

    substantive_description = section_description if saw_description_heading else description.strip()
    warnings: list[str] = []
    if not title:
        warnings.append("未识别到岗位名称，请手动填写。")
    if not substantive_description:
        warnings.append("未识别到职位描述，请核对原始文本并手动填写。")

    source_url = _find_url(values.get("source_url", ""))
    status_context = values.get("status", "") or "\n".join(lines)

    return JobTextParseResult(
        title=_truncate(title, "title"),
        company=_truncate(company, "company"),
        location=_truncate(values.get("location", ""), "location"),
        salary=_truncate(values.get("salary", ""), "salary"),
        job_type=_truncate(job_type, "job_type"),
        description=description.strip(),
        requirements=requirements.strip(),
        source_url=_truncate(source_url, "source_url"),
        posted_at=_truncate(_extract_posted_at(lines, values), "posted_at"),
        status=_truncate(_normalize_status(status_context), "status"),
        warnings=warnings,
    )
