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

