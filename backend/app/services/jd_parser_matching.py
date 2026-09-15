"""JD 技能词典匹配器和文本规范化。"""

import json
import re
import unicodedata
from pathlib import Path

from .jd_parser_constants import _SKILL_ALIASES, _SKILL_CANONICAL_OVERRIDES

SKILLS_PATH = Path(__file__).resolve().parent.parent / "data" / "skills.json"


def _normalize_text(text: str) -> str:
    """统一全角字符和不可见空白，降低复制来源差异对匹配的影响。"""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = (
        normalized.replace("\u00a0", " ").replace("\u200b", "").replace("’", "'").replace("‘", "'")
    )
    return normalized


def _alias_pattern(alias: str, canonical_name: str) -> re.Pattern[str] | None:
    """为英文/混合别名建立边界安全的匹配器；纯中文由包含匹配处理。"""
    alias = _normalize_text(alias).strip()
    if not alias:
        return None
    if not re.search(r"[A-Za-z]", alias):
        return None
    # 别名中的空格可能因网页排版变成多个空格或换行。
    escaped = re.escape(alias).replace(r"\ ", r"\s*")
    left_boundary = r"(?<![A-Za-z0-9])"
    right_boundary = r"(?![A-Za-z0-9])"
    if alias.startswith("."):
        # ``.NET`` 通常嵌在 ``ASP.NET`` 中；点号本身已提供足够边界，
        # 不应因为前面的框架前缀而漏掉规范技能。
        left_boundary = r""
    # 单独的 C 不应从 C++ 或 C# 中误报；它们有各自独立的技能条目。
    if canonical_name == "C" and alias == "C":
        right_boundary = r"(?![A-Za-z0-9+#])"
    # Vue.js、Node.js 等框架名不应因为 .js 后缀额外被标为 JavaScript；
    # 独立的“JS”仍可在中文文本和常规分隔符之间被识别。
    if alias.casefold() == "js":
        left_boundary = r"(?<![A-Za-z0-9.])"
    return re.compile(rf"{left_boundary}{escaped}{right_boundary}", re.IGNORECASE)


def _build_skill_matchers() -> list[tuple[re.Pattern[str] | None, str, str]]:
    """编译规范名及其别名，保持词典顺序并返回规范技能名。"""
    data = json.loads(SKILLS_PATH.read_text(encoding="utf-8"))
    matchers: list[tuple[re.Pattern[str] | None, str, str]] = []
    for category, words in data["categories"].items():
        for word in words:
            canonical_name = _SKILL_CANONICAL_OVERRIDES.get(word, word)
            aliases = (word, *_SKILL_ALIASES.get(word, ()))
            for alias in aliases:
                pattern = _alias_pattern(alias, canonical_name)
                if pattern is None and re.search(r"[A-Za-z]", alias):
                    continue
                matchers.append(
                    (
                        pattern
                        if pattern is not None
                        else re.compile(re.escape(_normalize_text(alias)), re.IGNORECASE),
                        canonical_name,
                        category,
                    )
                )
    return matchers


_SKILL_MATCHERS = _build_skill_matchers()

# Java, Go, C and CV need contextual filtering in prose, but are also commonly
# written as a compact skill list.  Keep this vocabulary deliberately limited:
# a comma-separated natural-language sentence must not become a skill list just
# because it happens to contain a short English word.
_LIST_DELIMITER_PATTERN = r"[,，、/|;；]"
_LIST_SKILL_TOKEN_PATTERN = (
    r"(?<![A-Za-z0-9])(?:"
    r"Python(?:\s*3(?:\.\d+)?)?|JavaScript|TypeScript|C\+\+|C#|"
    r"Java|Go|CV|C(?![A-Za-z0-9+#])|SQL|MySQL|PostgreSQL|SQLite|Redis|"
    r"MongoDB|Kafka|Docker|Kubernetes|FastAPI|PyTorch|TensorFlow|OpenCV|"
    r"React|Vue|Node\.js|Linux|Git|NLP|LLM|RAG|"
    r"机器学习|深度学习|自然语言处理|计算机视觉|大模型|微服务|分布式|数据结构|算法"
    r")(?![A-Za-z0-9])"
)
_LIST_SKILL_TOKEN_MATCHER = re.compile(_LIST_SKILL_TOKEN_PATTERN, re.IGNORECASE)
_TECHNICAL_LIST_ANCHOR_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"Python(?:\s*3(?:\.\d+)?)?|JavaScript|TypeScript|C\+\+|C#|SQL|"
    r"MySQL|PostgreSQL|SQLite|Redis|MongoDB|Kafka|Docker|Kubernetes|FastAPI|"
    r"PyTorch|TensorFlow|OpenCV|React|Vue|Node\.js|Linux|Git|NLP|LLM|RAG"
    r")(?![A-Za-z0-9])|机器学习|深度学习|自然语言处理|计算机视觉|大模型|"
    r"微服务|分布式|数据结构|算法",
    re.IGNORECASE,
)
_TECHNICAL_LIST_SEQUENCE_PATTERN = re.compile(
    rf"{_LIST_SKILL_TOKEN_PATTERN}(?:\s*{_LIST_DELIMITER_PATTERN}\s*"
    rf"{_LIST_SKILL_TOKEN_PATTERN})+",
    re.IGNORECASE,
)
