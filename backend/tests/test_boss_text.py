"""BOSS 文本还原的回归测试——用例里的字符串**全部取自真实采集到的数据**。

这些混淆形态不是想出来的，是从用户的库里读出来的：标题里的方框（``全栈工程师-K``）、
描述里夹着的 ``boss`` / ``kanzhun`` / ``直聘``、以及被换成康熙部首的常用字。真实数据是最强的
回归样本，所以这里直接照搬，而不是自己编一份"看起来像"的文本。
"""
import pytest

from app.services.sites.boss_text import (
    looks_like_salary,
    normalize_text,
    split_job_sections,
    split_title_salary,
)


# ===== 字体反爬：私用区数字 =====


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 真实标题：数字被映射到 U+E030+digit，界面上显示成方框
        ("全栈工程师\ue032\ue033-\ue032\ue036K", "全栈工程师23-26K"),
        ("全栈工程师\ue038-\ue032\ue031K", "全栈工程师8-21K"),
        ("全栈开发\ue032\ue031-\ue032\ue036K", "全栈开发21-26K"),
        ("web全栈开发工程师\ue039-\ue032\ue034K", "web全栈开发工程师9-24K"),
        ("全栈工程师\ue032\ue031\ue031-\ue032\ue033\ue031元/天", "全栈工程师211-231元/天"),
    ],
)
def test_private_use_digits_are_restored(raw, expected):
    assert normalize_text(raw) == expected


def test_kangxi_radicals_are_folded_back_to_hanzi():
    """字体反爬的另一半：常用字被换成康熙部首，NFKC 归一化即可还原。"""
    assert normalize_text("⼯作时段") == "工作时段"
    assert normalize_text("结算⽅式") == "结算方式"
    assert normalize_text("熟练使⽤") == "熟练使用"


# ===== 水印 token =====


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 夹在汉字之间
        ("教育背景：本boss科在校生", "教育背景：本科在校生"),
        ("、负责公司业boss务系统的前后", "、负责公司业务系统的前后"),
        ("公司核心产品boss的前后端架构", "公司核心产品的前后端架构"),
        ("熟练使kanzhun用Golang", "熟练使用Golang"),
        ("工kanzhun作周期：长直聘期兼职", "工作周期：长期兼职"),
        # 出现在文本开头、后面紧跟汉字
        ("boss岗位职责：1、参与", "岗位职责：1、参与"),
        ("boss岗位要求：1、熟练", "岗位要求：1、熟练"),
        ("直聘岗位职责：1、负责", "岗位职责：1、负责"),
    ],
)
def test_watermark_tokens_are_removed(raw, expected):
    assert normalize_text(raw) == expected


@pytest.mark.parametrize(
    "brand",
    [
        "BOSS直聘",
        "Boss直聘",
        "欢迎投递 BOSS 直聘官网",
        "该岗位来自BOSS直聘",
    ],
)
def test_brand_name_is_never_stripped(brand):
    """品牌名本身就含 ``boss`` / ``直聘``，删水印时绝不能误伤它。

    规则要求 *小写* 且紧贴汉字——品牌名写作 BOSS/Boss，且后面常跟空格，因此天然被排除。
    """
    assert normalize_text(brand) == brand


def test_watermark_removal_is_idempotent():
    once = normalize_text("教育背景：本boss科在校生")
    assert normalize_text(once) == once


# ===== 空白与不可见字符 =====


def test_invisible_and_nbsp_characters_are_normalised():
    # 真实数据里出现过 \xa0（不换行空格）与 \u200b（零宽空格）
    assert normalize_text("1.\xa0负责前端") == "1. 负责前端"
    assert normalize_text("结果可视化\u200b2、承担") == "结果可视化2、承担"


def test_normalize_text_handles_none_and_empty():
    assert normalize_text(None) == ""
    assert normalize_text("") == ""


# ===== 标题 / 薪资分离 =====


@pytest.mark.parametrize(
    ("raw", "title", "salary"),
    [
        ("全栈工程师\ue032\ue033-\ue032\ue036K", "全栈工程师", "23-26K"),
        ("全栈开发\ue032\ue031-\ue032\ue036K", "全栈开发", "21-26K"),
        ("全栈工程师（兼职）\ue033\ue031-\ue035\ue031K", "全栈工程师（兼职）", "31-51K"),
        ("全栈工程师\ue032\ue031\ue031-\ue032\ue033\ue031元/天", "全栈工程师", "211-231元/天"),
        # 带 ·13薪 的形态
        ("高级前端18-30K·13薪", "高级前端", "18-30K·13薪"),
        # 标题里本来就不含薪资 → 原样保留，薪资留空
        ("全栈工程师", "全栈工程师", ""),
        ("AI 智能体开发工程师", "AI 智能体开发工程师", ""),
    ],
)
def test_split_title_salary(raw, title, salary):
    assert split_title_salary(raw) == (title, salary)


def test_split_title_salary_never_produces_an_empty_title():
    """整段就是一个薪资时保留在标题位——空标题会让岗位在列表里"消失"。"""
    assert split_title_salary("15-25K") == ("15-25K", "")


def test_looks_like_salary():
    assert looks_like_salary("15-25K")
    assert looks_like_salary("18-30K·13薪")
    assert looks_like_salary("211-231元/天")
    assert looks_like_salary("面议")
    # 岗位名（哪怕里面带数字）不是薪资；卡片容器取错时靠它兜住
    assert not looks_like_salary("全栈工程师23-26K")
    assert not looks_like_salary("全栈工程师")
    assert not looks_like_salary("")


# ===== 职位描述 / 任职要求 切分 =====


def test_splits_description_and_requirements_at_the_heading():
    """真实用例：要求类小标题出现在中段 → 之前是描述、之后是要求。"""
    text = (
        "岗位职责：1、参与公司新产品的需求分析、软件设计及开发工作。"
        "2、根据工作安排高效、高质地完成代码编写，确保符合团队开发规范。"
        "岗位要求：1、专科及以上学历，计算机相关专业。2、1年以上JAVA开发经验。"
    )
    description, requirements = split_job_sections(text)

    assert description.startswith("岗位职责")
    assert "岗位要求" not in description
    assert requirements.startswith("岗位要求")
    assert "JAVA开发经验" in requirements


def test_does_not_split_when_the_whole_jd_is_requirements():
    """真实用例：整篇只有要求段（``boss岗位要求：…``）→ 不切，全文留在描述里。

    否则会产出一个空的「职位描述」，比不切更难看。
    """
    text = "boss岗位要求：1、熟练使用Golang(必须)2、熟练使用React或vue3。"
    description, requirements = split_job_sections(text)

    assert description == "岗位要求：1、熟练使用Golang(必须)2、熟练使用React或vue3。"
    assert requirements == ""


def test_splits_on_bracketed_heading():
    """真实用例：标题写成 ``【任职要求】``。"""
    text = "1. 负责公司核心产品的前后端架构设计、开发与维护。2. 需求评审，输出技术方案并落地。" * 3 + (
        "【任职要求】基本条件：1. 计算机或相关专业。"
    )
    description, requirements = split_job_sections(text)

    assert "【任职要求】" not in description
    assert requirements.startswith("【任职要求】")


def test_requirement_heading_is_chosen_by_position_not_by_table_order():
    """取**最早出现**的要求类标题：文案里先后顺序并不固定。"""
    text = (
        "岗位职责：负责前后端开发、系统设计与性能优化等日常工作内容若干。"
        "任职资格：1、熟悉主流框架。2、具备良好的沟通能力。"
        "岗位要求：1、三年以上经验。"
    )
    _, requirements = split_job_sections(text)

    assert requirements.startswith("任职资格")


def test_section_split_handles_empty_input():
    assert split_job_sections(None) == ("", "")
    assert split_job_sections("") == ("", "")
