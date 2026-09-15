"""个人资料解析的英文标题、日期、技能别名和无标题场景测试。"""

from app.services.profile_text_parser import parse_profile_text


def test_parse_profile_text_supports_common_english_section_names():
    result = parse_profile_text(
        "Name: Alice\n"
        "Education and Training\n"
        "University of Example - Computer Science - Bachelor - 2021-2025\n"
        "Work History\n"
        "Example Corp - Software Engineer - 2025-present\n"
        "Campus Activities\n"
        "Student Union - President - 2022-2023\n"
        "Projects & Practice\n"
        "Resume App - Developer - 2024-2025\n"
        "Tech Stack: Python, React.js, PostgreSQL\n"
        "Technical Expertise\n"
        "Python, JavaScript and SQL"
    )

    assert result.name == "Alice"
    assert len(result.educations) == 1
    assert len(result.experiences) == 1
    assert len(result.campus_experiences) == 1
    assert len(result.projects) == 1
    assert {skill.name for skill in result.skills} >= {"Python", "JavaScript", "SQL"}


def test_parse_profile_text_supports_english_month_date_ranges():
    result = parse_profile_text(
        "Work Experience\n"
        "Example Inc - Backend Engineer - Jan 2024 - Present\n"
        "Projects\n"
        "Resume App - Developer - September 2023 - June 2024"
    )

    assert result.experiences[0].start_date == "Jan 2024"
    assert result.experiences[0].end_date == "Present"
    assert result.projects[0].start_date == "September 2023"
    assert result.projects[0].end_date == "June 2024"


def test_parse_profile_text_normalizes_framework_ai_and_infrastructure_aliases():
    result = parse_profile_text(
        "技能特长\n"
        "React.js、NodeJS、My Batis、Apache Kafka、Postgres、SQLite3、"
        "PyTorch、sklearn、LLM、检索增强生成、Docker、WebSocket"
    )
    names = {skill.name for skill in result.skills}

    assert {
        "React",
        "Node.js",
        "MyBatis",
        "Kafka",
        "PostgreSQL",
        "SQLite",
        "PyTorch",
        "Scikit-learn",
        "大模型",
        "RAG",
        "Docker",
        "WebSocket",
    } <= names


def test_parse_profile_text_normalizes_versioned_and_chinese_skill_variants():
    result = parse_profile_text("专业技能\nVue3、React18、MySQL8、检索增强、机器视觉、生成式 AI")
    names = {skill.name for skill in result.skills}

    assert {"Vue", "React", "MySQL", "RAG", "计算机视觉", "AIGC"} <= names


def test_parse_profile_text_infers_sections_when_headings_are_missing():
    result = parse_profile_text(
        "姓名：张三\n"
        "学校：甲大学 专业：软件工程 学历：本科 时间：2020-2024\n"
        "公司：甲科技 职位：后端工程师 时间：2024-2025\n"
        "项目名称：平台项目 角色：开发 时间：2025-2026\n"
        "技能：Python、FastAPI、Docker"
    )

    assert len(result.educations) == 1
    assert len(result.experiences) == 1
    assert len(result.projects) == 1
    assert {skill.name for skill in result.skills} == {"Python", "FastAPI", "Docker"}


def test_parse_profile_text_infers_unlabeled_date_entries_and_skill_list():
    result = parse_profile_text(
        "张三\n"
        "甲大学 - 软件工程 - 本科 - 2020-2024\n"
        "甲科技 - 后端工程师 - 2024-2025\n"
        "Resume App - Developer - 2025-2026\n"
        "Python, FastAPI, Docker"
    )

    assert result.name == "张三"
    assert result.educations[0].school == "甲大学"
    assert result.experiences[0].company == "甲科技"
    assert result.projects[0].name == "Resume App"
    assert {skill.name for skill in result.skills} == {"Python", "FastAPI", "Docker"}


def test_parse_profile_text_normalizes_full_width_copy_and_formatted_phone():
    result = parse_profile_text(
        "\uff2e\uff41\uff4d\uff45: Alice\u3000\u624b\u673a: +86 138-0000-0000\n"
        "\uff25\uff44\uff55\uff43\uff41\uff54\uff49\uff4f\uff4e\n"
        "School: Example University | Major: Computer Science | Degree: Bachelor | Time: 2021-2025"
    )

    assert result.name == "Alice"
    assert result.phone == "13800000000"
    assert result.educations[0].school == "Example University"
