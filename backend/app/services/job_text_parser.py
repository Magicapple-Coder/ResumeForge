"""将招聘页面复制出的纯文本解析为可编辑的岗位草稿。

解析器刻意只使用本地、可解释的规则：识别不到的内容留空，交给用户在
创建岗位前确认。它不访问网络，也不直接写数据库。
"""

import re

from ..schemas.job import JobTextParseResult


_FIELD_LIMITS = {
    "title": 128,
    "company": 128,
    "location": 64,
    "salary": 64,
    "job_type": 32,
    "source_url": 512,
    "posted_at": 32,
    "status": 16,
}

_LABELS = {
    "title": (
        "职位名称",
        "岗位名称",
        "招聘职位名称",
        "招聘岗位名称",
        "职位名",
        "岗位名",
        "招聘职位名",
        "招聘岗位名",
        "招聘职位",
        "招聘岗位",
        "职位标题",
        "岗位标题",
        "职位",
        "岗位",
        "job title",
        "position title",
        "position name",
        "position",
        "title",
        "role",
        "job",
    ),
    "company": (
        "公司名称",
        "企业名称",
        "企业",
        "招聘公司",
        "招聘企业",
        "招聘主体",
        "所属公司",
        "所属企业",
        "公司主体",
        "企业主体",
        "用人单位",
        "任职单位",
        "雇主",
        "公司",
        "employer",
        "employer name",
        "enterprise",
        "organization",
        "organisation",
        "organization name",
        "company",
        "company name",
    ),
    "location": (
        "工作地点",
        "工作地址",
        "工作城市",
        "办公地点",
        "办公城市",
        "职位地点",
        "职位城市",
        "岗位地点",
        "所在城市",
        "工作地",
        "工作区域",
        "地点",
        "城市",
        "work location",
        "location",
        "city",
        "office",
    ),
    "salary": (
        "薪资范围",
        "薪资待遇",
        "薪酬待遇",
        "薪资福利",
        "薪酬福利",
        "薪酬范围",
        "工资待遇",
        "月薪范围",
        "年薪范围",
        "薪酬",
        "薪资",
        "月薪",
        "年薪",
        "salary range",
        "compensation",
        "salary",
        "pay",
    ),
    "job_type": (
        "招聘类型",
        "职位类型",
        "岗位类型",
        "工作性质",
        "岗位性质",
        "职位性质",
        "用工性质",
        "用工形式",
        "雇佣类型",
        "工作形式",
        "合同类型",
        "招聘形式",
        "用工类型",
        "employment type",
        "job type",
        "position type",
        "work type",
        "contract type",
    ),
    "source_url": (
        "投递链接",
        "申请链接",
        "职位链接",
        "岗位链接",
        "招聘链接",
        "官网链接",
        "官网投递链接",
        "网申地址",
        "申请网址",
        "官网地址",
        "职位详情链接",
        "详情链接",
        "链接",
        "URL",
        "apply url",
        "application url",
        "job url",
        "job link",
        "career url",
        "link",
    ),
    "posted_at": (
        "发布时间",
        "发布日期",
        "发布于",
        "posted date",
        "date posted",
        "published",
        "posted",
    ),
    "status": (
        "招聘状态",
        "职位状态",
        "岗位状态",
        "招聘进度",
        "招聘有效期",
        "状态",
        "job status",
        "hiring status",
        "status",
    ),
}

_ENGLISH_LABELS_REQUIRING_COLON = frozenset(
    {
        "job",
        "company",
        "enterprise",
        "title",
        "position",
        "role",
        "posted",
        "updated",
        "status",
        "link",
    }
)


def _compile_label_pattern(labels: tuple[str, ...]) -> re.Pattern[str]:
    ordered = sorted(labels, key=len, reverse=True)
    alternatives = "|".join(re.escape(label) for label in ordered)
    # 部分单词型英文标签（如 ``job``/``company``）很容易成为章节标题的前缀，
    # 例如 ``Job Description``。这些高歧义标签只接受冒号形式；中文、多词
    # 标签和低歧义英文标签继续兼容“标签 值”的复制格式。
    spaced_labels = [
        label
        for label in ordered
        if not (
            re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", label)
            and label.casefold() in _ENGLISH_LABELS_REQUIRING_COLON
        )
    ]
    if not spaced_labels:
        return re.compile(rf"^(?:{alternatives})\s*[:：]\s*(?P<value>.+?)\s*$", re.IGNORECASE)
    spaced_alternatives = "|".join(re.escape(label) for label in spaced_labels)
    return re.compile(
        rf"^(?:(?:{alternatives})\s*[:：]\s*|(?:{spaced_alternatives})\s+)"
        r"(?P<value>.+?)\s*$",
        re.IGNORECASE,
    )


_LABEL_PATTERNS = {field: _compile_label_pattern(labels) for field, labels in _LABELS.items()}


def _compile_inline_label_pattern(
    labels: tuple[str, ...],
) -> tuple[re.Pattern[str], frozenset[str]]:
    """预编译卡片内联字段匹配器，避免大段文本逐行重复构造正则。"""
    ordered = sorted(labels, key=len, reverse=True)
    alternatives = "|".join(re.escape(label) for label in ordered)
    colon_only = frozenset(
        label.casefold()
        for label in ordered
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", label)
        and label.casefold() in _ENGLISH_LABELS_REQUIRING_COLON
    )
    return (
        re.compile(
            rf"(?<![A-Za-z0-9_])(?P<label>{alternatives})(?P<separator>"
            r"\s*[:：]\s*|\s+)",
            re.IGNORECASE,
        ),
        colon_only,
    )


_INLINE_LABEL_PATTERNS = {
    field: _compile_inline_label_pattern(labels) for field, labels in _LABELS.items()
}


def _inline_label_matches(line: str) -> list[tuple[int, int, str, str]]:
    """找出同一行中的多个字段标签，避免把后续字段吞进前一个值。

    招聘网站的卡片文本经常把元信息压成 ``公司：A 职位：B 地点：C``；
    逐行使用带锚点的字段正则只能识别第一个字段，因此这里先收集标签
    位置，再用下一个标签作为当前值的结束边界。
    """
    matches: list[tuple[int, int, str, str]] = []
    for field, (pattern, colon_only) in _INLINE_LABEL_PATTERNS.items():
        for match in pattern.finditer(line):
            if (
                match.group("label").casefold() in colon_only
                and ":" not in match.group("separator")
                and "：" not in match.group("separator")
            ):
                continue
            matches.append((match.start(), match.end(), field, match.group("label")))

    # 同一位置可能同时匹配短/长别名（如“公司”与“公司名称”）；保留最长的
    # 一个，随后按原文位置排序，确保字段值边界稳定。
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str, str]] = []
    for match in matches:
        if selected and match[0] < selected[-1][1]:
            continue
        selected.append(match)
    return selected


_SECTION_NUMBER_PREFIX = r"(?:(?:第\s*)?(?:\d{1,3}|[一二三四五六七八九十百]+)\s*[、.)）.]\s*)?"
# 招聘官网常把章节名渲染为 Markdown 标题或视觉标签。将这些展示包装从
# 实际章节名中剥离，既能覆盖复制文本，又不会放宽普通岗位标题的识别条件。
_SECTION_HEADING_PREFIX = r"(?:#{1,6}\s*)?(?:[【［\[]\s*)?"
_SECTION_HEADING_SUFFIX = r"\s*(?:[】］\]])?"
_DESCRIPTION_HEADINGS = (
    r"(?:职位描述|岗位描述|工作描述|岗位职责|职位职责|工作职责|职责描述|工作内容|岗位内容|"
    r"主要职责|岗位职责说明|职位职责说明|工作职责与内容|工作内容及职责|职位概述|岗位概述|"
    r"职位职责与内容|岗位职责与工作内容|职责与工作内容|"
    r"你将负责|你将参与|what\s+you(?:'|’)ll\s+do|what\s+you\s+will\s+do|"
    r"key\s+responsibilities|your\s+responsibilities|job\s+description|"
    r"job\s+responsibilities|description|duties|about\s+the\s+role|"
    r"role\s+overview|position\s+overview|responsibilities|"
    r"what\s+you\s+do|key\s+duties|responsibilities\s*(?:&|and)\s*duties)"
)
_REQUIREMENTS_HEADINGS = (
    r"(?:职位要求|岗位要求|任职要求|任职资格|岗位资格|职位资格|任职条件|岗位条件|招聘要求|能力要求|"
    r"任职要求与条件|任职资格与要求|岗位要求与条件|应聘要求|资格要求|必备条件|"
    r"任职资格与条件|岗位要求与职责|"
    r"我们希望你|我们期待你|what\s+you(?:'|’)ll\s+bring|what\s+you\s+will\s+bring|"
    r"what\s+we(?:'|’)re\s+looking\s+for|what\s+we\s+are\s+looking\s+for|"
    r"job\s+requirements|job\s+qualifications|what\s+you\s+bring|"
    r"what\s+you\s+need|your\s+qualifications|requirements|qualifications|"
    r"preferred\s+qualifications|must\s+have|"
    r"who\s+you\s+are|preferred\s+skills|qualifications\s*(?:&|and)\s+skills)"
)
_SECTION_SEPARATOR = r"(?:\s*[:：]\s*|\s+|$)"

_DESCRIPTION_HEADING_RE = re.compile(
    rf"^{_SECTION_HEADING_PREFIX}{_SECTION_NUMBER_PREFIX}{_DESCRIPTION_HEADINGS}"
    rf"{_SECTION_HEADING_SUFFIX}{_SECTION_SEPARATOR}(?P<content>.*)$",
    re.IGNORECASE,
)
_REQUIREMENTS_HEADING_RE = re.compile(
    rf"^{_SECTION_HEADING_PREFIX}{_SECTION_NUMBER_PREFIX}{_REQUIREMENTS_HEADINGS}"
    rf"{_SECTION_HEADING_SUFFIX}{_SECTION_SEPARATOR}(?P<content>.*)$",
    re.IGNORECASE,
)
_ADDITIONAL_HEADINGS = (
    r"(?:福利待遇|福利与待遇|薪资福利|员工福利|福利说明|公司介绍|企业介绍|公司简介|企业简介|"
    r"公司概况|关于我们|团队介绍|部门介绍|工作环境|联系方式|联系我们|投递方式|申请方式|"
    r"招聘流程|面试流程|申请流程|如何申请|投递须知|招聘须知|其他信息|补充信息|岗位信息|"
    r"工作安排|公司概览|company\s+overview|benefits?|perks?|about\s+(?:the\s+)?company|"
    r"about\s+us|team\s+introduction|contact\s+us|how\s+to\s+apply|application\s+process|"
    r"interview\s+process|additional\s+information|other\s+information)"
)
_ADDITIONAL_HEADING_RE = re.compile(
    rf"^{_SECTION_HEADING_PREFIX}{_SECTION_NUMBER_PREFIX}(?P<heading>{_ADDITIONAL_HEADINGS})"
    rf"{_SECTION_HEADING_SUFFIX}{_SECTION_SEPARATOR}(?P<content>.*)$",
    re.IGNORECASE,
)
_INLINE_SECTION_RE = re.compile(
    rf"(?:^|(?<=[。；，,;！？!?.\s]))\s*{_SECTION_HEADING_PREFIX}{_SECTION_NUMBER_PREFIX}"
    rf"(?P<heading>{_DESCRIPTION_HEADINGS}|{_REQUIREMENTS_HEADINGS}|{_ADDITIONAL_HEADINGS})"
    rf"{_SECTION_HEADING_SUFFIX}{_SECTION_SEPARATOR}",
    re.IGNORECASE,
)

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_JOB_ID_RE = re.compile(
    r"^(?:(?:职位|岗位|Job|Position)\s*(?:ID|编号|编码)|Req(?:uisition)?\s*ID)\s*[:：#]?\s*\S+",
    re.IGNORECASE,
)
_SALARY_RE = re.compile(
    r"(?:薪资|薪酬|工资|月薪|年薪)?\s*(?:面议|可面议|待定|保密)|"
    r"(?:[$€£￥¥]\s*)?\d+(?:\.\d+)?\s*(?:[kKwW万千元])?\s*"
    r"(?:-|~|～|—|–|至)\s*(?:[$€£￥¥]\s*)?\d+(?:\.\d+)?\s*(?:[kKwW万千元])"
    r"(?:\s*/\s*(?:月|年|天|日|小时))?(?:\s*[·xX*]\s*\d{1,2}\s*薪)?|"
    r"(?:薪资|薪酬|工资|月薪|年薪)?\s*(?:[$€£￥¥]\s*)?\d+(?:\.\d+)?\s*(?:[kKwW万千元])\s*"
    r"(?:起|以上|/\s*(?:月|年|天|日|小时)|(?:\s*[·xX*]\s*\d{1,2}\s*薪)?(?=\s*(?:$|[|｜·,，;；/\\])))|"
    # 卡片常只显示单个数字（如 ``30K`` 或 ``$120K``），此分支要求有
    # 明确的金额单位，避免把普通年份/编号误当薪资。
    r"(?:[$€£￥¥]\s*)?\d+(?:\.\d+)?\s*[kKwW万千元](?:\s*[·xX*]\s*\d{1,2}\s*薪)?"
)
_PUBLISHED_DATE_RE = re.compile(
    r"(?:发布于|发布日期?|发布时间|posted\s+date|date\s+posted|published)\s*[:：]?\s*"
    r"(?P<date>\d{4}(?:[./年-]\d{1,2})?(?:[./月-]\d{1,2}日?)?|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+(?:\d{1,2}(?:,)?\s+)?\d{4})",
    re.IGNORECASE,
)
_UPDATED_DATE_RE = re.compile(
    r"^(?:更新于|更新日期|更新时间|updated|last\s+updated)\s*[:：]?\s*\S+",
    re.IGNORECASE,
)

_TITLE_TERMS = (
    "工程师",
    "开发",
    "算法",
    "研究员",
    "架构师",
    "设计师",
    "分析师",
    "产品经理",
    "项目经理",
    "运营",
    "测试",
    "研发",
    "顾问",
    "专员",
    "管培生",
    "实习生",
    "科学家",
    "助理",
    "程序员",
    "开发者",
    "技术支持",
    "解决方案",
    "数据科学",
    "用户研究",
    "售前",
    "采购",
    "财务",
    "法务",
    "人力",
    "经理",
    "主管",
    "总监",
    "销售",
    "市场",
    "客服",
    "编辑",
    "文案",
    "讲师",
    "律师",
    "审计",
    "行政",
    "秘书",
    "运营岗",
    "医生",
    "医师",
    "护士",
    "药师",
    "治疗师",
    "检验师",
    "护理",
    "教师",
    "老师",
    "教务",
    "辅导员",
    "班主任",
    "操作工",
    "技术员",
    "技工",
    "电工",
    "焊工",
    "钳工",
    "车工",
    "机修",
    "质检",
    "品管",
    "工艺员",
    "生产计划",
    "店员",
    "店长",
    "导购",
    "收银员",
    "理货员",
    "营业员",
    "司机",
    "配送员",
    "快递员",
    "仓管",
    "仓库管理员",
    "调度员",
    "施工员",
    "造价员",
    "安全员",
    "监理",
    "测量员",
    "厨师",
    "服务员",
    "咖啡师",
    "烘焙师",
    "兽医",
    "农艺师",
    "会计",
    "出纳",
    "翻译",
    "记者",
    "摄影师",
    "主播",
)
_ENGLISH_TITLE_RE = re.compile(
    r"\b(?:engineer|developer|programmer|architect|analyst|designer|"
    r"scientist|researcher|manager|consultant|specialist|intern|operator|"
    r"lead|director|technician|support|sales|recruiter|owner|planner|"
    r"coordinator|administrator|accountant|auditor|writer|editor|"
    r"teacher|lecturer|professor|lawyer|nurse|doctor|physician|pharmacist|"
    r"therapist|mechanic|electrician|welder|machinist|assembler|inspector|"
    r"cashier|merchandiser|driver|courier|dispatcher|chef|barista|waiter|"
    r"veterinarian|surveyor|estimator|foreman|qa|sre|devops)\b",
    re.IGNORECASE,
)
_TITLE_SENTENCE_PREFIX_RE = re.compile(
    r"^(?:负责|参与|熟悉|掌握|具备|要求|我们|团队|协助|能够|拥有|"
    r"we\b|you\b|what\b|our\b|the\b|this\b|looking\s+for\b)",
    re.IGNORECASE,
)
_TITLE_NON_ROLE_PREFIX_RE = re.compile(
    r"^(?:公司|企业|团队|关于我们|福利|薪资福利|联系方式|联系我们|投递方式|申请方式|招聘流程|"
    r"company|team|about\s+(?:us|the\s+company)|benefits?|contact|how\s+to\s+apply)"
    r"(?:介绍|简介|概况|说明|信息)?\s*[:：]",
    re.IGNORECASE,
)
_TITLE_SENTENCE_PREFIXES = (
    "负责",
    "参与",
    "熟悉",
    "掌握",
    "具备",
    "要求",
    "我们",
    "团队",
    "协助",
    "能够",
    "拥有",
)
_COMPANY_TERMS = (
    "公司",
    "集团",
    "银行",
    "研究院",
    "事务所",
    "有限公司",
    "股份",
    "科技",
    "网络",
    "智能",
    "控股",
    "实业",
    "资本",
    "基金",
    "证券",
    "保险",
    "医院",
    "诊所",
    "药房",
    "学校",
    "学院",
    "大学",
    "中学",
    "小学",
    "幼儿园",
    "工厂",
    "制造",
    "物流",
    "商场",
    "超市",
    "门店",
    "律所",
    "设计院",
    "合作社",
    "协会",
    "实验室",
)
_ENGLISH_COMPANY_RE = re.compile(
    r"\b(?:inc\.?|incorporated|ltd\.?|limited|llc|corp\.?|corporation|company|group|holdings)\b",
    re.IGNORECASE,
)
_LOCATION_TERMS = (
    "北京",
    "上海",
    "天津",
    "重庆",
    "深圳",
    "广州",
    "杭州",
    "成都",
    "武汉",
    "西安",
    "南京",
    "苏州",
    "长沙",
    "厦门",
    "合肥",
    "郑州",
    "青岛",
    "济南",
    "大连",
    "宁波",
    "东莞",
    "佛山",
    "珠海",
    "无锡",
    "福州",
    "昆明",
    "南昌",
    "沈阳",
    "石家庄",
    "哈尔滨",
    "香港",
    "澳门",
    "台湾",
    "海外",
    "全国",
    "远程",
    "混合办公",
    "兰州",
    "太原",
    "南宁",
    "海口",
    "贵阳",
    "乌鲁木齐",
    "呼和浩特",
    "温州",
    "常州",
    "嘉兴",
    "绍兴",
    "扬州",
    "Beijing",
    "Shanghai",
    "Tianjin",
    "Chongqing",
    "Shenzhen",
    "Guangzhou",
    "Hangzhou",
    "Chengdu",
    "Wuhan",
    "Nanjing",
    "Suzhou",
    "Remote",
    "Hybrid",
    "Singapore",
    "New York",
)
_NON_LOCATION_TERMS = (
    "负责",
    "要求",
    "经验",
    "学历",
    "招聘",
    "职位",
    "岗位",
    "工程师",
    "薪资",
    "职责",
    "描述",
    "团队",
    "公司",
    "项目",
    "部门",
)
_LOCATION_SUFFIX_RE = re.compile(
    r"^(?:中国\s*)?(?:[\u4e00-\u9fff]{2,12}(?:省|市|自治区|特别行政区|自治州|地区|盟|"
    r"县|区|旗|镇|乡|街道|工业园区)){1,4}$"
)


def _normalize_lines(text: str) -> list[str]:
    # 只归一化全角拉丁字母/数字和空格；招聘正文中的全角标点具有语义和
    # 可读性，不能像 NFKC 那样无差别改成半角（例如“，”变成“,”）。
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
    return [line.strip() for line in normalized.split("\n") if line.strip()]


def _truncate(value: str, field: str) -> str:
    return value.strip()[: _FIELD_LIMITS[field]]


def _find_url(value: str) -> str:
    match = _URL_RE.search(value)
    if match is None:
        return ""
    return match.group(0).rstrip(".,;:!?，。；：！？、)]}）】」』")


def _strip_inline_salary(value: str) -> str:
    """去掉标题卡片中附带的薪资，避免薪资元信息吞掉岗位名。"""
    return _SALARY_RE.sub("", value).strip(" \t|｜·,，;；/\\")


def _looks_like_title(value: str) -> bool:
    candidate = value.strip()
    if not candidate or len(candidate) > 128 or candidate.startswith(_TITLE_SENTENCE_PREFIXES):
        return False
    if _TITLE_NON_ROLE_PREFIX_RE.match(candidate):
        return False
    if _TITLE_SENTENCE_PREFIX_RE.match(candidate):
        return False
    if re.match(r"^[（(]?\d+[、.)）]", candidate):
        return False
    return any(term in candidate for term in _TITLE_TERMS) or bool(
        _ENGLISH_TITLE_RE.search(candidate)
    )


def _looks_like_company(value: str) -> bool:
    return any(term in value for term in _COMPANY_TERMS) or bool(_ENGLISH_COMPANY_RE.search(value))


def _looks_like_company_candidate(value: str) -> bool:
    """判断标题相邻的一行是否可能是品牌/公司名。"""
    candidate = value.strip(" \t|｜·,，;；")
    if not candidate or len(candidate) > _FIELD_LIMITS["company"]:
        return False
    if _looks_like_title(candidate) or _looks_like_location(candidate):
        return False
    if (
        _JOB_ID_RE.match(candidate)
        or _UPDATED_DATE_RE.match(candidate)
        or _ADDITIONAL_HEADING_RE.match(candidate)
    ):
        return False
    if _TITLE_NON_ROLE_PREFIX_RE.match(candidate):
        return False
    if _SALARY_RE.fullmatch(candidate) or _URL_RE.fullmatch(candidate):
        return False
    if re.fullmatch(
        r"(?:正式|全职|兼职|实习|校招|社招|校园招聘|社会招聘|intern(?:ship)?|"
        r"full[- ]?time|part[- ]?time|campus|graduate program)",
        candidate,
        re.IGNORECASE,
    ):
        return False
    if re.search(r"[。！？!?]", candidate) or re.match(r"^[\d#*•·]+", candidate):
        return False
    # 没有公司后缀的短行可能只是“北京团队/研发部门”等岗位元信息；
    # 带“科技/有限公司”等明确公司信号的名称不受此过滤影响。
    if not _looks_like_company(candidate) and (
        any(
            term in candidate
            for term in ("团队", "部门", "研发", "客户端", "技术", "产品", "正式", "全职", "兼职")
        )
        or re.search(
            r"\b(?:team|department|division|business\s+unit|function)\b", candidate, re.IGNORECASE
        )
    ):
        return False
    # “研发 - 客户端”一类部门元信息不是公司名；真正的品牌名通常没有句末标点。
    if re.search(
        r"(?:岗位|职位|工作|招聘|职责|描述|要求|部门|团队|客户端|研发)\s*[-—–/]", candidate
    ):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", candidate))


def _looks_like_internship_marker(value: str) -> bool:
    """判断标题区的一行是否明确表示实习，避免正文偏好语句触发误判。"""
    candidate = value.strip()
    if not candidate:
        return False
    if re.fullmatch(
        r"(?:实习招聘|实习生|岗位实习|职位实习|实习岗位|"
        r"20\d{2}\s*届(?:暑期)?实习招聘|"
        r"intern(?:ship)?(?:\s+(?:program|recruitment|hiring|position|role))?)",
        candidate,
        re.IGNORECASE,
    ):
        return True
    return _looks_like_title(candidate) and bool(
        re.search(r"实习|\bintern(?:ship)?\b", candidate, re.IGNORECASE)
    )


def _split_title_company(value: str) -> tuple[str, str]:
    # 招聘卡片常把公司、岗位、地点、薪资和类型压成一行。先按管道分段
    # 定位真正的岗位片段，避免把后续元信息一起写入 title。
    pipe_parts = [
        part.strip(" \t|｜·,，;；/\\")
        for part in re.split(r"\s*[|丨｜]\s*", value.strip())
        if part.strip(" \t|｜·,，;；/\\")
    ]
    if len(pipe_parts) >= 3:
        title_indices = [index for index, part in enumerate(pipe_parts) if _looks_like_title(part)]
        if len(title_indices) == 1:
            title_index = title_indices[0]
            title = pipe_parts[title_index]
            metadata_terms = ("正式", "全职", "兼职", "实习", "校招", "社招", "intern", "full-time")
            company_candidates = [
                part
                for index, part in enumerate(pipe_parts)
                if index != title_index
                and not re.fullmatch(
                    "|".join(re.escape(term) for term in metadata_terms), part, re.IGNORECASE
                )
                and (_looks_like_company(part) or _looks_like_company_candidate(part))
            ]
            if company_candidates:
                # 通常公司紧邻岗位；若卡片把公司放在岗位后，也能取到最近候选。
                company = min(
                    company_candidates, key=lambda part: abs(pipe_parts.index(part) - title_index)
                )
                return title, company
            return title, ""

    parts = re.split(
        r"\s+(?:[-—–|｜@])\s+|\s*[|丨｜]\s*",
        value.strip(),
        maxsplit=1,
    )
    if len(parts) != 2 and re.search(r"\s+[/／]\s+", value):
        slash_parts = re.split(r"\s+[/／]\s+", value.strip(), maxsplit=1)
        # Slash is common inside role names (``AI / ML``); only treat it as
        # a company separator when the left side has a company signal.
        if len(slash_parts) == 2 and _looks_like_company(slash_parts[0]):
            parts = slash_parts
    if len(parts) != 2:
        # 中文招聘卡片常把“公司-岗位”复制成无空格形式。只在连字符两侧
        # 至少有一侧包含中文时尝试拆分，避免把 ``AI-powered`` 这类英文岗位
        # 内部连字符误当成公司分隔符。
        parts = re.split(
            r"(?<=[\u4e00-\u9fff])[-—–](?=[\u4e00-\u9fffA-Za-z])|"
            r"(?<=[A-Za-z])[-—–](?=[\u4e00-\u9fff])",
            value.strip(),
            maxsplit=1,
        )
    if len(parts) != 2:
        parts = re.split(r"(?<=[A-Za-z])[-—–](?=[A-Za-z])", value.strip(), maxsplit=1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        return value.strip(), ""

    left, right = (part.strip(" \t|｜·,，;；/\\") for part in parts)
    # “公司 - 岗位”只在左侧具有明显公司特征时反转；品牌名和技术名都可能很短，
    # 因此右侧像岗位、左侧不像岗位时，也按“公司 - 岗位”处理。
    if _looks_like_title(right) and (_looks_like_company(left) or not _looks_like_title(left)):
        return right, left
    # 两侧都像岗位名时通常是岗位自身的英文/方向分隔（例如
    # ``Backend Engineer - Software Engineer``），不要把右侧误填为公司。
    if (
        _looks_like_title(left)
        and _looks_like_title(right)
        and not (_looks_like_company(left) or _looks_like_company(right))
    ):
        return value.strip(), ""
    return left, right


def _discard_location_as_company(value: str) -> str:
    """标题行中的地点片段不是公司名（例如“岗位 | 北京”）。"""
    if value and _looks_like_location(value) and not _looks_like_company(value):
        return ""
    return value


def _looks_like_location(value: str) -> bool:
    candidate = value.strip()
    if not candidate or len(candidate) > _FIELD_LIMITS["location"]:
        return False
    candidate_fold = candidate.casefold()
    if _looks_like_company(candidate):
        return False
    if any(term.casefold() in candidate_fold for term in _NON_LOCATION_TERMS):
        return False
    if not any(term.casefold() in candidate_fold for term in _LOCATION_TERMS) and not (
        _LOCATION_SUFFIX_RE.fullmatch(candidate)
    ):
        return False
    return not re.search(r"[。！？!?]", candidate)


def _extract_location_from_metadata(value: str) -> str:
    """从将地点、薪资放在同一行的招聘卡片中保留地点部分。"""
    without_salary = _SALARY_RE.sub("", value)
    without_salary = re.sub(
        r"(?:正式|正式员工|全职|兼职|长期|实习|校招|社招|intern(?:ship)?|full[- ]?time|"
        r"part[- ]?time|permanent|contract|"
        r"campus\s+(?:recruitment|hiring)|graduate\s+program)",
        "",
        without_salary,
        flags=re.IGNORECASE,
    )
    without_salary = without_salary.strip(" \t|｜·,，;；/\\")
    parts = []
    for part in re.split(r"[|｜·;；/\\]+|\s{2,}", without_salary):
        candidate = part.strip(" \t,，")
        if _looks_like_location(candidate):
            parts.append(candidate)
    if parts:
        return "、".join(dict.fromkeys(parts))
    if _looks_like_location(without_salary):
        return without_salary
    return ""


def _normalize_job_type(value: str) -> str:
    if re.search(r"实习|intern(?:ship)?", value, re.IGNORECASE):
        return "实习"
    if re.search(
        r"校园招聘|校招|应届|毕业生|20\d{2}\s*届|管培生|"
        r"campus\s+(?:recruitment|hiring|program)|graduate\s+(?:program|scheme|recruitment)|"
        r"new\s+grad(?:uate)?|entry[- ]level",
        value,
        re.IGNORECASE,
    ):
        return "校招"
    if re.search(
        r"社会招聘|社招|社会人才|experienced\s+hire|professional\s+hire",
        value,
        re.IGNORECASE,
    ):
        return "社招"
    return "其他"


def _normalize_status(value: str) -> str:
    if re.search(
        r"已关闭|停止招聘|招聘结束|已结束|已截止|职位失效|岗位失效|停止申请|"
        # 连字符技术术语（如 closed-loop）不代表岗位已关闭；限定英文词边界
        # 并排除紧随其后的连字符。
        r"(?<![A-Za-z])closed(?![A-Za-z-])|"
        r"(?<![A-Za-z])expired(?![A-Za-z])|"
        r"\bno\s+longer\s+accepting\b",
        value,
        re.IGNORECASE,
    ):
        return "已截止"
    return "开放中"


def _extract_labeled_fields(lines: list[str]) -> tuple[dict[str, str], set[int]]:
    values: dict[str, str] = {}
    consumed: set[int] = set()
    for index, line in enumerate(lines):
        # 章节标题可能以 ``Job Description:`` 这类形式出现；先让章节解析器
        # 处理，避免短英文字段别名（如 ``job``）把标题内容写进岗位名。
        if (
            _DESCRIPTION_HEADING_RE.match(line)
            or _REQUIREMENTS_HEADING_RE.match(line)
            or _ADDITIONAL_HEADING_RE.match(line)
            or _JOB_ID_RE.match(line)
        ):
            continue
        inline_matches = _inline_label_matches(line)
        if inline_matches:
            # 字段标签之后可能紧接“职位描述/任职要求”等章节标题；这些
            # 标题不是元数据字段，若不纳入边界，薪资/地点值会吞掉整段 JD。
            section_boundaries = [
                match.start() for match in _INLINE_SECTION_RE.finditer(line) if match.start() > 0
            ]
            for match_index, (start, end, field, _label) in enumerate(inline_matches):
                value_end = (
                    inline_matches[match_index + 1][0]
                    if match_index + 1 < len(inline_matches)
                    else len(line)
                )
                following_sections = [boundary for boundary in section_boundaries if boundary > end]
                if following_sections:
                    value_end = min(value_end, min(following_sections))
                value = line[end:value_end].strip(" \t:：|｜丨;,；,，")
                if value and field not in values:
                    values[field] = value
            consumed.add(index)
            continue
        for field, pattern in _LABEL_PATTERNS.items():
            match = pattern.match(line)
            if match is None:
                continue
            # “职位 ID：…”以“职位”开头，但它不是岗位名称；不要让通用
            # 标签别名覆盖后续真正的标题行。
            if field == "title" and _JOB_ID_RE.match(line):
                continue
            consumed.add(index)
            if field not in values:
                values[field] = match.group("value").strip()
            break
    return values, consumed


def _first_section_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if _DESCRIPTION_HEADING_RE.match(line) or _REQUIREMENTS_HEADING_RE.match(line):
            return index
    return len(lines)


def _mark_unlabeled_metadata(
    lines: list[str], values: dict[str, str], consumed: set[int], preamble_end: int
) -> None:
    for index, line in enumerate(lines[:preamble_end]):
        if index in consumed:
            continue
        if "source_url" not in values:
            url = _find_url(line)
            if url:
                values["source_url"] = url
                if url == line:
                    consumed.add(index)
                continue
        if "salary" not in values:
            salary_match = _SALARY_RE.search(line)
            if salary_match:
                values["salary"] = salary_match.group(0)
                # 标题和薪资经常位于同一行；只有剩余内容不像标题时才
                # 整行消费，否则后续标题提取会看不到岗位名。
                if len(line) <= 80 and not _looks_like_title(_strip_inline_salary(line)):
                    consumed.add(index)
        if "location" not in values:
            location = _extract_location_from_metadata(line)
            if not location:
                continue
            values["location"] = location
            # 同一行可能同时包含“岗位名 | 地点 | 薪资”；保留该行供标题
            # 提取逻辑处理，不能因为识别出地点就把岗位名一起消费掉。
            if not _looks_like_title(_strip_inline_salary(line)):
                consumed.add(index)


def _extract_title_and_company(
    lines: list[str], values: dict[str, str], consumed: set[int], preamble_end: int
) -> tuple[str, str]:
    title_value = _strip_inline_salary(values.get("title", ""))
    company = values.get("company", "")
    if title_value:
        title, inline_company = _split_title_company(title_value)
        return title, company or _discard_location_as_company(inline_company)

    for index, line in enumerate(lines[:preamble_end]):
        if index in consumed or _JOB_ID_RE.match(line) or _ADDITIONAL_HEADING_RE.match(line):
            continue
        title_candidate = _strip_inline_salary(line)
        if _looks_like_title(title_candidate):
            consumed.add(index)
            title, inline_company = _split_title_company(title_candidate)
            if not company and not inline_company:
                # 不同官网会把公司放在职位上方、下方，甚至使用没有“科技/有限公司”
                # 后缀的品牌名（如 Acme）。只检查紧邻行并排除地点、部门和元信息，
                # 避免把正文中的任意短句提升为公司。
                neighboring_indices = (index - 1, index + 1)
                for neighbor_index in neighboring_indices:
                    if neighbor_index < 0 or neighbor_index >= preamble_end:
                        continue
                    if neighbor_index in consumed:
                        continue
                    neighbor = lines[neighbor_index]
                    if _looks_like_company_candidate(neighbor):
                        company = neighbor.strip()
                        consumed.add(neighbor_index)
                        break
            return title, company or _discard_location_as_company(inline_company)
    return "", company


def _detect_job_type(lines: list[str], values: dict[str, str], preamble_end: int) -> str:
    labeled = values.get("job_type", "")
    if labeled:
        return _normalize_job_type(labeled)

    # 只看标题区和正文标题之前的元信息，避免“有实习经历者优先”把校招误判为实习。
    context = "\n".join(lines[:preamble_end])
    if any(_looks_like_internship_marker(line) for line in lines[:preamble_end]):
        return "实习"
    if re.search(
        r"校园招聘|校招|应届|毕业生|20\d{2}\s*届|管培生|"
        r"campus\s+(?:recruitment|hiring|program)|graduate\s+(?:program|scheme|recruitment)|"
        r"new\s+grad(?:uate)?|entry[- ]level",
        context,
        re.IGNORECASE,
    ):
        return "校招"
    if re.search(
        r"社会招聘|社招|社会人才|experienced\s+hire|professional\s+hire", context, re.IGNORECASE
    ):
        return "社招"
    return "其他"


def _mark_type_lines(lines: list[str], consumed: set[int], preamble_end: int) -> None:
    marker = re.compile(
        # 招聘计划标记已用于类型判断，无需再写入职责或补充信息。
        r"^(?:校园招聘|校招|社会招聘|社招|实习招聘|"
        r"20\d{2}\s*届(?:(?:暑期)?实习招聘|校园招聘|校招)?|"
        r"campus\s+(?:recruitment|hiring|program)|graduate\s+(?:program|scheme|recruitment)|"
        r"new\s+grad(?:uate)?|entry[- ]level|"
        r"intern(?:ship)?(?:\s+(?:program|recruitment|hiring))?)$",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines[:preamble_end]):
        if marker.match(line):
            consumed.add(index)


def _is_additional_preamble_line(line: str) -> bool:
    """识别标题区中应保留、但不属于岗位职责的招聘元信息。"""
    candidate = line.strip()
    if _JOB_ID_RE.match(candidate) or _UPDATED_DATE_RE.match(candidate):
        return True
    if re.fullmatch(
        r"(?:正式|正式员工|全职|兼职|长期|合同工|临时工|劳务派遣|"
        r"permanent|full[- ]?time|part[- ]?time|contract|temporary)",
        candidate,
        re.IGNORECASE,
    ):
        return True
    if re.match(
        r"^(?:所属)?(?:部门|团队|科室|业务线|事业部|职类|职位类别|岗位类别|"
        r"招聘人数|汇报对象|工作班次|工作时间|合同期限|department|team|division|"
        r"business\s+unit|reports?\s+to)\s*[:：]",
        candidate,
        re.IGNORECASE,
    ):
        return True
    return bool(
        re.fullmatch(
            r"[^。！？!?]{1,32}\s*[-—–/]\s*"
            r"(?:客户端|服务端|研发|生产|制造|销售|市场|运营|门店|科室|"
            r"client|server|engineering|production|sales|marketing|operations)",
            candidate,
            re.IGNORECASE,
        )
    )


def _extract_sections(
    lines: list[str], consumed: set[int]
) -> tuple[str, str, str, set[int], bool]:
    description_lines: list[str] = []
    requirement_lines: list[str] = []
    additional_lines: list[str] = []
    section_indices: set[int] = set()
    current_section = ""
    saw_description_heading = False

    for index, line in enumerate(lines):
        inline_matches = list(_INLINE_SECTION_RE.finditer(line))
        if inline_matches:
            section_indices.add(index)
            previous_section = current_section
            restore_description_after_intro = False
            for match_index, match in enumerate(inline_matches):
                heading = match.group("heading")
                if _DESCRIPTION_HEADING_RE.match(heading):
                    current_section = "description"
                elif _REQUIREMENTS_HEADING_RE.match(heading):
                    current_section = "requirements"
                else:
                    current_section = "additional"
                if current_section == "description":
                    saw_description_heading = True
                content_end = (
                    inline_matches[match_index + 1].start()
                    if match_index + 1 < len(inline_matches)
                    else len(line)
                )
                content = line[match.end() : content_end].strip()
                if current_section == "description":
                    if content:
                        description_lines.append(content)
                elif current_section == "requirements":
                    if content:
                        requirement_lines.append(content)
                else:
                    additional_lines.append(
                        f"{heading.strip()}：{content}" if content else heading.strip()
                    )
                    # 职责正文常先写一行“团队/公司介绍：...”，随后立即列出
                    # 实际职责。这种内联介绍只归入补充信息，不改变后续正文归属。
                    if previous_section == "description" and re.fullmatch(
                        r"(?:团队介绍|公司介绍|企业介绍|公司简介|企业简介|关于我们|"
                        r"company\s+overview|about\s+(?:the\s+)?company|about\s+us|"
                        r"team\s+introduction)",
                        heading.strip(),
                        re.IGNORECASE,
                    ):
                        restore_description_after_intro = True
            if restore_description_after_intro:
                current_section = previous_section
            continue

        description_match = _DESCRIPTION_HEADING_RE.match(line)
        if description_match:
            current_section = "description"
            saw_description_heading = True
            section_indices.add(index)
            content = description_match.group("content").strip()
            if content:
                description_lines.append(content)
            continue

        requirements_match = _REQUIREMENTS_HEADING_RE.match(line)
        if requirements_match:
            current_section = "requirements"
            section_indices.add(index)
            content = requirements_match.group("content").strip()
            if content:
                requirement_lines.append(content)
            continue

        additional_match = _ADDITIONAL_HEADING_RE.match(line)
        if additional_match:
            current_section = "additional"
            section_indices.add(index)
            heading = additional_match.group("heading").strip()
            content = additional_match.group("content").strip()
            additional_lines.append(f"{heading}：{content}" if content else heading)
            continue

        if current_section:
            section_indices.add(index)
            if index in consumed:
                continue
            if current_section == "description":
                description_lines.append(line)
            elif current_section == "requirements":
                requirement_lines.append(line)
            else:
                additional_lines.append(line)

    return (
        "\n".join(description_lines),
        "\n".join(requirement_lines),
        "\n".join(additional_lines),
        section_indices,
        saw_description_heading,
    )


def _extract_posted_at(lines: list[str], values: dict[str, str]) -> str:
    if "posted_at" in values:
        return values["posted_at"]
    for line in lines:
        match = _PUBLISHED_DATE_RE.search(line)
        if match:
            return match.group("date")
    return ""


def parse_job_text(text: str) -> JobTextParseResult:
    """解析一段招聘文本并返回岗位草稿；不会调用网络或修改数据库。"""
    lines = _normalize_lines(text or "")
    values, consumed = _extract_labeled_fields(lines)
    preamble_end = _first_section_index(lines)

    _mark_unlabeled_metadata(lines, values, consumed, preamble_end)
    title, company = _extract_title_and_company(lines, values, consumed, preamble_end)
    job_type = _detect_job_type(lines, values, preamble_end)
    _mark_type_lines(lines, consumed, preamble_end)

    description, requirements, additional_info, section_indices, saw_description_heading = (
        _extract_sections(lines, consumed)
    )
    section_description = description.strip()
    additional_metadata_indices = {
        index
        for index, line in enumerate(lines[:preamble_end])
        if index not in consumed
        and index not in section_indices
        and _is_additional_preamble_line(line)
    }
    additional_metadata = [lines[index] for index in sorted(additional_metadata_indices)]

    if not saw_description_heading:
        fallback_lines = [
            line
            for index, line in enumerate(lines)
            if index not in consumed
            and index not in section_indices
            and index not in additional_metadata_indices
            and not _ADDITIONAL_HEADING_RE.match(line)
        ]
        description = "\n".join(fallback_lines)
    else:
        # 标题区仍可能有不属于职责或补充信息的简介，保留在职位描述前言中。
        preamble_metadata = [
            line
            for index, line in enumerate(lines[:preamble_end])
            if index not in consumed
            and index not in section_indices
            and index not in additional_metadata_indices
            and not _ADDITIONAL_HEADING_RE.match(line)
        ]
        description = "\n".join(preamble_metadata + ([description] if description else []))

    additional_info = "\n".join(
        [*additional_metadata, *([additional_info] if additional_info else [])]
    )

    substantive_description = (
        section_description if saw_description_heading else description.strip()
    )
    warnings: list[str] = []
    if not title:
        warnings.append("未识别到岗位名称，请手动填写。")
    if not substantive_description:
        warnings.append("未识别到职位描述，请核对原始文本并手动填写。")

    source_url = _find_url(values.get("source_url", ""))
    status_context = values.get("status", "") or "\n".join(lines)

    return JobTextParseResult(
        title=_truncate(title, "title"),
        company=_truncate(company, "company"),
        location=_truncate(values.get("location", ""), "location"),
        salary=_truncate(values.get("salary", ""), "salary"),
        job_type=_truncate(job_type, "job_type"),
        description=description.strip(),
        requirements=requirements.strip(),
        additional_info=additional_info.strip(),
        source_url=_truncate(source_url, "source_url"),
        posted_at=_truncate(_extract_posted_at(lines, values), "posted_at"),
        status=_truncate(_normalize_status(status_context), "status"),
        warnings=warnings,
    )
