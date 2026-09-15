"""岗位文本解析器的英文标题、元数据与分隔符测试。"""

from app.services.job_text_parser import parse_job_text


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
