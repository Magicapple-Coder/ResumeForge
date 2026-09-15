"""个人资料解析器的推断、边界与英文输入测试。"""

from app.services.profile_text_parser import parse_profile_text


def test_parse_profile_text_extracts_unlabeled_english_identity_fields():
    result = parse_profile_text(
        "Alice Zhang | Female | born 1999 | Beijing | +86 138-0011-2233 | alice@example.com\n"
        "Education & Training\n"
        "University of Example - Computer Science - Bachelor - 2021-2025"
    )

    assert result.name == "Alice Zhang"
    assert result.gender == "Female"
    assert result.birth_year == "1999"
    assert result.city == "Beijing"
    assert result.phone == "13800112233"
    assert result.educations[0].school == "University of Example"


def test_parse_profile_text_keeps_project_role_and_period_in_unlabeled_blocks():
    result = parse_profile_text(
        "姓名：张三\n"
        "项目名称：平台项目\n"
        "角色：后端负责人\n"
        "周期：2025-2026\n"
        "描述：负责服务开发\n"
        "技能：Python、FastAPI"
    )

    assert len(result.projects) == 1
    assert result.projects[0].name == "平台项目"
    assert result.projects[0].role == "后端负责人"
    assert result.projects[0].start_date == "2025"
    assert result.projects[0].end_date == "2026"
    assert result.projects[0].description == "负责服务开发"
    assert result.experiences == []


def test_parse_profile_text_splits_inline_chinese_education_and_work_headers():
    result = parse_profile_text(
        "姓名：张三\n"
        "教育背景：2020-2024 甲大学 软件工程 本科\n"
        "工作经历：2024-2025 甲科技 后端工程师\n"
        "项目经历：2025-2026 平台项目 项目负责人"
    )

    assert result.educations[0].school == "甲大学"
    assert result.educations[0].major == "软件工程"
    assert result.educations[0].degree == "本科"
    assert result.experiences[0].company == "甲科技"
    assert result.experiences[0].role == "后端工程师"
    assert result.projects[0].name == "平台项目"
    assert result.projects[0].role == "项目负责人"


def test_parse_profile_text_allows_strong_project_field_after_an_explicit_section():
    result = parse_profile_text(
        "教育背景：2020-2024 甲大学 软件工程 本科\n"
        "项目名称：简历平台\n"
        "角色：后端负责人\n"
        "周期：2024-2025\n"
        "技术栈：Python、FastAPI"
    )

    assert len(result.educations) == 1
    assert result.projects[0].name == "简历平台"
    assert result.projects[0].role == "后端负责人"
    assert result.projects[0].tech_stack == "Python、FastAPI"


def test_parse_profile_text_infers_unlabeled_campus_fields():
    result = parse_profile_text(
        "组织名称：计算机学院学生会\n角色：技术部负责人\n周期：2023-2024\n描述：组织校园技术活动"
    )

    assert result.campus_experiences[0].organization == "计算机学院学生会"
    assert result.campus_experiences[0].role == "技术部负责人"
    assert result.campus_experiences[0].start_date == "2023"
    assert result.campus_experiences[0].end_date == "2024"


def test_parse_profile_text_splits_inline_english_project_fields_without_touching_name():
    result = parse_profile_text(
        "Project Name: Resume App / Role: Backend Developer / Period: 2024-2025\n"
        "Tech Stack: Python, FastAPI"
    )

    assert result.name == ""
    assert result.birth_year == ""
    assert result.projects[0].name == "Resume App"
    assert result.projects[0].role == "Backend Developer"
    assert result.projects[0].start_date == "2024"
    assert result.projects[0].end_date == "2025"
    assert result.projects[0].tech_stack == "Python、FastAPI"


def test_parse_profile_text_bounds_overlong_parsed_fields_instead_of_failing():
    project_name = "x" * 200
    result = parse_profile_text(f"项目名称：{project_name}\n角色：开发")

    assert result.projects[0].name == project_name[:128]
    assert any("超过可保存长度" in warning for warning in result.warnings)


def test_parse_profile_text_supports_employment_aliases_without_splitting_records():
    result = parse_profile_text(
        "姓名：李明\n"
        "企业：Acme\n"
        "工作职位：Backend Engineer\n"
        "Employment Dates: 2024 - Present\n"
        "工作内容：Build APIs"
    )

    assert len(result.experiences) == 1
    assert result.experiences[0].company == "Acme"
    assert result.experiences[0].role == "Backend Engineer"
    assert result.experiences[0].start_date == "2024"
    assert result.experiences[0].end_date == "Present"
    assert result.experiences[0].description == "Build APIs"


def test_parse_profile_text_infers_unheaded_company_role_date_sequence():
    result = parse_profile_text("姓名：王五\n某科技公司\n算法实习生\n2024-2025\n负责模型训练")

    assert len(result.experiences) == 1
    assert result.experiences[0].company == "某科技公司"
    assert result.experiences[0].role == "算法实习生"
    assert result.experiences[0].start_date == "2024"
    assert result.experiences[0].end_date == "2025"
    assert result.experiences[0].description == "负责模型训练"


def test_parse_profile_text_infers_unheaded_student_organization_sequence():
    result = parse_profile_text("姓名：王五\n学生会\n团支书\n2023-2024\n组织校园活动")

    assert result.experiences == []
    assert len(result.campus_experiences) == 1
    assert result.campus_experiences[0].organization == "学生会"
    assert result.campus_experiences[0].role == "团支书"


def test_parse_profile_text_normalizes_versioned_and_ci_cd_skill_entries():
    result = parse_profile_text("专业技能\nTech: Python 3.10, CI/CD pipelines, Fast API")

    assert {skill.name for skill in result.skills} == {"Python", "CI/CD", "FastAPI"}
