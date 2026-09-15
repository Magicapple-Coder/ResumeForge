"""JD 学历和经验年限的规则解析。"""

import re

from .jd_parser_constants import (
    _CHINESE_YEARS_PATTERN,
    _ENGLISH_WORD_YEARS_PATTERN,
    _YEARS_PATTERN,
)


def _contains_degree_alias(text: str, alias: str) -> bool:
    """匹配学历词时排除少数明显的非学历复合词。"""
    suffix_exclusion = {
        "博士": "后",  # 博士后是职称/经历，不是学历要求
        "研究生": "院",  # 研究生院是机构名称
    }.get(alias)
    pattern = re.escape(alias)
    if suffix_exclusion:
        pattern += rf"(?!{re.escape(suffix_exclusion)})"
    if re.search(r"[A-Za-z]", alias):
        # 英文学历词需要 ASCII 边界，避免 ``master`` 命中普通单词的一部分。
        pattern = rf"(?<![A-Za-z]){pattern}(?![A-Za-z])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def _chinese_number(value: str) -> int:
    """把招聘文本中常见的中文小数字转换成整数。"""
    digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value == "十":
        return 10
    if "百" in value:
        head, _, tail = value.partition("百")
        return (digits.get(head, 1) * 100) + (_chinese_number(tail) if tail else 0)
    if "十" in value:
        head, _, tail = value.partition("十")
        tens = digits.get(head, 1) if head else 1
        return tens * 10 + (digits.get(tail, 0) if tail else 0)
    return digits.get(value, 0)


def _english_number(value: str) -> int:
    return {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }.get(value.casefold(), 0)


def _extract_min_years(text: str) -> int | None:
    values: list[int] = []
    for match in _YEARS_PATTERN.finditer(text):
        values.append(int(match.group("years")))
    for match in _CHINESE_YEARS_PATTERN.finditer(text):
        years = _chinese_number(match.group("years"))
        if years:
            values.append(years)
    for match in _ENGLISH_WORD_YEARS_PATTERN.finditer(text):
        years = _english_number(match.group("years"))
        if years:
            values.append(years)
    return min(values) if values else None
