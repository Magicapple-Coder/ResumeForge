"""JD 解析的学历、年限和技能规则常量。"""

import re

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
