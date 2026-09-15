"""岗位标题、公司、地点及其元数据候选识别。"""

import re

from .candidate_constants import (
    _COMPANY_TERMS,
    _ENGLISH_COMPANY_RE,
    _ENGLISH_TITLE_RE,
    _LOCATION_SUFFIX_RE,
    _LOCATION_TERMS,
    _NON_LOCATION_TERMS,
    _TITLE_NON_ROLE_PREFIX_RE,
    _TITLE_SENTENCE_PREFIXES,
    _TITLE_SENTENCE_PREFIX_RE,
    _TITLE_TERMS,
)
from .field_constants import _FIELD_LIMITS
from .normalization import _strip_inline_salary
from .section_constants import (
    _ADDITIONAL_HEADING_RE,
    _JOB_ID_RE,
    _SALARY_RE,
    _UPDATED_DATE_RE,
    _URL_RE,
)


def _prepare_title_candidate(value: str) -> tuple[str, str]:
    """清理标题行附带的 URL，并拆出明确分隔的地点前缀。"""
    candidate = _strip_inline_salary(_URL_RE.sub("", value)).strip()
    leading_location = ""
    prefix_match = re.match(
        r"^(?P<prefix>[^|丨｜\-—–]{1,64})\s*(?:[|丨｜—–]|-(?!\d))\s*(?P<remainder>.+)$",
        candidate,
    )
    if prefix_match:
        prefix = prefix_match.group("prefix").strip()
        if _looks_like_location(prefix):
            leading_location = prefix
            candidate = prefix_match.group("remainder").strip()
    return candidate, leading_location


def _looks_like_title(value: str) -> bool:
    candidate = value.strip()
    if not candidate or len(candidate) > 128 or candidate.startswith(_TITLE_SENTENCE_PREFIXES):
        return False
    if _TITLE_NON_ROLE_PREFIX_RE.match(candidate):
        return False
    if _TITLE_SENTENCE_PREFIX_RE.match(candidate):
        return False
    if re.match(r"^[（(]?\d+[、.)）]", candidate):
        return False
    return any(term in candidate for term in _TITLE_TERMS) or bool(
        _ENGLISH_TITLE_RE.search(candidate)
    )


def _looks_like_company(value: str) -> bool:
    return any(term in value for term in _COMPANY_TERMS) or bool(_ENGLISH_COMPANY_RE.search(value))


def _looks_like_company_candidate(value: str) -> bool:
    """判断标题相邻的一行是否可能是品牌/公司名。"""
    candidate = value.strip(" \t|｜·,，;；")
    if not candidate or len(candidate) > _FIELD_LIMITS["company"]:
        return False
    if _looks_like_title(candidate) or _looks_like_location(candidate):
        return False
    if (
        _JOB_ID_RE.match(candidate)
        or _UPDATED_DATE_RE.match(candidate)
        or _ADDITIONAL_HEADING_RE.match(candidate)
    ):
        return False
    if _TITLE_NON_ROLE_PREFIX_RE.match(candidate):
        return False
    if _SALARY_RE.fullmatch(candidate) or _URL_RE.fullmatch(candidate):
        return False
    if re.fullmatch(
        r"(?:正式|全职|兼职|实习|校招|社招|校园招聘|社会招聘|intern(?:ship)?|"
        r"full[- ]?time|part[- ]?time|campus|graduate program)",
        candidate,
        re.IGNORECASE,
    ):
        return False
    if re.search(r"[。！？!?]", candidate) or re.match(r"^[\d#*•·]+", candidate):
        return False
    # 没有公司后缀的短行可能只是“北京团队/研发部门”等岗位元信息；
    # 带“科技/有限公司”等明确公司信号的名称不受此过滤影响。
    if not _looks_like_company(candidate) and (
        any(
            term in candidate
            for term in ("团队", "部门", "研发", "客户端", "技术", "产品", "正式", "全职", "兼职")
        )
        or re.search(
            r"\b(?:team|department|division|business\s+unit|function)\b", candidate, re.IGNORECASE
        )
    ):
        return False
    # “研发 - 客户端”一类部门元信息不是公司名；真正的品牌名通常没有句末标点。
    if re.search(
        r"(?:岗位|职位|工作|招聘|职责|描述|要求|部门|团队|客户端|研发)\s*[-—–/]", candidate
    ):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", candidate))


def _looks_like_internship_marker(value: str) -> bool:
    """判断标题区的一行是否明确表示实习，避免正文偏好语句触发误判。"""
    candidate = value.strip()
    if not candidate:
        return False
    if re.fullmatch(
        r"(?:实习招聘|实习生|岗位实习|职位实习|实习岗位|"
        r"20\d{2}\s*届(?:暑期)?实习招聘|"
        r"intern(?:ship)?(?:\s+(?:program|recruitment|hiring|position|role))?)",
        candidate,
        re.IGNORECASE,
    ):
        return True
    return _looks_like_title(candidate) and bool(
        re.search(r"实习|\bintern(?:ship)?\b", candidate, re.IGNORECASE)
    )


def _split_title_company(value: str) -> tuple[str, str]:
    # 部分官网把“岗位名(职位编号)公司品牌”无分隔地拼接。含数字的括号编号
    # 是可靠边界；尾部仍需通过公司候选校验，避免拆坏普通括号说明。
    for code_match in re.finditer(
        r"[（(](?=[^（）()\s]{1,32}[)）])[^（）()\s]*\d[^（）()\s]*[)）]", value
    ):
        compact_title = value[: code_match.end()].strip()
        compact_company = value[code_match.end() :].strip(" \t|｜·,，;；/\\")
        if (
            compact_company
            and _looks_like_title(compact_title)
            and _looks_like_company_candidate(compact_company)
        ):
            return compact_title, compact_company

    # 招聘卡片常把公司、岗位、地点、薪资和类型压成一行。先按管道分段
    # 定位真正的岗位片段，避免把后续元信息一起写入 title。
    pipe_parts = [
        part.strip(" \t|｜·,，;；/\\")
        for part in re.split(r"\s*[|丨｜]\s*", value.strip())
        if part.strip(" \t|｜·,，;；/\\")
    ]
    if len(pipe_parts) >= 3:
        title_indices = [index for index, part in enumerate(pipe_parts) if _looks_like_title(part)]
        if len(title_indices) == 1:
            title_index = title_indices[0]
            title = pipe_parts[title_index]
            metadata_terms = ("正式", "全职", "兼职", "实习", "校招", "社招", "intern", "full-time")
            company_candidates = [
                part
                for index, part in enumerate(pipe_parts)
                if index != title_index
                and not re.fullmatch(
                    "|".join(re.escape(term) for term in metadata_terms), part, re.IGNORECASE
                )
                and (_looks_like_company(part) or _looks_like_company_candidate(part))
            ]
            if company_candidates:
                # 通常公司紧邻岗位；若卡片把公司放在岗位后，也能取到最近候选。
                company = min(
                    company_candidates, key=lambda part: abs(pipe_parts.index(part) - title_index)
                )
                return title, company
            return title, ""

    parts = re.split(
        r"\s+(?:[-—–|｜@])\s+|\s*[|丨｜]\s*",
        value.strip(),
        maxsplit=1,
    )
    if len(parts) != 2 and re.search(r"\s+[/／]\s+", value):
        slash_parts = re.split(r"\s+[/／]\s+", value.strip(), maxsplit=1)
        # Slash is common inside role names (``AI / ML``); only treat it as
        # a company separator when the left side has a company signal.
        if len(slash_parts) == 2 and _looks_like_company(slash_parts[0]):
            parts = slash_parts
    if len(parts) != 2:
        # 中文招聘卡片常把“公司-岗位”复制成无空格形式。只在连字符两侧
        # 至少有一侧包含中文时尝试拆分，避免把 ``AI-powered`` 这类英文岗位
        # 内部连字符误当成公司分隔符。
        parts = re.split(
            r"(?<=[\u4e00-\u9fff])[-—–](?=[\u4e00-\u9fffA-Za-z])|"
            r"(?<=[A-Za-z])[-—–](?=[\u4e00-\u9fff])",
            value.strip(),
            maxsplit=1,
        )
    if len(parts) != 2:
        parts = re.split(r"(?<=[A-Za-z])[-—–](?=[A-Za-z])", value.strip(), maxsplit=1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        return value.strip(), ""

    left, right = (part.strip(" \t|｜·,，;；/\\") for part in parts)
    # “公司 - 岗位”只在左侧具有明显公司特征时反转；品牌名和技术名都可能很短，
    # 因此右侧像岗位、左侧不像岗位时，也按“公司 - 岗位”处理。
    if _looks_like_title(right) and (_looks_like_company(left) or not _looks_like_title(left)):
        return right, left
    # 两侧都像岗位名时通常是岗位自身的英文/方向分隔（例如
    # ``Backend Engineer - Software Engineer``），不要把右侧误填为公司。
    if (
        _looks_like_title(left)
        and _looks_like_title(right)
        and not (_looks_like_company(left) or _looks_like_company(right))
    ):
        return value.strip(), ""
    return left, right


def _discard_location_as_company(value: str) -> str:
    """标题行中的地点片段不是公司名（例如“岗位 | 北京”）。"""
    if value and _looks_like_location(value) and not _looks_like_company(value):
        return ""
    return value


def _looks_like_location(value: str) -> bool:
    candidate = value.strip()
    if not candidate or len(candidate) > _FIELD_LIMITS["location"]:
        return False
    candidate_fold = candidate.casefold()
    if _looks_like_company(candidate):
        return False
    if any(term.casefold() in candidate_fold for term in _NON_LOCATION_TERMS):
        return False
    if not any(term.casefold() in candidate_fold for term in _LOCATION_TERMS) and not (
        _LOCATION_SUFFIX_RE.fullmatch(candidate)
    ):
        return False
    return not re.search(r"[。！？!?]", candidate)


def _extract_location_from_metadata(value: str) -> str:
    """从将地点、薪资放在同一行的招聘卡片中保留地点部分。"""
    without_salary = _SALARY_RE.sub("", _URL_RE.sub("", value))

    # ``北京-岗位名`` 的连字符既不是薪资区间，也不是地点内容；只在
    # 连字符左侧本身可独立识别为地点时使用该边界。
    prefix_match = re.match(
        r"^(?P<prefix>[^|丨｜\-—–]{1,64})\s*(?:[|丨｜—–]|-(?!\d))\s*(?P<remainder>.+)$",
        without_salary,
    )
    if prefix_match:
        prefix = prefix_match.group("prefix").strip()
        if _looks_like_location(prefix):
            return prefix

    without_salary = re.sub(
        r"(?:正式|正式员工|全职|兼职|长期|实习|校招|社招|intern(?:ship)?|full[- ]?time|"
        r"part[- ]?time|permanent|contract|"
        r"campus\s+(?:recruitment|hiring)|graduate\s+program)",
        "|",
        without_salary,
        flags=re.IGNORECASE,
    )
    without_salary = without_salary.strip(" \t|｜·,，;；/\\")
    parts = []
    for part in re.split(r"[|｜·;；/\\]+|\s{2,}", without_salary):
        candidate = part.strip(" \t,，")
        if _looks_like_location(candidate):
            parts.append(candidate)
    if parts:
        return "、".join(dict.fromkeys(parts))
    if _looks_like_location(without_salary):
        return without_salary
    return ""

