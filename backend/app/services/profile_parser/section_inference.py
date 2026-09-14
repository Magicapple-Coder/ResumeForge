"""资料分区推断的兼容导出层。"""

from .section_signals import (
    _infer_section_for_unlabeled_line,
    _is_project_detail_line,
    _looks_like_skill_list,
    _looks_like_unlabeled_entry_line,
)
from .section_transitions import (
    _infer_section_from_unlabeled_sequence,
    _is_context_detail_field,
    _starts_explicit_section_transition,
)

__all__ = [
    "_infer_section_for_unlabeled_line",
    "_infer_section_from_unlabeled_sequence",
    "_is_context_detail_field",
    "_is_project_detail_line",
    "_looks_like_skill_list",
    "_looks_like_unlabeled_entry_line",
    "_starts_explicit_section_transition",
]
