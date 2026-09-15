"""岗位描述、要求和其他信息的章节规则。"""

import re

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
    r"职责要求|任职要求与条件|任职资格与要求|岗位要求与条件|应聘要求|资格要求|必备条件|"
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
_BARE_DATE_RE = re.compile(r"(?<!\d)(?P<date>20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})(?!\d)")
_NON_PUBLISHED_DATE_CONTEXT_RE = re.compile(
    r"更新|截止|到期|有效期|申请结束|报名结束|last\s+updated|deadline|closing\s+date|expires?",
    re.IGNORECASE,
)
