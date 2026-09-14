"""经历条目、日期、学历和头部字段识别规则。"""

import re


_MONTH_NAME = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE_TOKEN = rf"(?:\d{{4}}(?:[./年-]\d{{1,2}})?(?:[./月-]\d{{1,2}})?|{_MONTH_NAME}\s+\d{{4}})"
_DATE_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE_TOKEN})\s*"
    rf"(?:至|到|[-—–－~～]|\bto\b)\s*"
    rf"(?P<end>{_DATE_TOKEN}|至今|现在|present|current|now)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(_DATE_TOKEN, re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[\s-]?)?1[3-9](?:[\s-]?\d){9}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
# 限制数字序号长度，避免把 ``2025.06-至今`` 的年份误当作列表编号剥掉。
_BULLET_RE = re.compile(r"^\s*(?:[-*•·]|\d{1,3}[、.)）.]|[一二三四五六七八九十]+[、.)）.])\s*")
_ENTRY_SEPARATOR_RE = re.compile(r"\s*(?:\||｜|丨|·|•|—|–|－|/|／|~|～|\s+-\s+)\s*")
# 普通英文名称中可能含有连字符；仅把带空格的横线，或中文字段之间的
# 无空格横线当作条目分隔符。日期范围已在调用方先移除。
_HEADER_SEPARATOR_RE = re.compile(
    r"\s*(?:\||｜|丨|·|•|—|–|－|/|／|~|～|\s+-\s+|(?<=[\u4e00-\u9fff])-(?=[\u4e00-\u9fffA-Za-z]))\s*"
)

_NUMBERED_HEADING_RE = re.compile(
    r"^(?:第\s*)?(?:\d+|[一二三四五六七八九十百]+)\s*(?:[、.)）.]|、)\s*"
)
_INLINE_LABEL_SEPARATOR_RE = re.compile(r"\s*(?:\||｜|丨|;|；|,|，)\s*")
_BASIC_UNLABELED_CITY_RE = re.compile(
    r"(?:北京|上海|天津|重庆|深圳|广州|杭州|成都|武汉|西安|南京|苏州|长沙|厦门|合肥|郑州|青岛|济南|大连|宁波|东莞|佛山|珠海|无锡|福州|昆明|南昌|沈阳|石家庄|哈尔滨|香港|澳门|台北|兰州|太原|南宁|海口|贵阳|乌鲁木齐|呼和浩特|温州|常州|嘉兴|绍兴|扬州|Beijing|Shanghai|Tianjin|Chongqing|Shenzhen|Guangzhou|Hangzhou|Chengdu|Wuhan|Xi'an|Nanjing|Suzhou|Remote|Hybrid)",
    re.IGNORECASE,
)
_BASIC_NAME_RE = re.compile(r"^[\u4e00-\u9fff]{2,6}(?:\s+[A-Za-z][A-Za-z .'-]{1,30})?$")
_BASIC_ENGLISH_NAME_RE = re.compile(
    r"^[A-Za-z][A-Za-z.'-]{1,30}(?:\s+[A-Za-z][A-Za-z.'-]{1,30}){1,3}$"
)
_PROFILE_ENGLISH_TITLE_RE = re.compile(
    r"\b(?:engineer|developer|programmer|architect|analyst|designer|scientist|"
    r"researcher|manager|consultant|specialist|intern|operator|lead|director|"
    r"technician|support|sales|recruiter|secretary|president|treasurer|"
    r"coordinator|administrator|volunteer|fellow)\b",
    re.IGNORECASE,
)
_ENGLISH_COMPANY_HINT_RE = re.compile(
    r"\b(?:inc(?:orporated)?|ltd|limited|llc|corp(?:oration)?|company|group|holdings?|"
    r"technolog(?:y|ies)|tech|software|systems?|solutions?|studio|labs?|consulting)\b",
    re.IGNORECASE,
)
_NON_NAME_MARKERS = (
    "教育",
    "经历",
    "简历",
    "求职",
    "应聘",
    "意向",
    "工程师",
    "开发",
    "岗位",
    "职位",
    "联系方式",
    "电话",
    "邮箱",
    "城市",
    "地址",
    "个人",
    "基本",
)



_DEGREE_TERMS = (
    "本科",
    "大学本科",
    "硕士",
    "博士",
    "专科",
    "大专",
    "学士",
    "研究生",
    "bachelor",
    "master",
    "phd",
    "doctorate",
    "associate",
)



_HEADER_LABEL_ALIASES = {
    "school": (
        "学校",
        "院校",
        "学校名称",
        "毕业院校",
        "毕业学校",
        "graduated from",
        "school",
        "university",
        "college",
    ),
    "major": ("专业", "所学专业", "专业名称", "major", "field of study"),
    "degree": ("学历", "学位", "学历学位", "degree", "education"),
    "company": (
        "公司",
        "单位",
        "公司名称",
        "企业",
        "企业名称",
        "就职公司",
        "任职单位",
        "所在公司",
        "雇主",
        "employer name",
        "company",
        "company name",
        "enterprise",
        "employer",
        "organization name",
        "organization",
    ),
    "organization": (
        "组织",
        "组织/部门",
        "组织名称",
        "社团",
        "社团名称",
        "学生组织",
        "所在组织",
        "组织机构",
        "学生会",
        "团委",
        "部门",
        "organization",
        "department",
        "club",
        "student union",
        "organization name",
    ),
    "role": (
        "职位",
        "岗位",
        "职位名称",
        "岗位名称",
        "职务",
        "角色",
        "担任角色",
        "职称",
        "工作职位",
        "工作岗位",
        "work position",
        "job position",
        "担任职务",
        "职位名称",
        "岗位名称",
        "role",
        "position",
        "position name",
        "job title",
        "title",
    ),
    "project": (
        "项目",
        "项目名称",
        "项目标题",
        "项目名",
        "project",
        "project name",
        "project title",
    ),
}

# 按经历类型预编译条目起始字段，既与字段提取共用同一份别名，又避免在
# 每一行粘贴文本上重复拼接大正则。
_ENTRY_HEADER_FIELDS_BY_KIND = {
    "education": ("school",),
    "experience": ("company",),
    "campus": ("organization",),
    "project": ("project",),
    "default": ("school", "company", "organization", "project"),
}
_ENTRY_HEADER_PATTERNS = {
    kind: re.compile(
        rf"^(?:{'|'.join(re.escape(label) for field in fields for label in sorted(_HEADER_LABEL_ALIASES[field], key=len, reverse=True))})\s*[:：]",
        re.IGNORECASE,
    )
    for kind, fields in _ENTRY_HEADER_FIELDS_BY_KIND.items()
}
_HEADER_BOUNDARY_LABELS = (
    *(label for labels in _HEADER_LABEL_ALIASES.values() for label in labels),
    "时间",
    "起止时间",
    "任职时间",
    "任职期间",
    "任职周期",
    "在职时间",
    "工作时间",
    "入职时间",
    "入职日期",
    "就业时间",
    "就职时间",
    "参与时间",
    "参与日期",
    "工作日期",
    "就业日期",
    "任职日期",
    "项目期间",
    "项目日期",
    "学习期间",
    "学习日期",
    "项目周期",
    "项目时间",
    "项目起止时间",
    "就读时间",
    "学习时间",
    "周期",
    "日期",
    "time",
    "period",
    "employment period",
    "work period",
    "duration",
    "date",
    "dates",
    "employment dates",
    "employment date",
    "work dates",
    "work date",
    "job dates",
    "study period",
    "study dates",
    "start date",
    "end date",
)



_PROFILE_CHINESE_ROLE_RE = re.compile(
    r"(?:工程师|开发|程序员|架构师|分析师|经理|负责人|主管|总监|专员|研究员|"
    r"设计师|实习生|助理|顾问|运营|产品|测试|算法|部长|主席|团支书|书记|"
    r"秘书|志愿者|干事|会长|班长|委员|老师|讲师)"
)
