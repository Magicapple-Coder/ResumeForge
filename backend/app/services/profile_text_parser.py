"""将用户粘贴的个人资料拆成可编辑草稿。

解析器只使用本地规则，不调用网络或大模型。它优先识别明确的分区标题和字段标签，
无法确定的内容保留在对应经历的描述中，最终仍由用户在资料页核对后保存。
"""

from ..schemas.profile import ProfileTextParseResult
from .profile_parser.identity_constants import _BASIC_LABELS
from .profile_parser.basic_fields import (
    _extract_basic,
    _extract_inline_labeled_values,
    _extract_unlabeled_basic,
    _label_matches,
    _label_matches_pattern,
    _label_value,
    _label_value_pattern,
)
from .profile_parser.entry_blocks import (
    _block_labeled_value,
    _header_labeled_value,
    _is_header_metadata_line,
    _looks_like_entry_header,
    _parse_header,
    _split_entry_blocks,
)
from .profile_parser.entry_constants import (
    _BASIC_ENGLISH_NAME_RE,
    _BASIC_NAME_RE,
    _BASIC_UNLABELED_CITY_RE,
    _BULLET_RE,
    _DATE_TOKEN,
    _DATE_RANGE_RE,
    _DATE_RE,
    _DEGREE_TERMS,
    _EMAIL_RE,
    _ENTRY_HEADER_FIELDS_BY_KIND,
    _ENTRY_HEADER_PATTERNS,
    _ENTRY_SEPARATOR_RE,
    _ENGLISH_COMPANY_HINT_RE,
    _HEADER_BOUNDARY_LABELS,
    _HEADER_LABEL_ALIASES,
    _HEADER_SEPARATOR_RE,
    _INLINE_LABEL_SEPARATOR_RE,
    _NON_NAME_MARKERS,
    _NUMBERED_HEADING_RE,
    _PHONE_RE,
    _PROFILE_CHINESE_ROLE_RE,
    _PROFILE_ENGLISH_TITLE_RE,
    _URL_RE,
    _MONTH_NAME,
)
from .profile_parser.entry_details import _detail_groups
from .profile_parser.entry_inference import (
    _compact_header_fields,
    _find_date_range,
    _infer_unlabeled_header,
    _looks_like_profile_role_line,
)
from .profile_parser.limits import (
    _MAX_PARSED_SECTION_ITEMS,
    _PARSED_BASIC_FIELD_LIMITS,
    _PARSED_ENTRY_FIELD_LIMITS,
)
from .profile_parser.normalization import (
    _COMPACT_RESET_ALIASES,
    _COMPACT_SECTION_ALIASES,
    _clean_line,
    _compact_heading,
    _field_start_pattern,
    _heading_key,
    _heading_parts,
    _normalize_lines,
    _starts_with_field,
)
from .profile_parser.section_constants import _RESET_SECTION_ALIASES, _SECTION_ALIASES
from .profile_parser.section_detection import (
    _infer_section_for_unlabeled_line,
    _infer_section_from_unlabeled_sequence,
    _is_context_detail_field,
    _is_project_detail_line,
    _looks_like_skill_list,
    _looks_like_unlabeled_entry_line,
    _split_sections,
    _starts_explicit_section_transition,
)
from .profile_parser.section_parsers import (
    _parse_awards,
    _parse_education,
    _parse_experience,
    _parse_projects,
)
from .profile_parser.result_bounds import _bound_parse_result
from .profile_parser.skill_constants import _SKILL_LEADING_LEVEL_RE, _SKILL_LEVEL_RE
from .profile_parser.skill_fields import (
    _normalize_skill_name,
    _parse_skills,
    _skill_name_and_level,
    _split_tokens,
)

__all__ = [
    "parse_profile_text",
    "ProfileTextParseResult",
    "_SECTION_ALIASES",
    "_RESET_SECTION_ALIASES",
    "_BASIC_LABELS",
    "_MONTH_NAME",
    "_DATE_TOKEN",
    "_DATE_RANGE_RE",
    "_DATE_RE",
    "_PHONE_RE",
    "_EMAIL_RE",
    "_URL_RE",
    "_BULLET_RE",
    "_ENTRY_SEPARATOR_RE",
    "_HEADER_SEPARATOR_RE",
    "_NUMBERED_HEADING_RE",
    "_INLINE_LABEL_SEPARATOR_RE",
    "_BASIC_UNLABELED_CITY_RE",
    "_BASIC_NAME_RE",
    "_BASIC_ENGLISH_NAME_RE",
    "_PROFILE_ENGLISH_TITLE_RE",
    "_PROFILE_CHINESE_ROLE_RE",
    "_ENGLISH_COMPANY_HINT_RE",
    "_NON_NAME_MARKERS",
    "_SKILL_LEVEL_RE",
    "_SKILL_LEADING_LEVEL_RE",
    "_DEGREE_TERMS",
    "_COMPACT_SECTION_ALIASES",
    "_COMPACT_RESET_ALIASES",
    "_HEADER_LABEL_ALIASES",
    "_ENTRY_HEADER_FIELDS_BY_KIND",
    "_ENTRY_HEADER_PATTERNS",
    "_HEADER_BOUNDARY_LABELS",
    "_PARSED_BASIC_FIELD_LIMITS",
    "_PARSED_ENTRY_FIELD_LIMITS",
    "_MAX_PARSED_SECTION_ITEMS",
    "_normalize_lines",
    "_clean_line",
    "_compact_heading",
    "_heading_parts",
    "_heading_key",
    "_field_start_pattern",
    "_starts_with_field",
    "_is_project_detail_line",
    "_infer_section_for_unlabeled_line",
    "_infer_section_from_unlabeled_sequence",
    "_looks_like_unlabeled_entry_line",
    "_looks_like_skill_list",
    "_starts_explicit_section_transition",
    "_is_context_detail_field",
    "_split_sections",
    "_label_value_pattern",
    "_label_value",
    "_label_matches_pattern",
    "_label_matches",
    "_extract_inline_labeled_values",
    "_extract_unlabeled_basic",
    "_extract_basic",
    "_split_entry_blocks",
    "_looks_like_entry_header",
    "_header_labeled_value",
    "_block_labeled_value",
    "_is_header_metadata_line",
    "_parse_header",
    "_compact_header_fields",
    "_find_date_range",
    "_looks_like_profile_role_line",
    "_infer_unlabeled_header",
    "_detail_groups",
    "_split_tokens",
    "_normalize_skill_name",
    "_skill_name_and_level",
    "_parse_education",
    "_parse_experience",
    "_parse_projects",
    "_parse_skills",
    "_parse_awards",
    "_bound_parse_result",
]


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
