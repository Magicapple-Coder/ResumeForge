"""JD 技能匹配的上下文误报过滤。"""

import re

from .jd_parser_constants import (
    _LIST_SKILL_TOKEN_MATCHER,
    _TECHNICAL_LIST_ANCHOR_PATTERN,
    _TECHNICAL_LIST_SEQUENCE_PATTERN,
)


def _is_delimited_technical_skill_list(text: str, skill: str, match: re.Match[str]) -> bool:
    """Return whether a short ambiguous match belongs to a compact skill list."""
    for sequence in _TECHNICAL_LIST_SEQUENCE_PATTERN.finditer(text):
        if not (sequence.start() <= match.start() and match.end() <= sequence.end()):
            continue

        sequence_text = sequence.group()
        token_count = sum(1 for _ in _LIST_SKILL_TOKEN_MATCHER.finditer(sequence_text))
        anchor_count = sum(1 for _ in _TECHNICAL_LIST_ANCHOR_PATTERN.finditer(sequence_text))

        # One unambiguous technical anchor makes ``Python, Java`` a valid list.
        # CV at the beginning of a two-item phrase is excluded because "submit
        # your CV, Python ..." is ordinary prose rather than a skills list.
        if anchor_count and (
            skill != "计算机视觉" or token_count >= 3 or match.start() > sequence.start()
        ):
            return True

        # A sequence such as ``Java, Go, C, CV`` is technical even without an
        # anchor.  Requiring three entries protects ordinary two-word prose.
        if not anchor_count and token_count >= 3:
            return True
    return False


def _is_contextual_false_positive(text: str, skill: str, match: re.Match[str]) -> bool:
    """过滤少数短别名在复合技术名中的重叠命中。"""
    matched = match.group(0).casefold()
    context = text[max(0, match.start() - 32) : min(len(text), match.end() + 32)]
    if skill in {"Java", "Go", "C", "计算机视觉"} and _is_delimited_technical_skill_list(
        text, skill, match
    ):
        return False
    if skill == "CSS3":
        prefix = text[max(0, match.start() - 20) : match.start()]
        if re.search(r"tailwind\s*$", prefix, re.IGNORECASE):
            return True
    if skill == "Agent" and matched == "agent":
        # agent 在英文招聘文案中也常指客服/销售岗位；只有 AI/模型/工具
        # 上下文足够明确时才归一化为人工智能技能。
        if not re.search(
            r"人工智能|大模型|语言模型|智能体|机器学习|深度学习|\b(?:ai|llm|rag|aigc|"
            r"model|tool(?:s)?|function\s+calling|agentic)\b",
            context,
            re.IGNORECASE,
        ):
            return True
    if skill == "计算机视觉" and matched in {"cv", "cv技术"}:
        if not re.search(
            r"视觉|图像|图片|视频|计算机|模型|深度学习|\b(?:computer\s+vision|image|video|"
            r"vision|model|opencv|pytorch|tensorflow)\b",
            context,
            re.IGNORECASE,
        ):
            return True
    if skill == "Java" and matched == "java":
        if re.match(r"\s*script\b", text[match.end() :], re.IGNORECASE):
            return True
        if not re.search(
            r"开发|语言|编程|后端|代码|\b(?:jvm|spring|backend|developer|software|code|"
            r"application|programming)\b",
            context,
            re.IGNORECASE,
        ):
            return True
    if skill == "Python" and matched == "py":
        # PyTorch 的可分词写法（“Py Torch”）不应额外生成 Python 标签。
        if re.match(r"\s*[- ]?torch\b", text[match.end() :], re.IGNORECASE):
            return True
    if skill == "SQL" and matched == "sql":
        # Postgre SQL / My SQL 是数据库产品的空格变体，而非独立 SQL 技能。
        prefix = text[max(0, match.start() - 16) : match.start()]
        if re.search(r"(?:postgre|postgres|my)\s*$", prefix, re.IGNORECASE):
            return True
    if skill == "React" and matched == "react":
        if not re.search(
            r"开发|框架|组件|前端|页面|\b(?:frontend|front-end|framework|components?|"
            r"ui|web|javascript|typescript|jsx)\b",
            context,
            re.IGNORECASE,
        ):
            return True
    if skill == "C" and matched == "c":
        if not re.search(
            r"语言|开发|编程|代码|\b(?:programming|language|developer|embedded|"
            r"compiler|pointer)\b",
            context,
            re.IGNORECASE,
        ):
            return True
    if skill == "Shell" and matched == "shell":
        if not re.search(
            r"脚本|命令行|终端|bash|zsh|linux|\b(?:script|command|terminal|unix)\b",
            context,
            re.IGNORECASE,
        ):
            return True
    if skill == "Go" and matched == "go":
        # 普通英语中的动词 “go” 不是编程语言；招聘文本中的技术写法通常
        # 使用大写 Go，或伴随“语言/开发/编程”等上下文。
        context = text[max(0, match.start() - 32) : min(len(text), match.end() + 32)]
        if not re.search(
            r"语言|开发|编程|后端|技术|熟悉|掌握|使用|golang|goroutine|"
            r"language|develop|backend|program|experience\s+with|proficien(?:t|cy)\s+in",
            context,
            re.IGNORECASE,
        ):
            return True
    return False
