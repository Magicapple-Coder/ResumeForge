"""个人资料文本的行、标题和字段起始规范化。"""

import re
from functools import lru_cache

from .entry_constants import _BULLET_RE, _NUMBERED_HEADING_RE
from .section_constants import _RESET_SECTION_ALIASES, _SECTION_ALIASES


def _normalize_lines(text: str) -> list[str]:
    # 仅归一化全角拉丁字母/数字和不可见空白，保留中文标点的原始语义。
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
    lines: list[str] = []
    previous_blank = False
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            if lines and not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        lines.append(line)
        previous_blank = False
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _clean_line(line: str) -> str:
    return _BULLET_RE.sub("", line.lstrip("# ")).strip()


def _compact_heading(value: str) -> str:
    """统一标题的编号、括号和中英文空白，容纳不同模板的复制结果。"""
    candidate = _NUMBERED_HEADING_RE.sub("", value.strip())
    candidate = candidate.rstrip("：:").strip()
    # 常见模板会在中文标题后附 ``(Education)`` 或 ``/ English``。
    english_section_words = (
        r"education(?:\s+(?:background|and\s+training))?|"
        r"(?:work|professional|campus|leadership|internship|extracurricular)\s+experience|"
        r"(?:work|professional|employment)\s+history|"
        r"projects?(?:\s+(?:and|&)\s+practice|\s+experience)?|"
        r"portfolio\s+projects?|"
        r"(?:technical\s+)?(?:skills?|expertise|proficiencies?)|"
        r"skills?\s+(?:and|&)\s+certifications|"
        r"programming\s+languages|tools\s+(?:and|&)\s+technologies|"
        r"awards?|honors?|certificates?|certifications?|summary|profile"
    )
    candidate = re.sub(
        rf"\s*[（(](?:{english_section_words})[）)]\s*$", "", candidate, flags=re.IGNORECASE
    )
    candidate = re.sub(
        rf"\s*(?:/|｜|\|)\s*(?:{english_section_words})\s*$", "", candidate, flags=re.IGNORECASE
    )
    candidate = re.sub(
        rf"^(?:{english_section_words})\s*(?:/|｜|\|)\s*", "", candidate, flags=re.IGNORECASE
    )
    return re.sub(r"[\s（）()【】\[\]·•_-]", "", candidate).casefold()


_COMPACT_SECTION_ALIASES = {
    key: {_compact_heading(alias) for alias in aliases} for key, aliases in _SECTION_ALIASES.items()
}
_COMPACT_RESET_ALIASES = {_compact_heading(alias) for alias in _RESET_SECTION_ALIASES}


def _heading_parts(line: str) -> tuple[str | None, str]:
    clean = _clean_line(line)
    # 先尝试完整标题；随后处理“技能：Python、SQL”这种标题和内容同在一行。
    compact = _compact_heading(clean)
    for key, aliases in _COMPACT_SECTION_ALIASES.items():
        if compact in aliases:
            return key, ""

    numbered_removed = _NUMBERED_HEADING_RE.sub("", clean, count=1)
    for separator in ("：", ":"):
        if separator not in numbered_removed:
            continue
        heading, content = numbered_removed.split(separator, 1)
        heading_compact = _compact_heading(heading)
        for key, aliases in _COMPACT_SECTION_ALIASES.items():
            if heading_compact in aliases:
                return key, content.strip()
    # “教育背景 / Education” 和 “Projects - 项目经历” 等模板用横线连接
    # 中英文标题；只有两侧都能映射到同一分区时才接受，避免误切普通正文。
    for separator in ("/", "／", "|", "｜", "-", "—", "–"):
        if separator not in numbered_removed:
            continue
        left, right = (part.strip() for part in numbered_removed.split(separator, 1))
        left_key = next(
            (
                key
                for key, aliases in _COMPACT_SECTION_ALIASES.items()
                if _compact_heading(left) in aliases
            ),
            None,
        )
        right_key = next(
            (
                key
                for key, aliases in _COMPACT_SECTION_ALIASES.items()
                if _compact_heading(right) in aliases
            ),
            None,
        )
        if left_key and right_key and left_key == right_key:
            return left_key, ""
    return None, ""


def _heading_key(line: str) -> str | None:
    return _heading_parts(line)[0]


@lru_cache(maxsize=64)
def _field_start_pattern(labels: tuple[str, ...]) -> re.Pattern[str]:
    """缓存字段起始匹配器，粘贴大段文本时避免逐行重复编译。"""
    alternatives = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    return re.compile(rf"^(?:{alternatives})(?:\s*[:：]|\s+)", re.IGNORECASE)


def _starts_with_field(line: str, labels: tuple[str, ...]) -> bool:
    return bool(_field_start_pattern(labels).match(_clean_line(line)))
