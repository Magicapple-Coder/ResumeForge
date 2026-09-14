"""资料分区识别的兼容导出层。"""

from .section_inference import (
    _infer_section_for_unlabeled_line,
    _infer_section_from_unlabeled_sequence,
    _is_context_detail_field,
    _is_project_detail_line,
    _looks_like_skill_list,
    _looks_like_unlabeled_entry_line,
    _starts_explicit_section_transition,
)
from .section_splitter import _split_sections

__all__ = [
    "_infer_section_for_unlabeled_line",
    "_infer_section_from_unlabeled_sequence",
    "_is_context_detail_field",
    "_is_project_detail_line",
    "_looks_like_skill_list",
    "_looks_like_unlabeled_entry_line",
    "_split_sections",
    "_starts_explicit_section_transition",
]
