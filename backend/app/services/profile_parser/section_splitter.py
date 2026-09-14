"""按标题和推断结果拆分个人资料分区。"""

import re

from .entry_constants import _NUMBERED_HEADING_RE
from .normalization import _COMPACT_RESET_ALIASES, _clean_line, _compact_heading, _heading_parts
from .section_constants import _SECTION_ALIASES
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


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {key: [] for key in _SECTION_ALIASES}
    current: str | None = None
    # 明确分区标题具有更高可信度；进入该分区后，条目中的日期、学校名或
    # 技能词只应作为内容解析，不能再次触发跨分区推断。无标题粘贴文本
    # 仍通过 ``current_explicit=False`` 保留按强信号切换分区的能力。
    current_explicit = False
    for index, line in enumerate(lines):
        clean = _clean_line(line)
        # 在项目块内，未编号的“技术栈：...”属于该项目。编号标题仍优先视为
        # 新分区，以支持“4. 技术能力：...”这样的简历模板。
        if (
            current == "projects"
            and _is_project_detail_line(clean)
            and _NUMBERED_HEADING_RE.match(line) is None
        ):
            sections[current].append(line)
            continue
        key, inline_content = _heading_parts(line)
        if key is not None:
            current = key
            current_explicit = True
            if inline_content:
                sections[key].append(inline_content)
            continue
        if _compact_heading(clean) in _COMPACT_RESET_ALIASES:
            current = None
            current_explicit = False
            continue
        inferred = _infer_section_for_unlabeled_line(clean)
        sequence_indices: tuple[int, int] | None = None
        if inferred is None and current is None:
            sequence = _infer_section_from_unlabeled_sequence(lines, index)
            if sequence is not None:
                inferred, sequence_indices = sequence
        # 无标题文本中的“项目名称/组织名称 -> 角色 -> 周期”字段会被通用
        # ``role/period`` 规则暂时归到工作经历；在当前上下文已明确时，这些
        # 字段没有足够证据启动新分区，应保留在当前条目中。
        if (
            current is not None
            and not current_explicit
            and inferred != current
            and _is_context_detail_field(clean, current)
        ):
            inferred = None
        if inferred is not None and (
            current is None
            or (
                inferred != current
                and (
                    _starts_explicit_section_transition(clean, inferred)
                    if current_explicit
                    else (
                        re.match(r"^[^：:]{1,32}\s*[:：]", clean) is not None
                        or _looks_like_unlabeled_entry_line(clean)
                        or (inferred == "skills" and _looks_like_skill_list(clean))
                    )
                )
            )
        ):
            current = inferred
            current_explicit = False
            if sequence_indices is not None:
                sections[current].extend(
                    lines[sequence_index] for sequence_index in sequence_indices
                )
            sections[current].append(line)
            continue
        if current is not None:
            sections[current].append(line)
    return sections
