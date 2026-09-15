"""岗位文本解析器的行业适配与边界场景测试。"""

import pytest

from app.services.job_text_parser import parse_job_text


def test_parse_job_text_supports_short_company_aliases_and_numbered_sections():
    result = parse_job_text(
        "企业：Acme\n"
        "职位名：数据分析师\n"
        "工作地点：北京\n"
        "1. 岗位职责：负责业务报表和指标分析。\n"
        "2. 任职资格：熟悉 SQL 和 Python。"
    )

    assert result.title == "数据分析师"
    assert result.company == "Acme"
    assert result.location == "北京"
    assert result.description == "负责业务报表和指标分析。"
    assert result.requirements == "熟悉 SQL 和 Python。"


def test_parse_job_text_supports_markdown_and_bracketed_section_headings():
    result = parse_job_text(
        "后端开发工程师\n"
        "## 【岗位职责】\n"
        "负责 API 服务的设计与开发。\n"
        "### [Job Requirements]\n"
        "熟悉 Python 和数据库。"
    )

    assert result.title == "后端开发工程师"
    assert result.description == "负责 API 服务的设计与开发。"
    assert result.requirements == "熟悉 Python 和数据库。"


def test_parse_job_text_infers_a_short_brand_next_to_the_title():
    result = parse_job_text(
        "Acme\nProduct Designer\nShanghai\n"
        "Job Description: Design products.\nRequirements: Bachelor degree."
    )

    assert result.title == "Product Designer"
    assert result.company == "Acme"
    assert result.location == "Shanghai"


@pytest.mark.parametrize(
    ("text", "expected_title", "expected_company", "expected_location"),
    [
        (
            "南山人民医院\n急诊科医师\n广东省深圳市南山区\n"
            "岗位职责：负责急诊患者接诊。\n任职资格：持有执业医师资格证。",
            "急诊科医师",
            "南山人民医院",
            "广东省深圳市南山区",
        ),
        (
            "春风实验学校\n高中语文教师\n杭州市余杭区\n"
            "工作内容：承担高中语文教学。\n任职要求：持有教师资格证。",
            "高中语文教师",
            "春风实验学校",
            "杭州市余杭区",
        ),
        (
            "远航汽车制造有限公司\n焊工\n江苏省苏州市吴中区\n"
            "主要职责：完成车身焊接作业。\n资格要求：持焊工证优先。",
            "焊工",
            "远航汽车制造有限公司",
            "江苏省苏州市吴中区",
        ),
        (
            "惠民生活超市\n门店店长\n成都市武侯区\n"
            "岗位职责：负责门店经营。\n任职条件：三年零售管理经验。",
            "门店店长",
            "惠民生活超市",
            "成都市武侯区",
        ),
        (
            "顺达物流集团\n物流调度员\n武汉市江夏区\n"
            "工作职责：安排车辆调度。\n招聘要求：熟悉运输流程。",
            "物流调度员",
            "顺达物流集团",
            "武汉市江夏区",
        ),
    ],
)
def test_parse_job_text_supports_unlabeled_cross_industry_postings(
    text, expected_title, expected_company, expected_location
):
    result = parse_job_text(text)

    assert result.title == expected_title
    assert result.company == expected_company
    assert result.location == expected_location
    assert result.description
    assert result.requirements


def test_parse_job_text_collects_useful_recruitment_metadata_and_additional_sections():
    result = parse_job_text(
        "职位：招商主管\n"
        "公司：星河商业集团\n"
        "部门：商业运营部\n"
        "职位 ID：R-100\n"
        "发布时间：2026-08-19\n"
        "更新于：2026-08-20\n"
        "职位描述：负责品牌招商。\n"
        "任职要求：三年以上相关经验。\n"
        "福利待遇\n"
        "五险一金、带薪年假\n"
        "申请流程：网申后安排两轮面试。"
    )

    assert result.posted_at == "2026-08-19"
    assert "部门：商业运营部" in result.additional_info
    assert "职位 ID：R-100" in result.additional_info
    assert "更新于：2026-08-20" in result.additional_info
    assert "福利待遇\n五险一金、带薪年假" in result.additional_info
    assert "申请流程：网申后安排两轮面试。" in result.additional_info
    assert "福利待遇" not in result.requirements


def test_parse_job_text_does_not_treat_last_updated_as_posted_date():
    result = parse_job_text(
        "护士\nLast updated: August 20, 2026\nJob Description: Provide patient care."
    )

    assert result.posted_at == ""
    assert "Last updated: August 20, 2026" in result.additional_info
