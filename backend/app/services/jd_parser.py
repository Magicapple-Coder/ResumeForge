"""JD 文本解析：基于规则提取技能标签、学历要求与年限要求。

不依赖大模型，离线可用、零成本，用于岗位卡片的标签展示与搜索辅助。
规范技能词典位于 data/skills.json；常见缩写和等价表达在本模块中映射回词典名。
"""

from ..schemas.job import SkillTag
from .jd.jd_parser_constants import (
    _CHINESE_YEARS_PATTERN,
    _DEGREE_PATTERNS,
    _ENGLISH_WORD_YEARS_PATTERN,
    _LIST_DELIMITER_PATTERN,
    _LIST_SKILL_TOKEN_MATCHER,
    _LIST_SKILL_TOKEN_PATTERN,
    _SKILL_ALIASES,
    _SKILL_CANONICAL_OVERRIDES,
    _TECHNICAL_LIST_ANCHOR_PATTERN,
    _TECHNICAL_LIST_SEQUENCE_PATTERN,
    _YEARS_PATTERN,
)
from .jd.jd_parser_filters import _is_contextual_false_positive, _is_delimited_technical_skill_list
from .jd.jd_parser_matching import (
    SKILLS_PATH,
    _SKILL_MATCHERS,
    _alias_pattern,
    _build_skill_matchers,
    _normalize_text,
)
from .jd.jd_parser_requirements import (
    _chinese_number,
    _contains_degree_alias,
    _english_number,
    _extract_min_years,
)

__all__ = [
    "parse_jd",
    "SkillTag",
    "SKILLS_PATH",
    "_DEGREE_PATTERNS",
    "_YEARS_PATTERN",
    "_CHINESE_YEARS_PATTERN",
    "_ENGLISH_WORD_YEARS_PATTERN",
    "_SKILL_ALIASES",
    "_SKILL_CANONICAL_OVERRIDES",
    "_LIST_DELIMITER_PATTERN",
    "_LIST_SKILL_TOKEN_PATTERN",
    "_LIST_SKILL_TOKEN_MATCHER",
    "_TECHNICAL_LIST_ANCHOR_PATTERN",
    "_TECHNICAL_LIST_SEQUENCE_PATTERN",
    "_normalize_text",
    "_alias_pattern",
    "_build_skill_matchers",
    "_SKILL_MATCHERS",
    "_is_delimited_technical_skill_list",
    "_is_contextual_false_positive",
    "_contains_degree_alias",
    "_chinese_number",
    "_english_number",
    "_extract_min_years",
]

def parse_jd(text: str | None) -> dict:
    """解析 JD 文本，返回 {skills, degree, min_years}。

    任何异常输入都返回空结果，保证调用方永不因解析崩溃。
    """
    result: dict = {"skills": [], "degree": "", "min_years": None}
    if not isinstance(text, str) or not text.strip():
        return result

    text = _normalize_text(text)
    seen: set[str] = set()
    skills: list[SkillTag] = []
    for pattern, word, category in _SKILL_MATCHERS:
        match = pattern.search(text)
        # 一个普通英语用法可能先于真正的技术用法出现；跳过误命中后继续
        # 搜索，避免一次 false positive 把整段 JD 的真实技能遮掉。
        while match and _is_contextual_false_positive(text, word, match):
            match = pattern.search(text, match.end())
        if match and word.casefold() not in seen:
            seen.add(word.casefold())
            skills.append(SkillTag(name=word, category=category))

    # JD 同时出现多档学历时取最高档（博士 > 硕士 > 本科 > 大专）
    degree = ""
    for candidate, aliases in _DEGREE_PATTERNS:
        if any(_contains_degree_alias(text, alias) for alias in aliases):
            degree = candidate
            break

    # 多个年限出现时取最小值（最宽松的要求）；同时支持阿拉伯数字和
    # “三年以上/两年起”等中文写法。
    min_years = _extract_min_years(text)

    result["skills"] = skills
    result["degree"] = degree
    result["min_years"] = min_years
    return result
