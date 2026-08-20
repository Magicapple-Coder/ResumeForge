"""JD 文本解析：基于规则提取技能标签、学历要求与年限要求。

不依赖大模型，离线可用、零成本，用于岗位卡片的标签展示与搜索辅助。
规范技能词典位于 data/skills.json；常见缩写和等价表达在本模块中映射回词典名。
"""

import json
import re
import unicodedata
from pathlib import Path

from ..schemas.job import SkillTag

SKILLS_PATH = Path(__file__).resolve().parent.parent / "data" / "skills.json"

# 学历按优先级排序，JD 同时出现多档时取最高档。别名单独列出，避免把
# “研究生/学士”等常见写法漏掉。
_DEGREE_PATTERNS = (
    (
        "博士",
        ("博士", "博士研究生", "博士学历", "phd", "ph.d.", "ph.d", "doctorate"),
    ),
    (
        "硕士",
        (
            "硕士",
            "硕士研究生",
            "研究生",
            "研究生学历",
            "master's degree",
            "master degree",
            "master of science",
            "master of engineering",
            "master of arts",
            "m.s.",
            "m.s",
            "msc",
            "m.sc.",
            "m.eng",
            "meng",
        ),
    ),
    (
        "本科",
        (
            "本科",
            "大学本科",
            "学士",
            "本科学历",
            "bachelor's degree",
            "bachelor degree",
            "bachelor of science",
            "bachelor of engineering",
            "bachelor of arts",
            "undergraduate degree",
            "b.s.",
            "b.s",
            "bs",
            "bsc",
            "b.sc.",
            "b.eng",
            "beng",
        ),
    ),
    (
        "大专",
        ("大专", "专科", "高职", "大专学历", "associate degree", "a.s.", "a.s"),
    ),
)

# 常见写法包括“3年以上”“至少 3 年”“3+ years”“3年起”以及“3-5 年”。
# 前置的数字边界很重要：不能从“2026年”或“100年以上”的后缀回溯出
# “26 年”/“0 年”。
_YEARS_PATTERN = re.compile(
    r"(?<!\d)(?:至少\s*)?(?P<years>\d{1,3})(?!\d)"
    r"(?:\s*[-~～至到]\s*(?P<upper>\d{1,3})|\s+to\s+(?P<upper_words>\d{1,3}))?\s*"
    r"(?:\+\s*(?:年|years?|yrs?)?|年(?:以上|及以上|起)?|years?|yrs?)"
    r"(?!级)",
    re.IGNORECASE,
)
_CHINESE_YEARS_PATTERN = re.compile(
    r"(?P<years>[一二两三四五六七八九十百]+)"
    r"(?:\s*[至到\-~～]\s*(?P<upper>[一二两三四五六七八九十百]+))?\s*"
    r"年(?:以上|及以上|起)?(?!级)"
)
_ENGLISH_WORD_YEARS_PATTERN = re.compile(
    r"\b(?P<years>one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:years?|yrs?)\b",
    re.IGNORECASE,
)


# 招聘网站经常使用缩写、带 .js 后缀的写法或中文译名。值为规范化后展示
# 的技能名；只增加高置信度别名，避免把泛化词（如“开发”）误当成技能。
_SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "Python": ("py", "python3", "python 3", "python语言"),
    "Java": ("java语言", "java开发", "java 8", "java8", "java 11", "java11"),
    "Go": ("golang", "go语言"),
    "C++": ("cpp", "c plus plus", "c++语言", "c/c++"),
    "C": ("c语言", "c language"),
    "C#": ("c sharp", "csharp"),
    ".NET": ("dotnet", ".net core", "net core"),
    "SQL": ("sql语言", "structured query language"),
    "JavaScript": ("js", "java script", "ecmascript", "javascript语言"),
    "TypeScript": ("ts", "type script", "typescript语言"),
    "React": ("react.js", "reactjs", "react js", "react16", "react17", "react18", "react 18"),
    "Vue": ("vue.js", "vuejs", "vue js", "vue2", "vue3", "vue 3"),
    "Angular": ("angular.js", "angularjs", "angular js"),
    "Next.js": ("nextjs", "next js"),
    "Svelte": ("svelte.js", "sveltejs"),
    "Tailwind CSS": ("tailwindcss", "tailwind"),
    "HTML5": ("html", "html 5"),
    "CSS3": ("css", "css 3"),
    "Node.js": ("nodejs", "node js"),
    "小程序": ("微信小程序", "mini program", "mini-program"),
    "Electron": ("electron.js", "electronjs"),
    "Spring Boot": ("springboot", "spring boot开发"),
    "Spring Cloud": ("springcloud", "spring cloud开发"),
    "FastAPI": ("fast api", "fast-api", "fastapi framework"),
    "MyBatis": ("my batis",),
    "Express": ("express.js", "expressjs"),
    "MySQL": ("mysql数据库", "mysql database", "mysql8", "mysql 8"),
    "PostgreSQL": ("postgres", "postgresql数据库", "postgre sql", "postgre-sql"),
    "SQLite": ("sqlite3",),
    "MongoDB": ("mongo", "mongodb数据库"),
    "Redis": ("redis数据库",),
    "Kafka": ("apache kafka",),
    "RabbitMQ": ("rabbit mq",),
    "Elasticsearch": ("elastic search", "es检索"),
    "Kubernetes": ("k8s", "kubernetes集群"),
    "CI/CD": ("cicd", "ci cd", "持续集成", "持续交付", "持续集成持续部署"),
    "机器学习": ("machine learning", "ml算法"),
    "深度学习": ("deep learning", "dl算法"),
    "自然语言处理": ("natural language processing", "语言模型处理"),
    "NLP": ("nlp技术",),
    "计算机视觉": ("computer vision", "cv算法", "机器视觉"),
    "CV": ("cv技术",),
    "大模型": ("大语言模型", "大型语言模型", "foundation model", "基础模型"),
    "LLM": ("large language model", "llm模型"),
    "RAG": ("检索增强生成", "检索增强", "retrieval augmented generation"),
    "Agent": ("智能体", "ai agent", "agent开发"),
    "AIGC": ("生成式ai", "生成式 ai", "生成式人工智能", "generative ai"),
    "Embedding": ("向量嵌入", "文本向量化"),
    "PyTorch": ("pytorch框架", "py torch", "py-torch", "torch"),
    "TensorFlow": ("tensorflow框架",),
    "OpenCV": ("opencv库", "cv2"),
    "Scikit-learn": ("sklearn", "scikit learn"),
    "XGBoost": ("xgboost算法",),
    "LangChain": ("lang chain",),
    "微服务": ("microservices", "微服务架构"),
    "分布式": ("distributed systems", "分布式系统"),
    "高并发": ("high concurrency",),
    "消息队列": ("message queue", "mq"),
    "RESTful": ("rest api", "restful api"),
    "WebSocket": ("web socket",),
    "Docker": ("docker容器", "containerization"),
    "Linux": ("linux系统",),
    "Git": ("git版本控制",),
    "DevOps": ("dev ops",),
    "Terraform": ("terraform基础设施",),
    "Excel": ("microsoft excel", "ms excel", "电子表格"),
    "PowerPoint": ("microsoft powerpoint", "power point", "ppt"),
    "Power BI": ("powerbi",),
    "CAD": ("cad制图",),
    "AutoCAD": ("auto cad",),
    "SolidWorks": ("solid works",),
    "供应链管理": ("供应链运营", "supply chain management"),
    "仓储管理": ("仓库管理", "warehouse management"),
    "物流管理": ("运输管理", "logistics management"),
    "质量管理": ("品质管理", "quality management"),
    "临床护理": ("临床照护", "clinical nursing"),
    "教师资格证": ("教师资格", "teacher certification"),
    "执业医师资格证": ("医师资格证", "医师执业证"),
    "护士执业资格证": ("护士资格证", "护士执业证"),
    "法律职业资格证": ("法考证书", "法律职业资格"),
    "注册会计师": ("cpa证书", "certified public accountant"),
    "焊工证": ("焊工资格证",),
    "电工证": ("电工资格证",),
    "数据结构": ("data structures",),
    "算法": ("algorithms",),
    "操作系统": ("operating systems",),
    "计算机网络": ("computer networks", "网络基础"),
}

# 词典历史上保留了部分中英文/缩写词作为独立展示项。解析时统一为一个
# 规范名，避免“计算机视觉 + CV”或“Kubernetes + K8s”重复占用标签位置。
_SKILL_CANONICAL_OVERRIDES = {
    "CV": "计算机视觉",
    "K8s": "Kubernetes",
    "LLM": "大模型",
    "NLP": "自然语言处理",
}


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
