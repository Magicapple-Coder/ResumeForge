"""招聘文本解析器测试。"""

import re

import pytest

from app.services.job_text_parser import parse_job_text


SAMPLE_JOB_TEXT = """AI应用客户端开发工程师 - 剪映CapCut
深圳、广州
正式
研发 - 客户端
2027届校园招聘
职位 ID：A134186
职位描述
团队介绍：剪映研发团队，主要支持剪映、CapCut、醒图、Hypic、即梦、Dreamina、小云雀、Pippit等多款国内外产品的研发工作，业务覆盖多元化影像创作场景，并孵化了多款AIGC明星产品，相关产品多次登顶国内外App Store 免费应用榜第一，并继续保持高速增长。加入我们，一起打造全球最受用户欢迎的影像创作和GenAI产品。

1、参与产品迭代改进，协作多部门或团队进行功能开发和联调；
2、参与剪辑场景，基础剪辑能力和智能化剪辑能力开发；
3、参与提效工具开发，结合AI工具应用，开发内部提效工具。
职位要求
1、2027届获得本科及以上学历，计算机、数学等相关专业优先；
2、有良好的编程习惯，代码结构清晰，命名规范；
3、熟练掌握数据结构与算法、计算机网络、操作系统、编译原理等课程，熟练掌握C++/C/Java/JavaScript等一种或多种语言；
4、充满技术热情，有较强的自驱力和学习能力；
5、业余爱好视频拍摄、视频编辑，有移动端、桌面端视频编辑软件使用经验者优先。"""


BAIDU_COMPACT_JOB_TEXT = """北京-全栈开发工程师(J103963)百度 https://talent.baidu.com/jobs/detail/GRADUATE/8ded98ee-9ddf-486c-96e9-75d4941d943b
北京市校招技术若干2026-07-30
工作职责：
-负责前端和服务端的业务开发工作，覆盖业务全链路
-深度运用AI Coding工具，开发并维护基于MCP、CLI、Skills等的各类工具
职责要求：
-本科及以上学历，计算机、通信和电子信息科学、数学等相关专业
-熟练使用HTML5/CSS3/JavaScript/TypeScript/Vue/React等前端技术完成页面布局和交互开发
"""


def test_parse_full_job_posting_extracts_core_fields_and_sections():
    result = parse_job_text(SAMPLE_JOB_TEXT)

    assert result.title == "AI应用客户端开发工程师"
    assert result.company == "剪映CapCut"
    assert result.location == "深圳、广州"
    assert result.job_type == "校招"

    assert result.additional_info.splitlines()[:3] == [
        "正式",
        "研发 - 客户端",
        "职位 ID：A134186",
    ]
    assert "团队介绍：剪映研发团队" in result.additional_info
    for responsibility in (
        "1、参与产品迭代改进",
        "2、参与剪辑场景",
        "3、参与提效工具开发",
    ):
        assert responsibility in result.description

    requirement_numbers = re.findall(r"(?m)^([1-5])、", result.requirements)
    assert requirement_numbers == ["1", "2", "3", "4", "5"]
    assert "2027届获得本科及以上学历" in result.requirements
    assert "C++/C/Java/JavaScript" in result.requirements
    assert "业余爱好视频拍摄、视频编辑" in result.requirements
    assert "2027届获得本科及以上学历" not in result.description
    assert "业余爱好视频拍摄、视频编辑" not in result.description


def test_parse_compact_official_job_header_and_responsibility_requirements():
    result = parse_job_text(BAIDU_COMPACT_JOB_TEXT)

    assert result.title == "全栈开发工程师(J103963)"
    assert result.company == "百度"
    assert result.location == "北京市"
    assert result.job_type == "校招"
    assert result.source_url == (
        "https://talent.baidu.com/jobs/detail/GRADUATE/"
        "8ded98ee-9ddf-486c-96e9-75d4941d943b"
    )
    assert result.posted_at == "2026-07-30"
    assert "负责前端和服务端的业务开发工作" in result.description
    assert "深度运用AI Coding工具" in result.description
    assert "本科及以上学历" in result.requirements
    assert "HTML5/CSS3/JavaScript/TypeScript/Vue/React" in result.requirements
    assert "本科及以上学历" not in result.description
    assert "北京市校招技术若干2026-07-30" in result.additional_info


def test_parse_compact_metadata_does_not_treat_deadline_as_posted_date():
    result = parse_job_text(
        "北京-全栈开发工程师(J103963)示例品牌\n"
        "北京市校招技术若干 截止日期2026-08-30\n"
        "工作职责：负责平台开发。"
    )

    assert result.location == "北京市"
    assert result.job_type == "校招"
    assert result.posted_at == ""


def test_parse_title_location_prefix_is_used_when_no_location_metadata_exists():
    result = parse_job_text(
        "北京-全栈开发工程师(J103963)示例品牌\n工作职责：负责平台开发。"
    )

    assert result.title == "全栈开发工程师(J103963)"
    assert result.company == "示例品牌"
    assert result.location == "北京"


def test_parse_labeled_fields():
    text = """职位名称：大模型应用开发工程师
公司：星河科技有限公司
工作地点：上海
薪资：25K-40K·16薪
招聘类型：社会招聘
发布时间：2026-08-15
链接：https://jobs.example.com/positions/42
职位描述：负责大模型应用服务的设计与开发。
职位要求：三年以上 Python 开发经验。"""

    result = parse_job_text(text)

    assert result.title == "大模型应用开发工程师"
    assert result.company == "星河科技有限公司"
    assert result.location == "上海"
    assert result.salary == "25K-40K·16薪"
    assert result.job_type == "社招"
    assert result.source_url == "https://jobs.example.com/positions/42"
    assert result.posted_at == "2026-08-15"
    assert "大模型应用服务的设计与开发" in result.description
    assert "三年以上 Python 开发经验" in result.requirements


def test_labeled_company_keeps_hyphenated_position_direction_in_title():
    result = parse_job_text(
        "职位名称：Agent全栈开发实习生 - 数据平台\n"
        "公司：字节跳动\n"
        "职位描述：负责数据平台开发。"
    )

    assert result.title == "Agent全栈开发实习生 - 数据平台"
    assert result.company == "字节跳动"


def test_generic_additional_heading_is_not_copied_into_additional_value():
    result = parse_job_text(
        "职位名称：后端开发工程师\n"
        "公司：示例科技\n"
        "职位描述：负责 API 开发。\n"
        "其他信息\n"
        "职位 ID：A100"
    )

    assert result.additional_info == "职位 ID：A100"


@pytest.mark.parametrize(
    ("text", "expected_job_type"),
    [
        ("算法实习生\n职位描述：参与模型训练。", "实习"),
        ("资深后端开发工程师\n社会招聘\n职位描述：负责服务架构。", "社招"),
        ("算法实习生\n2027届暑期实习招聘\n职位描述：参与模型训练。", "实习"),
    ],
)
def test_parse_job_type(text, expected_job_type):
    assert parse_job_text(text).job_type == expected_job_type


def test_parse_crlf_and_inline_sections():
    text = (
        "前端开发实习生\r\n"
        "公司：示例科技\r\n"
        "工作地点：杭州\r\n"
        "职位描述：负责 React 页面开发。职位要求：本科在读，熟悉 JavaScript。"
    )

    result = parse_job_text(text)

    assert result.title == "前端开发实习生"
    assert result.job_type == "实习"
    assert "负责 React 页面开发" in result.description
    assert "本科在读，熟悉 JavaScript" in result.requirements
    assert "本科在读" not in result.description
    assert "负责 React 页面开发" not in result.requirements


def test_parse_inline_sections_without_punctuation_between_them():
    result = parse_job_text(
        "后端开发工程师\n职位描述：负责接口开发 职位要求：熟悉 Python 和数据库。"
    )

    assert result.description == "负责接口开发"
    assert result.requirements == "熟悉 Python 和数据库。"


def test_parse_missing_title_returns_warning():
    result = parse_job_text("公司：示例科技\n工作地点：北京\n职位描述：负责平台研发。")

    assert result.title == ""
    assert any("标题" in warning or "岗位名称" in warning for warning in result.warnings)


def test_parse_company_before_title_and_ignores_non_url_link():
    result = parse_job_text(
        "字节跳动 - 算法工程师\n链接：点击这里投递\n职位描述：负责推荐算法研发。"
    )

    assert result.title == "算法工程师"
    assert result.company == "字节跳动"
    assert result.source_url == ""


def test_parse_empty_description_warns_even_when_preamble_metadata_is_preserved():
    result = parse_job_text(
        "客户端开发工程师 - 示例品牌\n正式\n研发 - 客户端\n职位 ID：A100\n职位描述\n职位要求：熟悉 C++。"
    )

    assert result.description == ""
    assert result.additional_info.splitlines() == ["正式", "研发 - 客户端", "职位 ID：A100"]
    assert any("职位描述" in warning for warning in result.warnings)


def test_parse_job_text_accepts_label_and_section_variants():
    result = parse_job_text(
        "职位：数据分析师\n"
        "雇主：星河科技\n"
        "工作城市：北京 / 上海\n"
        "薪酬待遇：20k以上\n"
        "工作形式：全职\n"
        "更新于：2026/08/18\n"
        "主要职责：负责数据报表和指标体系建设。\n"
        "资格要求：学士，熟悉 SQL。"
    )

    assert result.title == "数据分析师"
    assert result.company == "星河科技"
    assert result.location == "北京 / 上海"
    assert result.salary == "20k以上"
    assert result.posted_at == ""
    assert "更新于：2026/08/18" in result.additional_info
    assert "负责数据报表" in result.description
    assert "学士" in result.requirements


def test_parse_job_text_handles_full_width_copy_and_bilingual_headings():
    result = parse_job_text(
        "Ｊａｖａ开发工程师　—　示例有限公司\n"
        "上海\n"
        "What you'll do: 负责微服务开发。 Requirements: 熟悉 Java。"
    )

    assert result.title == "Java开发工程师"
    assert result.company == "示例有限公司"
    assert "负责微服务开发" in result.description
    assert "熟悉 Java" in result.requirements


def test_parse_job_text_splits_bilingual_inline_sections_after_a_period():
    result = parse_job_text(
        "Backend Engineer\n"
        "Responsibilities: Build API services. Qualifications: Familiar with Python."
    )

    assert "Build API services" in result.description
    assert "Familiar with Python" in result.requirements


def test_parse_job_text_supports_english_headings_and_recruitment_markers():
    result = parse_job_text(
        "Backend Engineer\n"
        "Campus recruitment\n"
        "What you will do: Build API services.\n"
        "What we are looking for: Familiar with Python."
    )

    assert result.title == "Backend Engineer"
    assert result.job_type == "校招"
    assert "Build API services" in result.description
    assert "Familiar with Python" in result.requirements


def test_parse_job_text_splits_company_and_title_without_spaces():
    result = parse_job_text("示例科技-后端开发工程师\n职位描述：负责服务端开发。")

    assert result.company == "示例科技"
    assert result.title == "后端开发工程师"


def test_parse_job_text_reads_company_on_line_before_english_title():
    result = parse_job_text(
        "Example Corporation\nBackend Engineer\nResponsibilities: Build services."
    )

    assert result.company == "Example Corporation"
    assert result.title == "Backend Engineer"


def test_parse_job_text_extracts_location_and_salary_from_one_metadata_line():
    result = parse_job_text(
        "后端开发工程师\n北京 | 20K-30K·15薪 | 全职\n岗位职责：负责服务端开发。"
    )

    assert result.location == "北京"
    assert result.salary == "20K-30K·15薪"


def test_parse_job_text_keeps_title_when_salary_shares_the_title_line():
    result = parse_job_text("后端开发工程师 20K-30K\n职位描述：负责服务端开发。")

    assert result.title == "后端开发工程师"
    assert result.salary == "20K-30K"


def test_parse_job_text_does_not_treat_inline_location_as_company():
    result = parse_job_text("后端开发工程师 | 20K-30K | 北京\n职位描述：负责服务端开发。")

    assert result.title == "后端开发工程师"
    assert result.company == ""
    assert result.location == "北京"
    assert result.salary == "20K-30K"


def test_parse_job_text_consumes_an_inferred_company_line_once():
    result = parse_job_text("示例科技\n后端开发工程师\n职位描述：负责服务端开发。")

    assert result.company == "示例科技"
    assert "示例科技" not in result.description


def test_parse_job_text_does_not_promote_team_metadata_to_company():
    result = parse_job_text("后端开发工程师\n北京团队\n职位描述：负责服务端开发。")

    assert result.title == "后端开发工程师"
    assert result.company == ""


def test_parse_job_text_does_not_promote_company_intro_to_title_or_company():
    result = parse_job_text(
        "公司介绍：我们专注软件开发\n后端开发工程师\n职位描述：负责服务端开发。"
    )

    assert result.title == "后端开发工程师"
    assert result.company == ""


def test_parse_job_text_recognizes_internship_program_marker():
    result = parse_job_text("Backend Engineer\nInternship Program\nResponsibilities: Build API.")

    assert result.job_type == "实习"
    assert "Internship Program" not in result.description


def test_parse_job_text_recognizes_common_english_locations():
    result = parse_job_text("Backend Engineer\nBeijing\nResponsibilities: Build API.")

    assert result.location == "Beijing"


def test_parse_job_text_does_not_close_a_closed_loop_role():
    result = parse_job_text("算法工程师\n职位描述：负责 closed-loop 控制算法。")

    assert result.status == "开放中"


def test_parse_job_text_supports_ascii_pipe_and_slash_title_separators():
    pipe_result = parse_job_text("Backend Engineer | Example Corp\nResponsibilities: Build API.")
    slash_result = parse_job_text("Example Corp / Backend Engineer\nResponsibilities: Build API.")

    assert pipe_result.title == "Backend Engineer"
    assert pipe_result.company == "Example Corp"
    assert slash_result.title == "Backend Engineer"
    assert slash_result.company == "Example Corp"


def test_parse_job_text_does_not_treat_two_role_names_as_company():
    result = parse_job_text("Backend Engineer - Software Engineer\nResponsibilities: Build API.")

    assert result.title == "Backend Engineer - Software Engineer"
    assert result.company == ""


def test_parse_job_text_does_not_treat_role_slash_as_company_separator():
    result = parse_job_text("AI / ML Engineer\nResponsibilities: Build models.")

    assert result.title == "AI / ML Engineer"
    assert result.company == ""


def test_parse_job_text_supports_english_field_labels_without_heading_prefix_leaks():
    result = parse_job_text(
        "Title: Backend Engineer\n"
        "Company: Example Inc\n"
        "Location: Beijing\n"
        "Salary: 20K-30K\n"
        "Job Description: Build APIs.\n"
        "Job Requirements: Python."
    )

    assert result.title == "Backend Engineer"
    assert result.company == "Example Inc"
    assert result.location == "Beijing"
    assert result.salary == "20K-30K"
    assert result.description == "Build APIs."
    assert result.requirements == "Python."


def test_parse_job_text_does_not_read_job_description_as_title_when_title_is_missing():
    result = parse_job_text("Job Description: Build APIs.\nJob Requirements: Python.")

    assert result.title == ""
    assert result.description == "Build APIs."
    assert result.requirements == "Python."


def test_parse_job_text_supports_position_label_and_generic_english_sections():
    result = parse_job_text(
        "Position: Backend Engineer\n"
        "Company: Example Inc\n"
        "Date Posted: Jan 2026\n"
        "Description: Build APIs.\n"
        "Qualifications: Python."
    )

    assert result.title == "Backend Engineer"
    assert result.company == "Example Inc"
    assert result.posted_at == "Jan 2026"
    assert result.description == "Build APIs."
    assert result.requirements == "Python."


def test_parse_job_text_supports_english_posted_date_with_day():
    result = parse_job_text(
        "Position: Backend Engineer\nPosted: August 18, 2026\nDescription: Build APIs."
    )

    assert result.posted_at == "August 18, 2026"


def test_parse_job_text_splits_multiple_metadata_labels_on_one_line():
    result = parse_job_text(
        "公司：星河科技 职位：后端开发工程师 地点：深圳 薪资：25K-35K·15薪\n"
        "职位描述：负责服务端开发。职位要求：熟悉 Python。"
    )

    assert result.company == "星河科技"
    assert result.title == "后端开发工程师"
    assert result.location == "深圳"
    assert result.salary == "25K-35K·15薪"
    assert result.description == "负责服务端开发。"
    assert result.requirements == "熟悉 Python。"


def test_parse_job_text_does_not_let_salary_consume_inline_section_headings():
    result = parse_job_text(
        "职位：后端开发工程师 公司：示例科技 地点：北京 薪资：20K-30K "
        "职位描述：负责 API 开发 职位要求：熟悉 Python"
    )

    assert result.salary == "20K-30K"
    assert result.description == "负责 API 开发"
    assert result.requirements == "熟悉 Python"


def test_parse_job_text_extracts_title_from_multi_segment_job_card():
    result = parse_job_text(
        "字节跳动 | 算法工程师 | 深圳 | 30-50K·16薪 | 社招\n"
        "岗位职责：负责推荐系统。岗位要求：硕士优先，熟悉 C++。"
    )

    assert result.title == "算法工程师"
    assert result.company == "字节跳动"
    assert result.location == "深圳"
    assert result.salary == "30-50K·16薪"
    assert result.job_type == "社招"


def test_parse_job_text_handles_single_amount_salary_in_card_metadata():
    result = parse_job_text("后端开发工程师 | 30K | 北京\n职位描述：负责服务端开发。")

    assert result.title == "后端开发工程师"
    assert result.company == ""
    assert result.salary == "30K"
    assert result.location == "北京"


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
