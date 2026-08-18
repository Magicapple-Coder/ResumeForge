"""JD 文本解析：基于规则提取技能标签、学历要求与年限要求。

不依赖大模型，离线可用、零成本，用于岗位卡片的标签展示与搜索辅助。
技能词典位于 data/skills.json，增删关键词只需改词典，无需改代码。
"""
import json
import re
from pathlib import Path

from ..schemas.job import SkillTag

SKILLS_PATH = Path(__file__).resolve().parent.parent / "data" / "skills.json"

# 学历按优先级排序，JD 同时出现多档时取最高档
_DEGREE_PRIORITY = ["博士", "硕士", "本科", "大专"]

# "3年以上" / "1年及以上" / "2年相关经验"
_YEARS_PATTERN = re.compile(r"(\d{1,2})\s*年(?:以上|及以上)?")


def _build_skill_matchers() -> tuple[list[tuple[re.Pattern, str, str]], list[tuple[str, str, str]]]:
    """把技能词典编译成匹配器：英文词用正则（带边界），中文短语直接包含匹配。"""
    data = json.loads(SKILLS_PATH.read_text(encoding="utf-8"))
    english: list[tuple[re.Pattern, str, str]] = []
    chinese: list[tuple[str, str, str]] = []
    for category, words in data["categories"].items():
        for word in words:
            if re.search(r"[a-zA-Z]", word):
                # Python 的 \b 会把中文也视为“单词字符”，导致「JavaScript等」漏匹配。
                # 统一只用 ASCII 字母数字做边界，仍能避免把 Java 命中 JavaScript。
                pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", re.IGNORECASE)
                english.append((pattern, word, category))
            else:
                chinese.append((word, word, category))
    return english, chinese


_ENGLISH_MATCHERS, _CHINESE_MATCHERS = _build_skill_matchers()


def parse_jd(text: str | None) -> dict:
    """解析 JD 文本，返回 {skills, degree, min_years}。

    任何异常输入都返回空结果，保证调用方永不因解析崩溃。
    """
    result: dict = {"skills": [], "degree": "", "min_years": None}
    if not text or not text.strip():
        return result

    seen: set[str] = set()
    skills: list[SkillTag] = []
    for pattern, word, category in _ENGLISH_MATCHERS:
        if pattern.search(text) and word.lower() not in seen:
            seen.add(word.lower())
            skills.append(SkillTag(name=word, category=category))
    for word, _raw, category in _CHINESE_MATCHERS:
        if word in text and word not in seen:
            seen.add(word)
            skills.append(SkillTag(name=word, category=category))

    # JD 同时出现多档学历时取最高档（博士 > 硕士 > 本科 > 大专）
    degree = ""
    for candidate in _DEGREE_PRIORITY:
        if candidate in text:
            degree = candidate
            break

    min_years = None
    for match in _YEARS_PATTERN.finditer(text):
        years = int(match.group(1))
        # 多个年限出现时取最小值（最宽松的要求）
        if min_years is None or years < min_years:
            min_years = years

    result["skills"] = skills
    result["degree"] = degree
    result["min_years"] = min_years
    return result
