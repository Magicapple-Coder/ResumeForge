"""岗位相关性筛选使用的常量和不可变结果类型。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# 这些上限是"一份简历"的候选上限，不是资料库的存储上限。
SECTION_LIMITS = {
    "educations": 2,
    "experiences": 3,
    "campus_experiences": 2,
    "projects": 3,
    "skills": 14,
    "awards": 3,
}

SECTION_PRIMARY_FIELDS = {
    "educations": "school",
    "experiences": "company",
    "campus_experiences": "organization",
    "projects": "name",
    "skills": "name",
    "awards": "name",
}

# 岗位方向词只用于低权重的语义补充；硬技能仍然优先使用 JD 技能解析结果。
DOMAIN_SIGNALS: dict[str, tuple[str, ...]] = {
    "ai_algorithm": (
        "算法",
        "机器学习",
        "深度学习",
        "自然语言处理",
        "计算机视觉",
        "大模型",
        "LLM",
        "AIGC",
        "RAG",
        "AI Agent",
        "智能体",
        "推荐系统",
        "多模态",
        "模型训练",
        "推理",
    ),
    "backend": (
        "后端",
        "服务端",
        "微服务",
        "分布式",
        "高并发",
        "接口开发",
        "服务开发",
        "数据库",
        "系统设计",
    ),
    "frontend_client": (
        "前端",
        "客户端",
        "移动端",
        "桌面端",
        "Web 开发",
        "界面开发",
        "交互开发",
    ),
    "data": (
        "数据分析",
        "数据工程",
        "数据挖掘",
        "商业分析",
        "指标体系",
        "数据可视化",
    ),
    "product_operations": (
        "产品经理",
        "产品运营",
        "用户研究",
        "需求分析",
        "竞品分析",
        "活动策划",
        "内容运营",
        "增长运营",
        "用户增长",
    ),
    "testing": ("测试开发", "软件测试", "自动化测试", "质量保证", "测试工程师"),
}

# 这类词能强化已经识别出的方向，但过于宽泛，不能单独把 JD 归到某个方向。
DOMAIN_CONTEXT_SIGNALS: dict[str, tuple[str, ...]] = {
    "product_operations": ("活动", "内容", "推广", "公众号", "宣传", "协作"),
}

# 当 JD 没有明确写出某个技能，但岗位方向很明确时，用于给技能一个较小的
# 先验分数。这里只放常见类别，不会压过 JD 中的直接技能命中。
SKILL_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "ai_algorithm": (
        "Python",
        "PyTorch",
        "TensorFlow",
        "机器学习",
        "深度学习",
        "NLP",
        "LLM",
        "大模型",
        "Transformer",
        "RAG",
    ),
    "backend": (
        "Python",
        "Java",
        "Go",
        "C++",
        "FastAPI",
        "Django",
        "Spring Boot",
        "MySQL",
        "Redis",
        "Docker",
        "Linux",
    ),
    "frontend_client": (
        "JavaScript",
        "TypeScript",
        "React",
        "Vue",
        "Flutter",
        "Electron",
        "CSS3",
        "HTML5",
    ),
    "data": (
        "Python",
        "SQL",
        "MySQL",
        "Spark",
        "Flink",
        "数据分析",
        "数据挖掘",
    ),
    "product_operations": (
        "用户研究",
        "活动策划",
        "内容运营",
        "Excel",
        "Figma",
        "数据分析",
    ),
    "testing": ("Python", "Java", "Selenium", "自动化测试", "接口测试"),
}

_TITLE_SPLIT_RE = re.compile(r"[\s\-_/|,，、；;（）()：:]+")
_ASCII_TERM_RE = re.compile(r"[A-Za-z]")
_LIST_DETAIL_FIELDS = ("courses", "achievements", "description", "highlights")
_OPTIONAL_TOP_LEVEL_FIELDS = ("summary", "github", "personal_website", "target_city")
_LLM_PROFILE_FIELDS = (
    "target_city",
    "job_intent",
    "summary",
    "educations",
    "experiences",
    "campus_experiences",
    "projects",
    "skills",
    "awards",
)
_MIN_PROFILE_CONTEXT_CHARS = 1_000
_REFERENCE_SECTIONS = ("educations", "experiences", "campus_experiences", "projects")
_REFERENCE_CONTENT_KEY = "_reference_content"
_REFERENCE_FILE_KEY = "_reference_file_name"
_REFERENCE_EXCERPT_MAX_CHARS = 1_800
_REFERENCE_FACT_MAX_CHARS = 320
_REFERENCE_FACT_LIMIT = 5
_REFERENCE_INSTRUCTION_RE = re.compile(
    r"(?:忽略|绕过).{0,24}(?:系统|规则|指令|要求|限制)|"
    r"(?:系统|开发者|用户)\s*(?:消息|指令)|"
    r"(?:执行|遵循).{0,16}(?:以下|上述|本文).{0,8}(?:命令|指令)|"
    r"(?:虚构|编造).{0,24}(?:经历|成绩|成果|数据|数字)|"
    r"(?:请勿|不要|无需).{0,24}(?:虚构|编造|弱化|执行)",
    re.IGNORECASE,
)
_REFERENCE_META_RE = re.compile(
    r"用途说明|事实性总结|供后续|简历(?:包装|优化|措辞)|"
    r"面试(?:准备|要点)|可直接(?:提炼|引用|使用)|不是(?:系统|用户)指令",
    re.IGNORECASE,
)
_MARKDOWN_LIST_PREFIX_RE = re.compile(r"^(?:[-+*]\s+|\d+(?:[.)、]|、)\s*)")
_MARKDOWN_TABLE_DIVIDER_RE = re.compile(r"^:?-{3,}:?$")


@dataclass(frozen=True)
class JobFocus:
    """从岗位标题/JD 中提取的可解释匹配信号。"""

    skills: tuple[str, ...]
    domains: tuple[str, ...]
    terms: tuple[str, ...]


@dataclass(frozen=True)
class ProfileSelection:
    """候选资料及其诊断信息。``serialized`` 一定是完整合法 JSON。"""

    data: dict[str, Any]
    serialized: str
    focus: JobFocus
    selected_counts: dict[str, int]
    omitted_counts: dict[str, int]
