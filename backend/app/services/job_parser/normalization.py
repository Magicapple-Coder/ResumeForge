"""招聘文本的字段匹配、行规范化和基础清洗。"""

import re

from .field_constants import _ENGLISH_LABELS_REQUIRING_COLON, _FIELD_LIMITS, _LABELS
from .section_constants import _SALARY_RE, _URL_RE


def _compile_label_pattern(labels: tuple[str, ...]) -> re.Pattern[str]:
    ordered = sorted(labels, key=len, reverse=True)
    alternatives = "|".join(re.escape(label) for label in ordered)
    # 部分单词型英文标签（如 ``job``/``company``）很容易成为章节标题的前缀，
    # 例如 ``Job Description``。这些高歧义标签只接受冒号形式；中文、多词
    # 标签和低歧义英文标签继续兼容“标签 值”的复制格式。
    spaced_labels = [
        label
        for label in ordered
        if not (
            re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", label)
            and label.casefold() in _ENGLISH_LABELS_REQUIRING_COLON
        )
    ]
    if not spaced_labels:
        return re.compile(rf"^(?:{alternatives})\s*[:：]\s*(?P<value>.+?)\s*$", re.IGNORECASE)
    spaced_alternatives = "|".join(re.escape(label) for label in spaced_labels)
    return re.compile(
        rf"^(?:(?:{alternatives})\s*[:：]\s*|(?:{spaced_alternatives})\s+)"
        r"(?P<value>.+?)\s*$",
        re.IGNORECASE,
    )


_LABEL_PATTERNS = {field: _compile_label_pattern(labels) for field, labels in _LABELS.items()}


def _compile_inline_label_pattern(
    labels: tuple[str, ...],
) -> tuple[re.Pattern[str], frozenset[str]]:
    """预编译卡片内联字段匹配器，避免大段文本逐行重复构造正则。"""
    ordered = sorted(labels, key=len, reverse=True)
    alternatives = "|".join(re.escape(label) for label in ordered)
    colon_only = frozenset(
        label.casefold()
        for label in ordered
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", label)
        and label.casefold() in _ENGLISH_LABELS_REQUIRING_COLON
    )
    return (
        re.compile(
            rf"(?<![A-Za-z0-9_])(?P<label>{alternatives})(?P<separator>"
            r"\s*[:：]\s*|\s+)",
            re.IGNORECASE,
        ),
        colon_only,
    )


_INLINE_LABEL_PATTERNS = {
    field: _compile_inline_label_pattern(labels) for field, labels in _LABELS.items()
}


def _inline_label_matches(line: str) -> list[tuple[int, int, str, str]]:
    """找出同一行中的多个字段标签，避免把后续字段吞进前一个值。

    招聘网站的卡片文本经常把元信息压成 ``公司：A 职位：B 地点：C``；
    逐行使用带锚点的字段正则只能识别第一个字段，因此这里先收集标签
    位置，再用下一个标签作为当前值的结束边界。
    """
    matches: list[tuple[int, int, str, str]] = []
    for field, (pattern, colon_only) in _INLINE_LABEL_PATTERNS.items():
        for match in pattern.finditer(line):
            if (
                match.group("label").casefold() in colon_only
                and ":" not in match.group("separator")
                and "：" not in match.group("separator")
            ):
                continue
            matches.append((match.start(), match.end(), field, match.group("label")))

    # 同一位置可能同时匹配短/长别名（如“公司”与“公司名称”）；保留最长的
    # 一个，随后按原文位置排序，确保字段值边界稳定。
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str, str]] = []
    for match in matches:
        if selected and match[0] < selected[-1][1]:
            continue
        selected.append(match)
    return selected


def _normalize_lines(text: str) -> list[str]:
    # 只归一化全角拉丁字母/数字和空格；招聘正文中的全角标点具有语义和
    # 可读性，不能像 NFKC 那样无差别改成半角（例如“，”变成“,”）。
    normalized_chars: list[str] = []
    for char in text:
        codepoint = ord(char)
        if char == "\u3000":
            normalized_chars.append(" ")
        elif (
            0xFF10 <= codepoint <= 0xFF19
            or 0xFF21 <= codepoint <= 0xFF3A
            or 0xFF41 <= codepoint <= 0xFF5A
        ):
            normalized_chars.append(chr(codepoint - 0xFEE0))
        else:
            normalized_chars.append(char)
    normalized = "".join(normalized_chars)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00a0", " ").replace("\u200b", "")
    normalized = normalized.replace("\u2028", "\n").replace("\u2029", "\n")
    return [line.strip() for line in normalized.split("\n") if line.strip()]


def _truncate(value: str, field: str) -> str:
    return value.strip()[: _FIELD_LIMITS[field]]


def _find_url(value: str) -> str:
    match = _URL_RE.search(value)
    if match is None:
        return ""
    return match.group(0).rstrip(".,;:!?，。；：！？、)]}）】」』")


def _strip_inline_salary(value: str) -> str:
    """去掉标题卡片中附带的薪资，避免薪资元信息吞掉岗位名。"""
    return _SALARY_RE.sub("", value).strip(" \t|｜·,，;；/\\")
