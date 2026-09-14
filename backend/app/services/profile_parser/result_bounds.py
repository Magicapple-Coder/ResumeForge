"""解析结果的长度和条目数量边界。"""

from .limits import (
    _MAX_PARSED_SECTION_ITEMS,
    _PARSED_BASIC_FIELD_LIMITS,
    _PARSED_ENTRY_FIELD_LIMITS,
)


def _bound_parse_result(
    basic: dict[str, str],
    summary: str,
    sections: dict[str, list[dict[str, str]]],
) -> tuple[dict[str, str], str, dict[str, list[dict[str, str]]], bool]:
    """让不可信粘贴文本始终符合可保存 Schema 的长度与数量边界。"""
    truncated = False

    def bounded(value: str, limit: int) -> str:
        nonlocal truncated
        if len(value) > limit:
            truncated = True
            return value[:limit]
        return value

    safe_basic = {
        field: bounded(str(value or ""), limit)
        for field, limit in _PARSED_BASIC_FIELD_LIMITS.items()
        for value in [basic.get(field, "")]
    }
    safe_sections: dict[str, list[dict[str, str]]] = {}
    for section, limits in _PARSED_ENTRY_FIELD_LIMITS.items():
        entries = sections[section]
        if len(entries) > _MAX_PARSED_SECTION_ITEMS:
            truncated = True
        safe_sections[section] = [
            {
                field: bounded(str(entry.get(field, "") or ""), limit)
                for field, limit in limits.items()
            }
            for entry in entries[:_MAX_PARSED_SECTION_ITEMS]
        ]
    return safe_basic, bounded(summary, 200_000), safe_sections, truncated
