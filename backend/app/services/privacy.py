"""简历脱敏变换：把可识别身份的字段替换成占位符，供导出 / 分享 / 脱敏预览复用。

这是全仓库脱敏规则的**唯一实现处**。默认遮罩姓名 / 手机 / 邮箱 / 公司名；学校 / 项目 /
产品名可配置。脱敏是"导出时变换"，**不回写真实数据**：输入一份 ``ResumeContent``，返回
一份全新的 ``ResumeContent``，原对象不被改动（deep copy）。

``mask_product`` 的语义说明：``ResumeContent`` 里没有独立的"产品名"字段，产品名通常就是
项目名 / 公司名，并以叙事文本的形式出现在总结与描述里。所以这里做**正文级替换**——把
已知的项目名与公司名在总结 / 描述文本里遮罩，避免产品名从正文漏出。更细的产品名词表
留到 R-17 完整实现时再扩展。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..schemas.resume import ResumeContent

# 遮罩占位符：三颗星足够醒目又不会泄露长度信息。
MASK = "***"


@dataclass(frozen=True)
class RedactionOptions:
    """脱敏选项。默认遮罩可直接识别身份的四项，其余按需开启。"""

    mask_name: bool = True
    mask_phone: bool = True
    mask_email: bool = True
    mask_company: bool = True
    mask_school: bool = False
    mask_project: bool = False
    mask_product: bool = False


def _mask(value: str) -> str:
    """非空值替换为占位符，空值保持为空。"""
    return MASK if value else ""


def _mask_tokens(text: str, tokens: set[str]) -> str:
    for token in tokens:
        if token and token in text:
            text = text.replace(token, MASK)
    return text


def redact(resume_content: ResumeContent, options: RedactionOptions | None = None) -> ResumeContent:
    """按选项脱敏一份简历内容，返回新对象，不改动输入。"""
    opts = options or RedactionOptions()
    # 先收集正文级"产品名" token：mask_company / mask_project 会把字段改成占位符，
    # 若在遮罩之后才收集，就只剩 "***"，正文里的原始公司 / 项目名会漏网。
    product_tokens = {project.name for project in resume_content.projects if project.name}
    product_tokens |= {experience.company for experience in resume_content.experience if experience.company}
    resume = resume_content.model_copy(deep=True)

    if opts.mask_name:
        resume.name = _mask(resume.name)
    if opts.mask_phone:
        resume.phone = _mask(resume.phone)
    if opts.mask_email:
        resume.email = _mask(resume.email)
    if opts.mask_company:
        for experience in resume.experience:
            experience.company = _mask(experience.company)
    if opts.mask_school:
        for education in resume.education:
            education.school = _mask(education.school)
    if opts.mask_project:
        for project in resume.projects:
            project.name = _mask(project.name)
    if opts.mask_product:
        resume.summary = _mask_tokens(resume.summary, product_tokens)
        for experience in resume.experience:
            experience.description = [_mask_tokens(line, product_tokens) for line in experience.description]
        for project in resume.projects:
            project.description = [_mask_tokens(line, product_tokens) for line in project.description]
            project.highlights = [_mask_tokens(line, product_tokens) for line in project.highlights]

    return resume


# ===== 敏感信息与合规风险的「识别」模式（R-08 与 R-17 共用） =====
# 简历上不该出现、或需要格外注意的敏感/合规内容。上面 ``redact`` 是「遮罩」变换，
# 这里是「识别」模式——R-08 风险扫描用它提示用户，R-17 完整隐私功能也会复用同一套
# 名单，避免两处各写一份而漂移（共享知识第 8 条：规则只有一份实现）。
#
# 每项是 (规则名, 正则表达式)。关键词类（只能靠字面命中、没有数字规律的）见
# ``SENSITIVE_KEYWORDS`` 与 ``COMPLIANCE_KEYWORDS``。
SENSITIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    # 18 位中国居民身份证号（含末位 X/x）。
    (
        "身份证号",
        r"\b\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b",
    ),
    # 银行卡号：16~19 位纯数字（与身份证号重叠的部分由调用方按片段去重）。
    ("银行卡号", r"\b\d{16,19}\b"),
    # 精确出生日期（年-月-日），区别于仅写出生年份（birth_year）。
    ("精确出生日期", r"(?:19|20)\d{2}\s*[-年/.]\s*\d{1,2}\s*[-月/.]\s*\d{1,2}\s*日?"),
)

# 敏感关键词：命中即提示（偏「建议注意」，不一定是硬违规）。
SENSITIVE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("身份证", "身份证"),
    ("家庭住址", "家庭住址"),
    ("现住址", "现住址"),
    ("政治面貌", "政治面貌"),
    ("婚姻状况", "婚姻状况"),
    ("生育状况", "生育状况"),
    ("薪资", "薪资"),
    ("期望薪资", "期望薪资"),
    ("月薪", "月薪"),
    ("年薪", "年薪"),
)

# 合规/保密风险词（R-09 与 R-17 共用）：命中提示可能涉及未公开 / 保密信息。
COMPLIANCE_KEYWORDS: tuple[str, ...] = (
    "保密协议",
    "保密项目",
    "涉密",
    "机密",
    "绝密",
    "商业机密",
    "内部数据",
    "未公开",
    "未发布",
    "未上线",
    "客户名单",
    "核心算法",
    "竞品数据",
    "NDA",
)


__all__ = [
    "COMPLIANCE_KEYWORDS",
    "MASK",
    "RedactionOptions",
    "SENSITIVE_KEYWORDS",
    "SENSITIVE_PATTERNS",
    "redact",
]
