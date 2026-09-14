"""个人资料基本字段的标签和值提取。"""

import re
from functools import lru_cache

from .entry_constants import (
    _BASIC_ENGLISH_NAME_RE,
    _BASIC_NAME_RE,
    _BASIC_UNLABELED_CITY_RE,
    _EMAIL_RE,
    _INLINE_LABEL_SEPARATOR_RE,
    _NON_NAME_MARKERS,
    _PHONE_RE,
    _PROFILE_ENGLISH_TITLE_RE,
    _URL_RE,
)
from .identity_constants import (
    _BASIC_LABELS,
)
from .normalization import _COMPACT_RESET_ALIASES, _clean_line, _compact_heading, _heading_key


@lru_cache(maxsize=64)
def _label_value_pattern(labels: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(label) for label in labels)
    return re.compile(
        rf"^(?:{alternatives})(?:\s*[:：]\s*|\s+)(?P<value>.+?)\s*$",
        re.IGNORECASE,
    )


def _label_value(line: str, labels: tuple[str, ...]) -> str:
    match = _label_value_pattern(labels).match(line)
    return match.group("value").strip() if match else ""


@lru_cache(maxsize=64)
def _label_matches_pattern(labels: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    return re.compile(rf"(?<![\w\u4e00-\u9fff])(?:{alternatives})(?=\s*[:：]|\s+|$)", re.IGNORECASE)


def _label_matches(line: str, labels: tuple[str, ...]) -> list[tuple[int, int, str]]:
    """返回一行中所有字段标签的位置，支持 ``姓名 张三 手机 138...``。"""
    matches = list(_label_matches_pattern(labels).finditer(line))
    return [(match.start(), match.end(), match.group(0)) for match in matches]


def _extract_inline_labeled_values(line: str) -> dict[str, str]:
    """解析同一行的多个基本字段，不把后续标签吞进当前字段值。"""
    matches: list[tuple[int, int, str, str]] = []
    for field, labels in _BASIC_LABELS.items():
        for start, end, label in _label_matches(line, labels):
            # ``Project Name:``/``Company Name:`` 中的裸 ``Name`` 不是候选人
            # 姓名字段；完整的 ``project name``/``candidate name`` 别名会在
            # 更长匹配中优先保留，因此这里只过滤带英文前缀的短别名。
            if field == "name" and label.casefold() == "name":
                prefix = line[:start].rstrip()
                if prefix and prefix[-1].isalnum():
                    continue
            matches.append((start, end, field, label))
    # 同一位置可能同时匹配大小写别名，最长别名优先；之后按文本位置排序。
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str, str]] = []
    for match in matches:
        if selected and match[0] < selected[-1][1]:
            continue
        selected.append(match)

    values: dict[str, str] = {}
    for index, (start, end, field, _label) in enumerate(selected):
        value_start = end
        while value_start < len(line) and line[value_start] in " \t:：":
            value_start += 1
        value_end = selected[index + 1][0] if index + 1 < len(selected) else len(line)
        value = line[value_start:value_end].strip(" \t:：|｜丨;；,，")
        if value and field not in values:
            values[field] = value
    return values


def _extract_unlabeled_basic(lines: list[str], values: dict[str, str]) -> None:
    """从简历模板常见的联系方式行补齐没有字段标签的基本信息。"""
    preamble: list[str] = []
    for line in lines:
        if _heading_key(line) is not None:
            break
        if _compact_heading(_clean_line(line)) in _COMPACT_RESET_ALIASES:
            continue
        preamble.append(_clean_line(line))

    full_text = "\n".join(preamble)
    if not values["gender"]:
        match = re.search(r"(?<![男女])([男女])(?:性)?(?:\s|$|[|｜丨,，;；])", full_text)
        if match:
            values["gender"] = match.group(1)
        else:
            match = re.search(
                r"(?<![A-Za-z])(?P<gender>female|male|woman|man|non[- ]binary)(?![A-Za-z])",
                full_text,
                re.IGNORECASE,
            )
            if match:
                values["gender"] = match.group("gender")
    if not values["birth_year"]:
        match = re.search(r"((?:19|20)\d{2}\s*(?:年出生|年生|年|出生))", full_text)
        if match:
            values["birth_year"] = match.group(1).replace(" ", "")
        else:
            # 只有身份首行明确出现 born，或首行同时包含姓名/联系方式等
            # 身份信号时，才把独立四位年份当作出生年；否则项目/任职日期
            # 中的年份不应污染基本资料。
            identity_line = preamble[0] if preamble else ""
            has_identity_signal = bool(
                _PHONE_RE.search(identity_line)
                or _EMAIL_RE.search(identity_line)
                or re.search(r"(?:男|女|male|female|born|出生)", identity_line, re.IGNORECASE)
            )
            year_source = identity_line if has_identity_signal else ""
            match = re.search(
                r"(?:\bborn\s*)?((?:19|20)\d{2})(?:\s*(?:year|born))?\b",
                year_source,
                re.IGNORECASE,
            )
            if match:
                values["birth_year"] = match.group(1)
    if not values["city"]:
        # 只接受独立城市 token，避免把“意向城市：北京”误写为现居城市。
        for line in preamble:
            for token in re.split(r"[\s|｜丨,，;；]+", line):
                city_match = _BASIC_UNLABELED_CITY_RE.fullmatch(token.rstrip("市"))
                if city_match:
                    values["city"] = city_match.group(0)
                    break
            if values["city"]:
                break

    if not values["name"]:
        has_identity_context = bool(
            _PHONE_RE.search(full_text)
            or _EMAIL_RE.search(full_text)
            or values["gender"]
            or values["birth_year"]
            or values["city"]
        )
        for line in preamble:
            # 常见简历首行会用空格排列“姓名 性别 城市 电话”；先只取行首
            # 的短中文姓名，避免把后面的学校或岗位描述当成姓名。
            leading_name = re.match(r"^([\u4e00-\u9fff]{2,6})(?=\s+|[|｜丨,，;；]|$)", line)
            if (
                leading_name
                and (has_identity_context or line == preamble[0])
                and not any(marker in leading_name.group(1) for marker in _NON_NAME_MARKERS)
            ):
                values["name"] = leading_name.group(1)
                return
            candidate = line
            candidate = _PHONE_RE.sub("", candidate)
            candidate = _EMAIL_RE.sub("", candidate)
            candidate = _URL_RE.sub("", candidate)
            tokens = [
                token.strip()
                for token in _INLINE_LABEL_SEPARATOR_RE.split(candidate)
                if token.strip()
            ]
            for token in tokens:
                token = re.sub(r"(?:男|女)(?:性)?$", "", token).strip()
                token = re.sub(r"(?:19|20)\d{2}\s*年?(?:出生|年生)?$", "", token).strip()
                if (
                    (has_identity_context or line == preamble[0])
                    and (_BASIC_NAME_RE.fullmatch(token) or _BASIC_ENGLISH_NAME_RE.fullmatch(token))
                    and not _PROFILE_ENGLISH_TITLE_RE.search(token)
                    and not any(marker in token for marker in _NON_NAME_MARKERS)
                ):
                    values["name"] = token
                    return


def _extract_basic(lines: list[str]) -> dict[str, str]:
    values = {field: "" for field in _BASIC_LABELS}
    for line in lines:
        inline_values = _extract_inline_labeled_values(line)
        for field, value in inline_values.items():
            if value and not values[field]:
                values[field] = value
        for field, labels in _BASIC_LABELS.items():
            value = _label_value(line, labels)
            if value and not values[field]:
                values[field] = value

    full_text = "\n".join(lines)
    # “联系方式：手机 / 邮箱”可能被整体识别为一个标签值；二次提取保证
    # phone/email 字段始终只保存对应格式，不把另一字段或分隔符带进去。
    phone_source = values["phone"] or full_text
    phone_match = _PHONE_RE.search(phone_source)
    if phone_match:
        phone_digits = re.sub(r"\D", "", phone_match.group(0))
        values["phone"] = phone_digits[2:] if phone_digits.startswith("86") else phone_digits
    else:
        values["phone"] = ""
    email_source = values["email"] or full_text
    email_match = _EMAIL_RE.search(email_source)
    values["email"] = email_match.group(0) if email_match else ""
    if not values["github"]:
        match = re.search(r"https?://(?:www\.)?github\.com/[^\s<>\"']+", full_text, re.IGNORECASE)
        values["github"] = match.group(0).rstrip(".,;，。；") if match else ""
    if not values["personal_website"]:
        urls = _URL_RE.findall(full_text)
        values["personal_website"] = next(
            (url.rstrip(".,;，。；") for url in urls if "github.com" not in url.lower()), ""
        )
    _extract_unlabeled_basic(lines, values)
    return values
