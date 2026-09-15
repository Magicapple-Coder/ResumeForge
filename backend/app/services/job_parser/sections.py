"""招聘职责、任职要求和其他信息的章节提取。"""

import re

from .normalization import _LABEL_PATTERNS, _inline_label_matches
from .section_constants import (
    _ADDITIONAL_HEADING_RE,
    _DESCRIPTION_HEADING_RE,
    _INLINE_SECTION_RE,
    _JOB_ID_RE,
    _REQUIREMENTS_HEADING_RE,
)


def _extract_labeled_fields(lines: list[str]) -> tuple[dict[str, str], set[int]]:
    values: dict[str, str] = {}
    consumed: set[int] = set()
    for index, line in enumerate(lines):
        # 章节标题可能以 ``Job Description:`` 这类形式出现；先让章节解析器
        # 处理，避免短英文字段别名（如 ``job``）把标题内容写进岗位名。
        if (
            _DESCRIPTION_HEADING_RE.match(line)
            or _REQUIREMENTS_HEADING_RE.match(line)
            or _ADDITIONAL_HEADING_RE.match(line)
            or _JOB_ID_RE.match(line)
        ):
            continue
        inline_matches = _inline_label_matches(line)
        if inline_matches:
            # 字段标签之后可能紧接“职位描述/任职要求”等章节标题；这些
            # 标题不是元数据字段，若不纳入边界，薪资/地点值会吞掉整段 JD。
            section_boundaries = [
                match.start() for match in _INLINE_SECTION_RE.finditer(line) if match.start() > 0
            ]
            for match_index, (start, end, field, _label) in enumerate(inline_matches):
                value_end = (
                    inline_matches[match_index + 1][0]
                    if match_index + 1 < len(inline_matches)
                    else len(line)
                )
                following_sections = [boundary for boundary in section_boundaries if boundary > end]
                if following_sections:
                    value_end = min(value_end, min(following_sections))
                value = line[end:value_end].strip(" \t:：|｜丨;,；,，")
                if value and field not in values:
                    values[field] = value
            consumed.add(index)
            continue
        for field, pattern in _LABEL_PATTERNS.items():
            match = pattern.match(line)
            if match is None:
                continue
            # “职位 ID：…”以“职位”开头，但它不是岗位名称；不要让通用
            # 标签别名覆盖后续真正的标题行。
            if field == "title" and _JOB_ID_RE.match(line):
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


def _is_generic_additional_heading(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?:其他信息|补充信息|additional\s+information|other\s+information)",
            value.strip(),
            re.IGNORECASE,
        )
    )


def _extract_sections(lines: list[str], consumed: set[int]) -> tuple[str, str, str, set[int], bool]:
    description_lines: list[str] = []
    requirement_lines: list[str] = []
    additional_lines: list[str] = []
    section_indices: set[int] = set()
    current_section = ""
    saw_description_heading = False

    for index, line in enumerate(lines):
        inline_matches = list(_INLINE_SECTION_RE.finditer(line))
        if inline_matches:
            section_indices.add(index)
            previous_section = current_section
            restore_description_after_intro = False
            for match_index, match in enumerate(inline_matches):
                heading = match.group("heading")
                if _DESCRIPTION_HEADING_RE.match(heading):
                    current_section = "description"
                elif _REQUIREMENTS_HEADING_RE.match(heading):
                    current_section = "requirements"
                else:
                    current_section = "additional"
                if current_section == "description":
                    saw_description_heading = True
                content_end = (
                    inline_matches[match_index + 1].start()
                    if match_index + 1 < len(inline_matches)
                    else len(line)
                )
                content = line[match.end() : content_end].strip()
                if current_section == "description":
                    if content:
                        description_lines.append(content)
                elif current_section == "requirements":
                    if content:
                        requirement_lines.append(content)
                else:
                    normalized_heading = heading.strip()
                    if content:
                        additional_lines.append(f"{normalized_heading}：{content}")
                    elif not _is_generic_additional_heading(normalized_heading):
                        additional_lines.append(normalized_heading)
                    # 职责正文常先写一行“团队/公司介绍：...”，随后立即列出
                    # 实际职责。这种内联介绍只归入补充信息，不改变后续正文归属。
                    if previous_section == "description" and re.fullmatch(
                        r"(?:团队介绍|公司介绍|企业介绍|公司简介|企业简介|关于我们|"
                        r"company\s+overview|about\s+(?:the\s+)?company|about\s+us|"
                        r"team\s+introduction)",
                        heading.strip(),
                        re.IGNORECASE,
                    ):
                        restore_description_after_intro = True
            if restore_description_after_intro:
                current_section = previous_section
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

        additional_match = _ADDITIONAL_HEADING_RE.match(line)
        if additional_match:
            current_section = "additional"
            section_indices.add(index)
            heading = additional_match.group("heading").strip()
            content = additional_match.group("content").strip()
            if content:
                additional_lines.append(f"{heading}：{content}")
            elif not _is_generic_additional_heading(heading):
                additional_lines.append(heading)
            continue

        if current_section:
            section_indices.add(index)
            if index in consumed:
                continue
            if current_section == "description":
                description_lines.append(line)
            elif current_section == "requirements":
                requirement_lines.append(line)
            else:
                additional_lines.append(line)

    return (
        "\n".join(description_lines),
        "\n".join(requirement_lines),
        "\n".join(additional_lines),
        section_indices,
        saw_description_heading,
    )
