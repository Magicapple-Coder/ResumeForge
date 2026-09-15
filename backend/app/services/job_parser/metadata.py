"""招聘前置元数据、类型和发布时间识别。"""

import re

from .candidates import (
    _extract_location_from_metadata,
    _looks_like_internship_marker,
    _looks_like_title,
    _prepare_title_candidate,
)
from .normalization import _find_url, _strip_inline_salary
from .section_constants import (
    _BARE_DATE_RE,
    _JOB_ID_RE,
    _NON_PUBLISHED_DATE_CONTEXT_RE,
    _PUBLISHED_DATE_RE,
    _SALARY_RE,
    _UPDATED_DATE_RE,
)


def _looks_like_compact_recruitment_metadata(value: str) -> bool:
    """判断是否为官网压缩在一行的地点、类型、类别、人数和日期元数据。"""
    if not _extract_location_from_metadata(value):
        return False
    return bool(
        re.search(
            r"校招|社招|校园招聘|社会招聘|实习招聘|招聘人数|若干|"
            r"campus\s+(?:recruitment|hiring)|graduate\s+program|headcount|"
            r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}",
            value,
            re.IGNORECASE,
        )
    )


def _normalize_job_type(value: str) -> str:
    if re.search(r"实习|intern(?:ship)?", value, re.IGNORECASE):
        return "实习"
    if re.search(
        r"校园招聘|校招|应届|毕业生|20\d{2}\s*届|管培生|"
        r"campus\s+(?:recruitment|hiring|program)|graduate\s+(?:program|scheme|recruitment)|"
        r"new\s+grad(?:uate)?|entry[- ]level",
        value,
        re.IGNORECASE,
    ):
        return "校招"
    if re.search(
        r"社会招聘|社招|社会人才|experienced\s+hire|professional\s+hire",
        value,
        re.IGNORECASE,
    ):
        return "社招"
    return "其他"


def _normalize_status(value: str) -> str:
    if re.search(
        r"已关闭|停止招聘|招聘结束|已结束|已截止|职位失效|岗位失效|停止申请|"
        # 连字符技术术语（如 closed-loop）不代表岗位已关闭；限定英文词边界
        # 并排除紧随其后的连字符。
        r"(?<![A-Za-z])closed(?![A-Za-z-])|"
        r"(?<![A-Za-z])expired(?![A-Za-z])|"
        r"\bno\s+longer\s+accepting\b",
        value,
        re.IGNORECASE,
    ):
        return "已截止"
    return "开放中"


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
                # 标题和薪资经常位于同一行；只有剩余内容不像标题时才
                # 整行消费，否则后续标题提取会看不到岗位名。
                if len(line) <= 80 and not _looks_like_title(_strip_inline_salary(line)):
                    consumed.add(index)
        if "location" not in values:
            location = _extract_location_from_metadata(line)
            if not location:
                continue
            title_candidate, leading_title_location = _prepare_title_candidate(line)
            if leading_title_location and _looks_like_title(title_candidate):
                # 独立元数据行通常比标题里的“北京-岗位名”更具体。标题解析
                # 会在没有其他地点时再用该前缀兜底，因此这里先不占位。
                continue
            values["location"] = location
            # 同一行可能同时包含“岗位名 | 地点 | 薪资”；保留该行供标题
            # 提取逻辑处理。紧凑元数据行还包含类别、人数等无法可靠命名的
            # 信息，留给 additional_info 原样保存，不能在这里直接消费。
            if not _looks_like_title(_strip_inline_salary(line)) and not (
                _looks_like_compact_recruitment_metadata(line)
            ):
                consumed.add(index)


def _detect_job_type(lines: list[str], values: dict[str, str], preamble_end: int) -> str:
    labeled = values.get("job_type", "")
    if labeled:
        return _normalize_job_type(labeled)

    # 只看标题区和正文标题之前的元信息，避免“有实习经历者优先”把校招误判为实习。
    context = "\n".join(lines[:preamble_end])
    if any(_looks_like_internship_marker(line) for line in lines[:preamble_end]):
        return "实习"
    if re.search(
        r"校园招聘|校招|应届|毕业生|20\d{2}\s*届|管培生|"
        r"campus\s+(?:recruitment|hiring|program)|graduate\s+(?:program|scheme|recruitment)|"
        r"new\s+grad(?:uate)?|entry[- ]level",
        context,
        re.IGNORECASE,
    ):
        return "校招"
    if re.search(
        r"社会招聘|社招|社会人才|experienced\s+hire|professional\s+hire", context, re.IGNORECASE
    ):
        return "社招"
    return "其他"


def _mark_type_lines(lines: list[str], consumed: set[int], preamble_end: int) -> None:
    marker = re.compile(
        # 招聘计划标记已用于类型判断，无需再写入职责或补充信息。
        r"^(?:校园招聘|校招|社会招聘|社招|实习招聘|"
        r"20\d{2}\s*届(?:(?:暑期)?实习招聘|校园招聘|校招)?|"
        r"campus\s+(?:recruitment|hiring|program)|graduate\s+(?:program|scheme|recruitment)|"
        r"new\s+grad(?:uate)?|entry[- ]level|"
        r"intern(?:ship)?(?:\s+(?:program|recruitment|hiring))?)$",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines[:preamble_end]):
        if marker.match(line):
            consumed.add(index)


def _is_additional_preamble_line(line: str) -> bool:
    """识别标题区中应保留、但不属于岗位职责的招聘元信息。"""
    candidate = line.strip()
    if (
        _JOB_ID_RE.match(candidate)
        or _UPDATED_DATE_RE.match(candidate)
        or _looks_like_compact_recruitment_metadata(candidate)
    ):
        return True
    if re.fullmatch(
        r"(?:正式|正式员工|全职|兼职|长期|合同工|临时工|劳务派遣|"
        r"permanent|full[- ]?time|part[- ]?time|contract|temporary)",
        candidate,
        re.IGNORECASE,
    ):
        return True
    if re.match(
        r"^(?:所属)?(?:部门|团队|科室|业务线|事业部|职类|职位类别|岗位类别|"
        r"招聘人数|汇报对象|工作班次|工作时间|合同期限|department|team|division|"
        r"business\s+unit|reports?\s+to)\s*[:：]",
        candidate,
        re.IGNORECASE,
    ):
        return True
    return bool(
        re.fullmatch(
            r"[^。！？!?]{1,32}\s*[-—–/]\s*"
            r"(?:客户端|服务端|研发|生产|制造|销售|市场|运营|门店|科室|"
            r"client|server|engineering|production|sales|marketing|operations)",
            candidate,
            re.IGNORECASE,
        )
    )


def _extract_posted_at(lines: list[str], values: dict[str, str], preamble_end: int) -> str:
    if "posted_at" in values:
        return values["posted_at"]
    for line in lines:
        match = _PUBLISHED_DATE_RE.search(line)
        if match:
            return match.group("date")
    # 无标签日期只在职责正文之前、且带有招聘元数据的短行中可信。这样不会
    # 把正文中的项目年份或“截止/更新日期”误写成岗位发布时间。
    for line in lines[:preamble_end]:
        if _NON_PUBLISHED_DATE_CONTEXT_RE.search(line):
            continue
        match = _BARE_DATE_RE.search(line)
        if match and _looks_like_compact_recruitment_metadata(line):
            return match.group("date")
    return ""
