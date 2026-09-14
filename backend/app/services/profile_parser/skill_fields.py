"""个人资料技能字段的拆分、别名规范化和等级解析。"""

import re

from .skill_constants import _SKILL_LEADING_LEVEL_RE, _SKILL_LEVEL_RE
from .normalization import _clean_line


def _split_tokens(value: str) -> list[str]:
    # 斜杠通常是分隔符，但 CI/CD 是一个完整技能；先保护它，避免被拆成
    # 两个无意义的 “CI”/“CD” 标签。
    protected = re.sub(r"\bCI\s*/\s*CD\b", "CI_CD", value, flags=re.IGNORECASE)
    return [
        token.strip().replace("CI_CD", "CI/CD").replace("ci_cd", "CI/CD")
        for token in re.split(
            r"[,，、/|｜;；&\n]+|\s+(?:and|以及|及)\s+",
            protected,
            flags=re.IGNORECASE,
        )
        if token.strip()
    ]


def _normalize_skill_name(value: str) -> str:
    """保留用户的自定义技能，同时统一高置信度的常见技术写法。"""
    compact = re.sub(r"[\s._-]+", "", value).casefold()
    if re.fullmatch(r"python3\d{0,2}", compact):
        return "Python"
    if re.fullmatch(r"java(?:8|11|17|21)", compact):
        return "Java"
    if re.fullmatch(r"(?:react|vue)\d{1,2}", compact):
        return "React" if compact.startswith("react") else "Vue"
    if re.fullmatch(r"ci/cd(?:pipelines?)?", compact):
        return "CI/CD"
    aliases = {
        "py": "Python",
        "python3": "Python",
        "python语言": "Python",
        "golang": "Go",
        "go语言": "Go",
        "cpp": "C++",
        "c++语言": "C++",
        "js": "JavaScript",
        "javascript": "JavaScript",
        "javascript语言": "JavaScript",
        "typescript": "TypeScript",
        "typescript语言": "TypeScript",
        "reactjs": "React",
        "react16": "React",
        "react17": "React",
        "react18": "React",
        "reactnative": "React Native",
        "vuejs": "Vue",
        "vue2": "Vue",
        "vue3": "Vue",
        "angularjs": "Angular",
        "nodejs": "Node.js",
        "nextjs": "Next.js",
        "sveltejs": "Svelte",
        "tailwindcss": "Tailwind CSS",
        "html5": "HTML5",
        "html": "HTML5",
        "css3": "CSS3",
        "css": "CSS3",
        "springboot": "Spring Boot",
        "springcloud": "Spring Cloud",
        "mybatis": "MyBatis",
        "django": "Django",
        "flask": "Flask",
        "expressjs": "Express",
        "mysql数据库": "MySQL",
        "mysql8": "MySQL",
        "mysql": "MySQL",
        "postgres": "PostgreSQL",
        "postgresql数据库": "PostgreSQL",
        "postgresql": "PostgreSQL",
        "sqlite3": "SQLite",
        "sqlite": "SQLite",
        "mongodb": "MongoDB",
        "mongo": "MongoDB",
        "rabbitmq": "RabbitMQ",
        "apachekafka": "Kafka",
        "kafka": "Kafka",
        "redis": "Redis",
        "elasticsearch": "Elasticsearch",
        "websocket": "WebSocket",
        "grpc": "gRPC",
        "k8s": "Kubernetes",
        "kubernetes": "Kubernetes",
        "vue": "Vue",
        "react": "React",
        "fastapi": "FastAPI",
        "pytorch": "PyTorch",
        "torch": "PyTorch",
        "tensorflow": "TensorFlow",
        "tf": "TensorFlow",
        "opencv": "OpenCV",
        "cv2": "OpenCV",
        "sklearn": "Scikit-learn",
        "scikitlearn": "Scikit-learn",
        "xgboost": "XGBoost",
        "机器学习": "机器学习",
        "深度学习": "深度学习",
        "自然语言处理": "自然语言处理",
        "nlp": "自然语言处理",
        "计算机视觉": "计算机视觉",
        "机器视觉": "计算机视觉",
        "cv": "计算机视觉",
        "大语言模型": "大模型",
        "大型语言模型": "大模型",
        "llm": "大模型",
        "检索增强生成": "RAG",
        "检索增强": "RAG",
        "rag": "RAG",
        "智能体": "Agent",
        "aigc": "AIGC",
        "生成式人工智能": "AIGC",
        "生成式ai": "AIGC",
        "docker": "Docker",
        "linux": "Linux",
        "git": "Git",
        "terraform": "Terraform",
        "microservices": "微服务",
        "微服务架构": "微服务",
        "distributedsystems": "分布式",
        "分布式系统": "分布式",
        "restapi": "RESTful",
        "restfulapi": "RESTful",
        "csharp": "C#",
        "dotnet": ".NET",
        "net": ".NET",
        "sql": "SQL",
        "cicd": "CI/CD",
        "ci/cd": "CI/CD",
        "ci/cdpipelines": "CI/CD",
        "devops": "DevOps",
    }
    return aliases.get(compact, value.strip())


def _skill_name_and_level(token: str, inherited_level: str = "") -> tuple[str, str]:
    """支持括号、前后缀和破折号等技能等级表述。"""
    clean = token.strip().strip("-—–－:：")
    clean = re.sub(r"\s*等(?:编程语言|开发语言|技术|工具|框架)?$", "", clean).strip()
    if not clean:
        return "", ""

    bracketed = re.match(r"^(?P<name>.+?)[（(]\s*(?P<level>[^()（）]+?)\s*[）)]$", clean)
    if bracketed and _SKILL_LEVEL_RE.fullmatch(bracketed.group("level").strip()):
        return _normalize_skill_name(bracketed.group("name")), bracketed.group("level").strip()

    trailing = re.match(
        r"^(?P<name>.+?)\s*(?:[-—–－:：]|\s+)\s*(?P<level>熟练掌握|熟练使用|熟练|精通|掌握|熟悉|了解|入门|精通使用|proficient|advanced|intermediate|beginner|basic)$",
        clean,
        re.IGNORECASE,
    )
    if trailing:
        return _normalize_skill_name(trailing.group("name")), trailing.group("level")

    leading = _SKILL_LEADING_LEVEL_RE.match(clean)
    if leading:
        return _normalize_skill_name(leading.group("skills")), leading.group("level")
    return _normalize_skill_name(clean), inherited_level


def _parse_skills(lines: list[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    indices_by_name: dict[str, int] = {}
    for line in lines:
        clean = _clean_line(line)
        if not clean:
            continue
        label_match = re.match(r"^([^：:]{1,32})\s*[:：]\s*(.+)$", clean)
        label_key = label_match.group(1).casefold() if label_match else ""
        if label_match and any(
            term.casefold() in label_key
            for term in (
                "技能",
                "技术",
                "语言",
                "工具",
                "框架",
                "数据库",
                "中间件",
                "前端",
                "后端",
                "云原生",
                "人工智能",
                "机器学习",
                "自然语言",
                "计算机视觉",
                "大模型",
                "certification",
                "certifications",
                "technical",
                "tech",
                "technology",
                "expertise",
                "proficiencies",
                "programming",
                "language",
                "languages",
                "database",
                "framework",
                "frontend",
                "backend",
                "cloud",
                "tools",
            )
        ):
            clean = label_match.group(2)
        inherited_level = ""
        leading_level = _SKILL_LEADING_LEVEL_RE.match(clean)
        if leading_level:
            inherited_level = leading_level.group("level")
            clean = leading_level.group("skills")
        for token in _split_tokens(clean):
            name, level = _skill_name_and_level(token, inherited_level)
            key = name.casefold()
            if not name or len(name) > 64:
                continue
            existing_index = indices_by_name.get(key)
            if existing_index is None:
                indices_by_name[key] = len(result)
                result.append({"name": name, "level": level})
            elif level and not result[existing_index]["level"]:
                # 同一技能在“技能清单”和“熟练程度”两处都出现时，保留更完整的等级。
                result[existing_index]["level"] = level
    return result
