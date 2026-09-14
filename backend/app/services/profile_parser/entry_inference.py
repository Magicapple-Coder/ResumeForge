"""无标签经历头部的字段推断。"""

import re

from .entry_constants import (
    _DATE_RANGE_RE,
    _DEGREE_TERMS,
    _PROFILE_CHINESE_ROLE_RE,
    _PROFILE_ENGLISH_TITLE_RE,
)
from .entry_blocks import _is_header_metadata_line
from .normalization import _clean_line


def _compact_header_fields(line: str, kind: str) -> dict[str, str]:
    """保守拆解“日期 学校 专业 学历”这类无分隔符的单行头部。

    仅在存在日期、没有显式分隔符且教育行包含学历词时启用；工作和项目行
    也要求至少有两个短 token，避免把自然语言描述拆成公司/项目名称。
    """
    clean = _clean_line(line)
    date_match = _DATE_RANGE_RE.search(clean)
    if date_match is None:
        return {}
    body = (clean[: date_match.start()] + clean[date_match.end() :]).strip(" -—–－~～|｜丨·•/／")
    if not body or re.search(r"[|｜丨/／·•—–－~～-]", body) or re.search(r"[:：]", body):
        return {}
    tokens = body.split()
    if len(tokens) < 2 or any(len(token) > 64 for token in tokens):
        return {}

    if kind == "education":
        degree_index = next(
            (
                index
                for index, token in enumerate(tokens)
                if any(term.casefold() in token.casefold() for term in _DEGREE_TERMS)
            ),
            -1,
        )
        if degree_index < 2:
            return {}
        # 英文院校名通常由多个词组成；优先把 University/College/Institute
        # 及其前缀一起作为学校，其余部分才是专业，避免只取首个词。
        school_end = 1
        for index, token in enumerate(tokens[:degree_index], start=1):
            if re.fullmatch(r"(?:university|college|institute|school)", token, re.IGNORECASE):
                school_end = index
                break
        if school_end >= degree_index:
            school_end = 1
        return {
            "school": " ".join(tokens[:school_end]),
            "major": " ".join(tokens[school_end:degree_index]),
            "degree": tokens[degree_index],
            "start_date": date_match.group("start"),
            "end_date": date_match.group("end"),
        }

    if kind in {"experience", "project"} and len(tokens) >= 2:
        body_text = " ".join(tokens)
        # 英文职位通常以 Engineer/Developer/Manager 等词结尾；保留其
        # 前面的方向词（如 Backend），把前面的词作为公司/项目名。
        english_role = re.search(
            r"\b(?:backend|frontend|full[- ]?stack|software|data|machine\s+learning|ai|ml|mobile|web|devops)?\s*"
            r"(?:engineer|developer|programmer|architect|analyst|designer|scientist|researcher|"
            r"manager|consultant|specialist|intern|lead|director|technician)\b",
            body_text,
            re.IGNORECASE,
        )
        if english_role and english_role.start() > 0:
            first = body_text[: english_role.start()].strip()
            role = body_text[english_role.start() :].strip()
            if first and role:
                return {
                    "first": first,
                    "role": role,
                    "start_date": date_match.group("start"),
                    "end_date": date_match.group("end"),
                }
        chinese_role = re.search(
            r"(?:后端|前端|全栈|算法|软件|数据|产品|项目|测试|研发|运维|网络|客户端)?"
            r"(?:工程师|开发|程序员|架构师|分析师|经理|负责人|专员|研究员|设计师|实习生|助理|顾问)",
            body_text,
        )
        if chinese_role and chinese_role.start() > 0:
            first = body_text[: chinese_role.start()].strip()
            role = body_text[chinese_role.start() :].strip()
            if first and role:
                return {
                    "first": first,
                    "role": role,
                    "start_date": date_match.group("start"),
                    "end_date": date_match.group("end"),
                }
        return {
            "first": tokens[0],
            "role": " ".join(tokens[1:]),
            "start_date": date_match.group("start"),
            "end_date": date_match.group("end"),
        }
    return {}


def _find_date_range(lines: list[str], start: str, end: str) -> tuple[str, str]:
    if start or end:
        return start, end
    match = _DATE_RANGE_RE.search(" ".join(lines))
    return (match.group("start"), match.group("end")) if match else ("", "")


def _looks_like_profile_role_line(line: str) -> bool:
    """识别无标签条目中的角色行，避免把公司/项目名当成角色。"""
    clean = _clean_line(line)
    if (
        not clean
        or len(clean) > 96
        or _DATE_RANGE_RE.fullmatch(clean)
        or _is_header_metadata_line(clean)
        or re.search(r"[。！？!?]", clean)
        or re.match(r"^(?:负责|参与|协助|完成|实现|使用|开发|设计|优化|承担)", clean)
    ):
        return False
    return bool(_PROFILE_CHINESE_ROLE_RE.search(clean) or _PROFILE_ENGLISH_TITLE_RE.search(clean))


def _infer_unlabeled_header(
    block: list[str],
) -> tuple[str, str, str, str, list[str]]:
    """从“公司名 / 角色 / 日期 / 描述”连续文本中恢复条目头部。"""
    clean_block = [_clean_line(line) for line in block if _clean_line(line)]
    if len(clean_block) < 2:
        return "", "", "", "", clean_block

    date_index = next(
        (index for index, line in enumerate(clean_block) if _DATE_RANGE_RE.fullmatch(line)),
        None,
    )
    date_start = date_end = ""
    if date_index is not None:
        date_match = _DATE_RANGE_RE.fullmatch(clean_block[date_index])
        if date_match:
            date_start = date_match.group("start")
            date_end = date_match.group("end")

    first_index = next(
        (
            index
            for index, line in enumerate(clean_block)
            if index != date_index and not _is_header_metadata_line(line)
        ),
        None,
    )
    if first_index is None:
        return "", "", date_start, date_end, clean_block

    role_index = next(
        (
            index
            for index, line in enumerate(clean_block)
            if index > first_index and index != date_index and _looks_like_profile_role_line(line)
        ),
        None,
    )
    if role_index is None:
        return "", "", date_start, date_end, clean_block

    ignored = {first_index, role_index}
    if date_index is not None:
        ignored.add(date_index)
    details = [line for index, line in enumerate(clean_block) if index not in ignored]
    return clean_block[first_index], clean_block[role_index], date_start, date_end, details
