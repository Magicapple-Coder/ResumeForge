"""JD 解析规则测试。"""

from app.services.jd_parser import parse_jd

SAMPLE_JD = """
职位：后端开发工程师
1. 本科及以上学历，计算机相关专业，3年以上开发经验；
2. 熟练掌握 Python 和 Java，了解 Go；
3. 熟悉 MySQL、Redis，有 Kafka 使用经验；
4. 了解微服务架构与分布式系统，熟悉 Linux；
5. 具备良好的数据结构与算法基础。
"""


def test_parse_jd_extracts_skills():
    result = parse_jd(SAMPLE_JD)
    names = {tag.name for tag in result["skills"]}
    assert {"Python", "Java", "Go", "MySQL", "Redis", "Kafka"} <= names
    assert "React" not in names  # 未出现的技能不应误报


def test_parse_jd_extracts_degree_and_years():
    result = parse_jd(SAMPLE_JD)
    assert result["degree"] == "本科"
    assert result["min_years"] == 3


def test_parse_jd_handles_empty_and_garbage():
    assert parse_jd("") == {"skills": [], "degree": "", "min_years": None}
    assert parse_jd(None) == {"skills": [], "degree": "", "min_years": None}
    result = parse_jd("！！!@#￥%……&*")
    assert result["skills"] == []


def test_parse_jd_dedupes_skills_case_insensitive():
    result = parse_jd("熟悉 python 和 Python")
    names = [tag.name for tag in result["skills"]]
    assert names.count("Python") == 1


def test_parse_jd_matches_english_skill_next_to_chinese_text():
    result = parse_jd("熟练掌握JavaScript等语言，使用Python开发")
    names = {tag.name for tag in result["skills"]}
    assert {"JavaScript", "Python"} <= names


def test_parse_jd_normalizes_common_skill_aliases_and_full_width_text():
    result = parse_jd(
        "熟悉Ｐｙｔｈｏｎ３、JS、Vue.js、Postgres、K8s，"
        "能够使用大语言模型和检索增强生成（RAG）构建应用。"
    )
    names = {tag.name for tag in result["skills"]}
    assert {"Python", "JavaScript", "Vue", "PostgreSQL", "Kubernetes", "大模型", "RAG"} <= names


def test_parse_jd_does_not_report_c_from_c_plus_plus():
    names = {tag.name for tag in parse_jd("熟悉 C++ 开发")["skills"]}
    assert "C++" in names
    assert "C" not in names


def test_parse_jd_normalizes_duplicate_skill_spellings_to_one_tag():
    names = [tag.name for tag in parse_jd("熟悉 Kubernetes（K8s）和计算机视觉（CV）")["skills"]]
    assert names.count("Kubernetes") == 1
    assert names.count("计算机视觉") == 1


def test_parse_jd_does_not_infer_javascript_from_a_framework_suffix():
    names = {tag.name for tag in parse_jd("熟悉 Vue.js 框架")["skills"]}
    assert "Vue" in names
    assert "JavaScript" not in names


def test_parse_jd_does_not_treat_bare_node_as_node_js():
    names = {tag.name for tag in parse_jd("熟悉树节点和数据结构")["skills"]}
    assert "Node.js" not in names


def test_parse_jd_supports_degree_and_experience_variants():
    result = parse_jd("学士及以上，至少 3 年相关经验；英文要求 2+ years")
    assert result["degree"] == "本科"
    assert result["min_years"] == 2


def test_parse_jd_supports_chinese_years_and_common_product_spellings():
    result = parse_jd(
        "三年以上经验，熟悉 Fast API、My Batis、Apache Kafka、Rabbit MQ、"
        "SQL、C#、.NET、PyTorch、sklearn、微信小程序。"
    )
    names = {tag.name for tag in result["skills"]}
    assert result["min_years"] == 3
    assert {
        "FastAPI",
        "MyBatis",
        "Kafka",
        "RabbitMQ",
        "SQL",
        "C#",
        ".NET",
        "PyTorch",
        "Scikit-learn",
        "小程序",
    } <= names


def test_parse_jd_matches_dotnet_when_embedded_in_aspnet():
    names = {tag.name for tag in parse_jd("熟悉 ASP.NET Core 和 C# 开发")["skills"]}
    assert {".NET", "C#"} <= names


def test_parse_jd_does_not_report_css3_from_tailwind_css():
    names = {tag.name for tag in parse_jd("熟悉 Tailwind CSS")["skills"]}
    assert "Tailwind CSS" in names
    assert "CSS3" not in names


def test_parse_jd_does_not_report_lowercase_english_verb_as_go_language():
    names = {tag.name for tag in parse_jd("We go through the interview process.")["skills"]}
    assert "Go" not in names


def test_parse_jd_filters_ambiguous_english_words_without_technical_context():
    assert "Agent" not in {tag.name for tag in parse_jd("Customer service agent role")["skills"]}
    assert "Java" not in {tag.name for tag in parse_jd("Java island project")["skills"]}
    assert "React" not in {tag.name for tag in parse_jd("React to customer feedback")["skills"]}
    assert "计算机视觉" not in {tag.name for tag in parse_jd("Please submit your CV")["skills"]}


def test_parse_jd_keeps_ambiguous_skills_with_technical_context():
    names = {
        tag.name
        for tag in parse_jd("Build an AI agent, Java backend and React components")["skills"]
    }
    assert {"Agent", "Java", "React"} <= names
    assert "计算机视觉" in {
        tag.name for tag in parse_jd("CV model and image recognition")["skills"]
    }


def test_parse_jd_takes_highest_degree_and_lowest_years():
    result = parse_jd("硕士及以上，博士优先；5年以上经验，3年以上亦可")
    assert result["degree"] == "博士"
    assert result["min_years"] == 3


def test_parse_jd_ignores_calendar_years_and_supports_experience_ranges():
    assert parse_jd("发布日期：2026年8月18日")["min_years"] is None
    assert parse_jd("要求 100 年以上经验")["min_years"] == 100
    assert parse_jd("具有 3-5 年后端开发经验")["min_years"] == 3


def test_parse_jd_avoids_degree_substrings_in_institution_or_postdoc_terms():
    assert parse_jd("毕业于研究生院，具有博士后经历")["degree"] == ""
    assert parse_jd("研究生学历优先")["degree"] == "硕士"


def test_parse_jd_handles_capitalized_english_go_contextually():
    assert "Go" not in {
        tag.name for tag in parse_jd("We Go through the interview process.")["skills"]
    }
    assert "Go" in {
        tag.name
        for tag in parse_jd("go through docs; use Go language for backend development")["skills"]
    }


def test_parse_jd_supports_english_degree_phrasing():
    assert parse_jd("Bachelor's degree required")["degree"] == "本科"
    assert parse_jd("Master’s degree preferred")["degree"] == "硕士"
    assert parse_jd("Ph.D. in computer science")["degree"] == "博士"
    assert parse_jd("Bachelor of Engineering preferred")["degree"] == "本科"


def test_parse_jd_returns_empty_result_for_non_string_input():
    assert parse_jd(123) == {"skills": [], "degree": "", "min_years": None}


def test_parse_jd_supports_english_number_words_for_experience():
    assert parse_jd("at least three years of backend experience")["min_years"] == 3


def test_parse_jd_normalizes_common_versioned_and_chinese_skill_variants():
    names = {
        tag.name
        for tag in parse_jd("熟悉 Vue3、React18、MySQL8、检索增强、机器视觉与生成式 AI 应用。")[
            "skills"
        ]
    }

    assert {"Vue", "React", "MySQL", "RAG", "计算机视觉", "AIGC"} <= names


def test_parse_jd_normalizes_spaced_framework_spellings_without_short_alias_noise():
    names = {
        tag.name
        for tag in parse_jd("Fast-API、Postgre SQL、Py Torch 和 Experience with Go.")["skills"]
    }

    assert {"FastAPI", "PostgreSQL", "PyTorch", "Go"} <= names
    assert "Python" not in names
    assert "SQL" not in names


def test_parse_jd_supports_common_english_degree_abbreviations():
    assert parse_jd("B.S. degree required")["degree"] == "本科"
    assert parse_jd("M.S. preferred")["degree"] == "硕士"
    assert parse_jd("BSc or equivalent")["degree"] == "本科"
    assert parse_jd("MSc preferred")["degree"] == "硕士"


def test_parse_jd_does_not_treat_bare_as_or_ms_as_degree_abbreviations():
    assert parse_jd("Work as part of a distributed team.")["degree"] == ""
    assert parse_jd("Keep request latency below 50 ms.")["degree"] == ""


def test_parse_jd_keeps_ambiguous_skills_in_delimited_technical_lists():
    names_with_anchor = {
        tag.name for tag in parse_jd("Required skills: Python、Java、Go、C、CV")["skills"]
    }
    names_without_anchor = {tag.name for tag in parse_jd("Java, Go, C, CV")["skills"]}

    expected = {"Java", "Go", "C", "计算机视觉"}
    assert {"Python", *expected} <= names_with_anchor
    assert expected <= names_without_anchor


def test_parse_jd_keeps_ambiguous_skills_out_of_delimited_natural_prose():
    names = {
        tag.name
        for tag in parse_jd("Please submit your CV, as requested. We go, as planned.")["skills"]
    }

    assert "计算机视觉" not in names
    assert "Go" not in names


def test_parse_jd_extracts_cross_industry_skills_and_qualifications():
    result = parse_jd(
        "熟练使用 Excel、Power BI 和 SAP，具备供应链管理、仓储管理与质量管理经验；"
        "持有教师资格证、护士资格证或焊工资格证者优先。"
    )
    names = {tag.name for tag in result["skills"]}

    assert {
        "Excel",
        "Power BI",
        "SAP",
        "供应链管理",
        "仓储管理",
        "质量管理",
        "教师资格证",
        "护士执业资格证",
        "焊工证",
    } <= names
