"""教育、工作、校园、项目和奖项条目的解析。"""

from .entry_blocks import (
    _block_labeled_value,
    _is_header_metadata_line,
    _parse_header,
    _split_entry_blocks,
)
from .entry_constants import _DATE_RE, _DEGREE_TERMS
from .entry_details import _detail_groups
from .entry_inference import _compact_header_fields, _find_date_range, _infer_unlabeled_header
from .normalization import _clean_line


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
