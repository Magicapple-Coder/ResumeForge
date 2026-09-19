"""简历版本三态差异（R-07）。

用标准库 ``difflib.SequenceMatcher`` 做两级对比：先按行，再对「被改写」的成对行按词。
输出 added / removed / unchanged 三态；前端只渲染、不重算——这是全仓库唯一实现，
共享知识第 11 条。
"""
from __future__ import annotations

import difflib
import json
from typing import Any

from ..schemas.resume_writing import DiffLine, DiffStats, DiffToken, ResumeDiffOut


def _to_lines(content: dict[str, Any]) -> list[str]:
    """把结构化简历内容序列化成稳定、逐行的文本，供行级 diff 使用。

    ``sort_keys=True`` 固定键顺序，避免「字段顺序不同」被误判成内容变化；
    ``indent=2`` 让每行短小、更贴近用户可读的差异粒度。
    """
    if not isinstance(content, dict):
        return []
    serialized = json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True)
    return serialized.splitlines()


def _split_words(line: str) -> list[str]:
    return line.split()


def _word_pair_diff(base: str, target: str) -> tuple[list[DiffToken], list[DiffToken]]:
    """对一对「被改写」的行做词级 diff，返回 (base 侧 tokens, target 侧 tokens)。"""
    a = _split_words(base)
    b = _split_words(target)
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    base_tokens: list[DiffToken] = []
    target_tokens: list[DiffToken] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            base_tokens.extend(DiffToken(type="unchanged", text=word) for word in a[i1:i2])
            target_tokens.extend(DiffToken(type="unchanged", text=word) for word in b[j1:j2])
        elif tag == "delete":
            base_tokens.extend(DiffToken(type="removed", text=word) for word in a[i1:i2])
        elif tag == "insert":
            target_tokens.extend(DiffToken(type="added", text=word) for word in b[j1:j2])
        elif tag == "replace":
            base_tokens.extend(DiffToken(type="removed", text=word) for word in a[i1:i2])
            target_tokens.extend(DiffToken(type="added", text=word) for word in b[j1:j2])
    return base_tokens, target_tokens


def diff_lines(base_lines: list[str], target_lines: list[str]) -> list[DiffLine]:
    """行级 + 词级两级 diff，返回有序的三态行序列。"""
    matcher = difflib.SequenceMatcher(a=base_lines, b=target_lines, autojunk=False)
    result: list[DiffLine] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for index in range(i1, i2):
                result.append(DiffLine(type="unchanged", text=base_lines[index]))
        elif tag == "delete":
            for index in range(i1, i2):
                result.append(DiffLine(type="removed", text=base_lines[index]))
        elif tag == "insert":
            for index in range(j1, j2):
                result.append(DiffLine(type="added", text=target_lines[index]))
        elif tag == "replace":
            # 成对的行做词级 diff，剩下不对称的行按整行 added/removed 处理。
            pairs = min(i2 - i1, j2 - j1)
            for offset in range(pairs):
                base_text = base_lines[i1 + offset]
                target_text = target_lines[j1 + offset]
                base_tokens, target_tokens = _word_pair_diff(base_text, target_text)
                result.append(DiffLine(type="removed", text=base_text, tokens=base_tokens))
                result.append(DiffLine(type="added", text=target_text, tokens=target_tokens))
            for index in range(i1 + pairs, i2):
                result.append(DiffLine(type="removed", text=base_lines[index]))
            for index in range(j1 + pairs, j2):
                result.append(DiffLine(type="added", text=target_lines[index]))
    return result


def build_resume_diff(
    base_id: int,
    base_title: str,
    base_content: dict[str, Any],
    against_id: int,
    against_title: str,
    against_content: dict[str, Any],
) -> ResumeDiffOut:
    """把两份简历的结构化内容序列化后做三态 diff，返回可直接下发前端的结构。"""
    base_lines = _to_lines(base_content)
    target_lines = _to_lines(against_content)
    lines = diff_lines(base_lines, target_lines)
    stats = DiffStats(
        added=sum(1 for line in lines if line.type == "added"),
        removed=sum(1 for line in lines if line.type == "removed"),
        unchanged=sum(1 for line in lines if line.type == "unchanged"),
    )
    return ResumeDiffOut(
        base_id=base_id,
        against_id=against_id,
        base_title=base_title,
        against_title=against_title,
        lines=lines,
        stats=stats,
    )
