"""经历条目块、头部字段和日期范围的基础解析。"""

import re

from .entry_constants import (
    _DATE_RANGE_RE,
    _ENTRY_HEADER_PATTERNS,
    _ENTRY_SEPARATOR_RE,
    _HEADER_BOUNDARY_LABELS,
    _HEADER_LABEL_ALIASES,
    _HEADER_SEPARATOR_RE,
)
from .normalization import _clean_line


def _split_entry_blocks(lines: list[str], kind: str = "") -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                blocks.append(current)
                current = []
            continue
        if current and _looks_like_entry_header(line, kind):
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _looks_like_entry_header(line: str, kind: str = "") -> bool:
    clean = _clean_line(line)
    if not clean or len(clean) > 180:
        return False
    # 新条目的第一行应与解析阶段认可的字段别名保持一致。这里不能只列
    # 几个中文写法，否则连续粘贴的 ``Company:`` / ``就职公司：`` 会被
    # 合并为一条经历，第二段内容也随之丢失。
    primary_label = _ENTRY_HEADER_PATTERNS.get(kind, _ENTRY_HEADER_PATTERNS["default"])
    # “学历：硕士”“任职时间：...”等同一条记录的字段可能包含日期或学位词，
    # 必须先排除，避免被后面的通用日期/学历启发式误切成新记录。
    if _is_header_metadata_line(clean):
        return bool(primary_label.match(clean))
    date_match = _DATE_RANGE_RE.search(clean)
    if date_match:
        # 只把带有结构分隔符、日期位于行首/行尾的短行当作经历头部。
        # 正文中的“2024-2025 完成迁移”也含日期，但不应因此切断当前条目。
        prefix = clean[: date_match.start()].strip(" \t|｜丨·•—–－/~～")
        suffix = clean[date_match.end() :].strip(" \t|｜丨·•—–－/~～")
        if not prefix and not suffix:
            return False
        if len(clean) > 160 or re.search(r"[。！？!?]", clean):
            return False
        return bool(
            prefix
            and (re.search(r"[|｜丨·•/／~～—–－-]", prefix + suffix) or not suffix)
            or suffix
            and (re.search(r"[|｜丨·•/／~～—–－-]", prefix + suffix) or not prefix)
        )
    if primary_label.match(clean):
        return True
    has_unspaced_hyphen = bool(re.search(r"(?<!\d)-(?!\d)", clean))
    if _ENTRY_SEPARATOR_RE.search(clean) or has_unspaced_hyphen:
        # 分隔符只有在短标题中才有足够结构信号；正文中的“技术/业务”不应
        # 让当前条目被误切开。
        return (
            len(clean) <= 128
            and not re.search(r"[。！？!?]", clean)
            and not re.match(r"^(?:负责|参与|协助|完成|实现|使用|开发|设计|优化)", clean)
        )
    if kind == "education":
        return bool(
            re.search(r"(?:本科|硕士|博士|专科|学士|研究生)", clean)
            and len(clean) <= 100
            and not re.search(r"[。！？!?]", clean)
        )
    return False


def _header_labeled_value(line: str, field: str) -> str:
    """从带多个字段的经历头部提取指定值，例如“公司：A 职位：B”。"""
    all_labels = sorted(set(_HEADER_BOUNDARY_LABELS), key=len, reverse=True)
    alternatives = "|".join(re.escape(label) for label in all_labels)
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_])(?P<label>{alternatives})\s*[:：]\s*",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(line))
    if not matches:
        return ""
    selected: list[re.Match[str]] = []
    for match in matches:
        # “项目名称”与“项目”等标签可能在同一位置起始；词典按长度排序，
        # 仅保留最长标签，避免短标签提前截断字段值。
        if selected and match.start() < selected[-1].end():
            continue
        selected.append(match)

    labels = {label.casefold() for label in _HEADER_LABEL_ALIASES[field]}
    for index, match in enumerate(selected):
        if match.group("label").casefold() not in labels:
            continue
        value_end = selected[index + 1].start() if index + 1 < len(selected) else len(line)
        value = line[match.end() : value_end]
        # 日期已由专门逻辑提取，不能残留在公司、项目或角色字段中。
        return _DATE_RANGE_RE.sub("", value).strip(" \t|｜丨;,；，/／-—–－~～")
    return ""


def _block_labeled_value(block: list[str], field: str) -> str:
    for line in block:
        value = _header_labeled_value(line, field)
        if value:
            return value
    return ""


def _is_header_metadata_line(line: str) -> bool:
    labels = "|".join(
        re.escape(label) for label in sorted(set(_HEADER_BOUNDARY_LABELS), key=len, reverse=True)
    )
    return bool(re.match(rf"^(?:{labels})\s*[:：]", _clean_line(line), re.IGNORECASE))


def _parse_header(line: str) -> tuple[list[str], str, str]:
    clean = _clean_line(line)
    date_match = _DATE_RANGE_RE.search(clean)
    start_date = date_match.group("start") if date_match else ""
    end_date = date_match.group("end") if date_match else ""
    if date_match:
        clean = (clean[: date_match.start()] + clean[date_match.end() :]).strip(
            " -—–－~～|｜丨·/／"
        )
    # 日期已先移除，因此此处可以兼容未加空格的 ``公司-岗位-时间`` 格式，
    # 又不会把年月中的连字符切开。
    parts = [part.strip() for part in _HEADER_SEPARATOR_RE.split(clean) if part.strip()]
    if len(parts) == 1:
        parts = [part.strip() for part in re.split(r"\s{2,}|\t+", clean) if part.strip()]
    return parts, start_date, end_date
