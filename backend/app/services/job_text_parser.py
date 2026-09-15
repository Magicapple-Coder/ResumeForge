"""将招聘页面复制出的纯文本解析为可编辑的岗位草稿。

解析器刻意只使用本地、可解释的规则：识别不到的内容留空，交给用户在
创建岗位前确认。它不访问网络，也不直接写数据库。
"""

from ..schemas.job import JobTextParseResult
from .job_parser.candidate_constants import (
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
from .job_parser.field_constants import _ENGLISH_LABELS_REQUIRING_COLON, _FIELD_LIMITS, _LABELS
from .job_parser.section_constants import (
    _ADDITIONAL_HEADING_RE,
    _ADDITIONAL_HEADINGS,
    _BARE_DATE_RE,
    _DESCRIPTION_HEADING_RE,
    _DESCRIPTION_HEADINGS,
    _INLINE_SECTION_RE,
    _JOB_ID_RE,
    _NON_PUBLISHED_DATE_CONTEXT_RE,
    _PUBLISHED_DATE_RE,
    _REQUIREMENTS_HEADING_RE,
    _REQUIREMENTS_HEADINGS,
    _SALARY_RE,
    _SECTION_HEADING_PREFIX,
    _SECTION_HEADING_SUFFIX,
    _SECTION_NUMBER_PREFIX,
    _SECTION_SEPARATOR,
    _UPDATED_DATE_RE,
    _URL_RE,
)
from .job_parser.normalization import (
    _INLINE_LABEL_PATTERNS,
    _LABEL_PATTERNS,
    _compile_inline_label_pattern,
    _compile_label_pattern,
    _find_url,
    _inline_label_matches,
    _normalize_lines,
    _strip_inline_salary,
    _truncate,
)
from .job_parser.candidates import (
    _discard_location_as_company,
    _extract_location_from_metadata,
    _looks_like_company,
    _looks_like_company_candidate,
    _looks_like_internship_marker,
    _looks_like_location,
    _looks_like_title,
    _prepare_title_candidate,
    _split_title_company,
)
from .job_parser.title_company import _extract_title_and_company
from .job_parser.metadata import (
    _detect_job_type,
    _extract_posted_at,
    _is_additional_preamble_line,
    _looks_like_compact_recruitment_metadata,
    _mark_type_lines,
    _mark_unlabeled_metadata,
    _normalize_job_type,
    _normalize_status,
)
from .job_parser.sections import (
    _extract_labeled_fields,
    _extract_sections,
    _first_section_index,
    _is_generic_additional_heading,
)

__all__ = [
    "parse_job_text",
    "JobTextParseResult",
    "_FIELD_LIMITS",
    "_LABELS",
    "_ENGLISH_LABELS_REQUIRING_COLON",
    "_compile_label_pattern",
    "_LABEL_PATTERNS",
    "_compile_inline_label_pattern",
    "_INLINE_LABEL_PATTERNS",
    "_inline_label_matches",
    "_SECTION_NUMBER_PREFIX",
    "_SECTION_HEADING_PREFIX",
    "_SECTION_HEADING_SUFFIX",
    "_DESCRIPTION_HEADINGS",
    "_REQUIREMENTS_HEADINGS",
    "_SECTION_SEPARATOR",
    "_DESCRIPTION_HEADING_RE",
    "_REQUIREMENTS_HEADING_RE",
    "_ADDITIONAL_HEADINGS",
    "_ADDITIONAL_HEADING_RE",
    "_INLINE_SECTION_RE",
    "_URL_RE",
    "_JOB_ID_RE",
    "_SALARY_RE",
    "_PUBLISHED_DATE_RE",
    "_UPDATED_DATE_RE",
    "_BARE_DATE_RE",
    "_NON_PUBLISHED_DATE_CONTEXT_RE",
    "_TITLE_TERMS",
    "_ENGLISH_TITLE_RE",
    "_TITLE_SENTENCE_PREFIX_RE",
    "_TITLE_NON_ROLE_PREFIX_RE",
    "_TITLE_SENTENCE_PREFIXES",
    "_COMPANY_TERMS",
    "_ENGLISH_COMPANY_RE",
    "_LOCATION_TERMS",
    "_NON_LOCATION_TERMS",
    "_LOCATION_SUFFIX_RE",
    "_normalize_lines",
    "_truncate",
    "_find_url",
    "_strip_inline_salary",
    "_prepare_title_candidate",
    "_looks_like_title",
    "_looks_like_company",
    "_looks_like_company_candidate",
    "_looks_like_internship_marker",
    "_split_title_company",
    "_discard_location_as_company",
    "_looks_like_location",
    "_extract_location_from_metadata",
    "_looks_like_compact_recruitment_metadata",
    "_normalize_job_type",
    "_normalize_status",
    "_extract_labeled_fields",
    "_first_section_index",
    "_mark_unlabeled_metadata",
    "_extract_title_and_company",
    "_detect_job_type",
    "_mark_type_lines",
    "_is_additional_preamble_line",
    "_is_generic_additional_heading",
    "_extract_sections",
    "_extract_posted_at",
]


def parse_job_text(text: str) -> JobTextParseResult:
    """解析一段招聘文本并返回岗位草稿；不会调用网络或修改数据库。"""
    lines = _normalize_lines(text or "")
    values, consumed = _extract_labeled_fields(lines)
    preamble_end = _first_section_index(lines)

    _mark_unlabeled_metadata(lines, values, consumed, preamble_end)
    title, company = _extract_title_and_company(lines, values, consumed, preamble_end)
    job_type = _detect_job_type(lines, values, preamble_end)
    _mark_type_lines(lines, consumed, preamble_end)

    description, requirements, additional_info, section_indices, saw_description_heading = (
        _extract_sections(lines, consumed)
    )
    section_description = description.strip()
    additional_metadata_indices = {
        index
        for index, line in enumerate(lines[:preamble_end])
        if index not in consumed
        and index not in section_indices
        and _is_additional_preamble_line(line)
    }
    additional_metadata = [lines[index] for index in sorted(additional_metadata_indices)]

    if not saw_description_heading:
        fallback_lines = [
            line
            for index, line in enumerate(lines)
            if index not in consumed
            and index not in section_indices
            and index not in additional_metadata_indices
            and not _ADDITIONAL_HEADING_RE.match(line)
        ]
        description = "\n".join(fallback_lines)
    else:
        # 标题区仍可能有不属于职责或补充信息的简介，保留在职位描述前言中。
        preamble_metadata = [
            line
            for index, line in enumerate(lines[:preamble_end])
            if index not in consumed
            and index not in section_indices
            and index not in additional_metadata_indices
            and not _ADDITIONAL_HEADING_RE.match(line)
        ]
        description = "\n".join(preamble_metadata + ([description] if description else []))

    additional_info = "\n".join(
        [*additional_metadata, *([additional_info] if additional_info else [])]
    )

    substantive_description = (
        section_description if saw_description_heading else description.strip()
    )
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
        additional_info=additional_info.strip(),
        source_url=_truncate(source_url, "source_url"),
        posted_at=_truncate(_extract_posted_at(lines, values, preamble_end), "posted_at"),
        status=_truncate(_normalize_status(status_context), "status"),
        warnings=warnings,
    )
