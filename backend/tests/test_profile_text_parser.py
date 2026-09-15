"""个人资料粘贴识别的规则测试。"""

from app.services.profile_text_parser import parse_profile_text


PROFILE_TEXT = """姓名：张三
邮箱：zhangsan@example.com
手机号：13800000000
求职意向：后端开发工程师

教育经历
天津工业大学｜软件工程｜本科｜2022.09-2026.06
核心课程：数据结构、数据库

实习经历
某科技公司｜后端开发实习生｜2025.06-2025.09
负责 FastAPI 服务开发

校园经历
学生会｜宣传部部长｜2023.09-2024.06
策划校园活动

项目经历
简历通｜核心开发｜2025.01-至今
技术栈：Python、FastAPI、React
项目描述：搭建简历平台
亮点：支持岗位导向简历生成

专业技能
Python（熟练）、FastAPI、SQL

荣誉奖项
奖学金｜2024.10

个人总结
具备后端开发和项目协作经验。"""


def test_parse_profile_text_extracts_sections_and_basic_fields():
    result = parse_profile_text(PROFILE_TEXT)

    assert result.name == "张三"
    assert result.email == "zhangsan@example.com"
    assert result.phone == "13800000000"
    assert result.job_intent == "后端开发工程师"
    assert result.educations[0].school == "天津工业大学"
    assert result.educations[0].courses == "数据结构、数据库"
    assert result.experiences[0].company == "某科技公司"
    assert result.campus_experiences[0].role == "宣传部部长"
    assert result.projects[0].tech_stack == "Python、FastAPI、React"
    assert result.projects[0].highlights == "支持岗位导向简历生成"
    assert {skill.name for skill in result.skills} == {"Python", "FastAPI", "SQL"}
    assert result.awards[0].name == "奖学金"
    assert result.summary == "具备后端开发和项目协作经验。"
    assert result.warnings == []


def test_parse_profile_text_warns_when_no_useful_section_is_found():
    result = parse_profile_text("这是一段无法识别结构的介绍")

    assert any("姓名" in warning for warning in result.warnings)
    assert any("分区" in warning for warning in result.warnings)


def test_parse_profile_text_accepts_numbered_synonym_headings_and_inline_content():
    """复制自不同简历模板的标题通常带编号、括号或英文说明。"""
    text = """个人信息
张三 | 男 | 2001年生 | 广州 | 13800000000 | zhangsan@example.com

一、教育背景（Education）
2022/09 ~ 2026/06 - 华南理工大学 - 计算机科学与技术 - 本科
核心课程：数据结构；计算机网络

2. 任职履历：
2025.06—至今 / 星河科技 / 后端开发工程师
工作内容：负责接口和数据服务开发

三、项目经验（Projects）
ResumeForge / 全栈开发 / 2025.01-现在
技术能力：Python、FastAPI、React
项目成果：完成简历生成平台

四、技术能力：熟练掌握 Python、FastAPI；精通 React；Docker（了解）

五、个人简介：具备后端开发和项目协作经验。"""

    result = parse_profile_text(text)

    assert result.name == "张三"
    assert result.gender == "男"
    assert result.birth_year == "2001年生"
    assert result.city == "广州"
    assert result.educations[0].school == "华南理工大学"
    assert result.educations[0].major == "计算机科学与技术"
    assert result.educations[0].degree == "本科"
    assert result.educations[0].start_date == "2022/09"
    assert result.educations[0].end_date == "2026/06"
    assert result.experiences[0].company == "星河科技"
    assert result.experiences[0].role == "后端开发工程师"
    assert result.projects[0].name == "ResumeForge"
    assert result.projects[0].role == "全栈开发"
    assert "Python" in result.projects[0].tech_stack
    assert result.projects[0].highlights == "完成简历生成平台"
    assert {skill.name for skill in result.skills} >= {"Python", "FastAPI", "React", "Docker"}
    skill_levels = {skill.name: skill.level for skill in result.skills}
    assert skill_levels["Python"] in {"熟练掌握", "熟练"}
    assert skill_levels["React"] == "精通"
    assert skill_levels["Docker"] == "了解"
    assert result.summary == "具备后端开发和项目协作经验。"


def test_parse_profile_text_splits_contiguous_labeled_entries_without_blank_lines():
    """有些招聘网站复制文本会去掉空行，显式字段仍应启动下一条记录。"""
    text = """教育经历
学校：甲大学 专业：软件工程 学位：本科 时间：2020-2024
课程：算法、数据库
学校：乙大学 专业：计算机科学 学位：硕士 时间：2024-2026
课程：机器学习
工作经历
公司：甲科技 职位：后端工程师 时间：2024.06-2025.06
描述：负责服务开发
公司：乙网络 岗位：平台工程师 时间：2025.07-至今
职责：负责稳定性建设"""

    result = parse_profile_text(text)

    assert [item.school for item in result.educations] == ["甲大学", "乙大学"]
    assert [item.company for item in result.experiences] == ["甲科技", "乙网络"]
    assert result.experiences[1].role == "平台工程师"


def test_parse_profile_text_splits_contiguous_entries_with_company_aliases():
    """条目边界必须覆盖字段解析支持的中英文公司别名。"""
    result = parse_profile_text(
        "工作经历\n"
        "Company: Acme | Position: Backend Engineer | Employment Dates: 2024-2025\n"
        "就职公司：Beta 科技 | 工作职位：平台工程师 | 任职期间：2025-至今"
    )

    assert [item.company for item in result.experiences] == ["Acme", "Beta 科技"]
    assert [item.role for item in result.experiences] == ["Backend Engineer", "平台工程师"]
    assert result.experiences[1].start_date == "2025"
    assert result.experiences[1].end_date == "至今"


def test_parse_profile_text_handles_unlabeled_headers_and_skill_aliases():
    text = """李四｜北京｜13900000000｜lisi@example.com
Education / 教育经历
北京大学-软件工程-硕士-2022-2025
Work Experience / 工作履历
远航科技-服务端开发-2025.07-至今
Campus Experience / 校园实践
计算机学院学生会-技术部负责人-2023/09-2024/06
Projects / 项目履历
校园服务平台-后端负责人-2024.03-2024.12
技术栈：Golang、Vue.js、MySQL数据库、K8s
技能清单
编程语言：Python：熟练、JS（精通）、C++ - 掌握
数据库：MySQL（熟练使用）
技术能力：熟悉 Docker、NodeJS 等工具"""

    result = parse_profile_text(text)

    assert result.name == "李四"
    assert result.city == "北京"
    assert result.educations[0].school == "北京大学"
    assert result.educations[0].major == "软件工程"
    assert result.experiences[0].company == "远航科技"
    assert result.campus_experiences[0].organization == "计算机学院学生会"
    assert result.projects[0].name == "校园服务平台"
    assert result.projects[0].tech_stack == "Golang、Vue.js、MySQL数据库、K8s"

    levels = {item.name: item.level for item in result.skills}
    assert levels["Python"] == "熟练"
    assert levels["JavaScript"] == "精通"
    assert levels["C++"] == "掌握"
    assert levels["MySQL"] == "熟练使用"
    assert levels["Docker"] == "熟悉"
    assert levels["Node.js"] == "熟悉"


def test_parse_profile_text_keeps_multiline_entry_fields_in_one_record():
    """字段分行而空行丢失时，专业、角色和日期仍属于同一条经历。"""
    text = """王五 男 2002年 北京 13700000000 wangwu@example.com
教育履历
学校：清华大学
专业：计算机科学与技术
学历：硕士
起止时间：2024-2027
核心课程：分布式系统、数据库
工作履历
公司：云帆科技
部门：平台研发部
职位：后端开发工程师
任职时间：2026.06-至今
职责：负责服务架构设计
项目履历
项目名称：简历优化平台
担任角色：后端负责人
项目周期：2025.01-2025.12
技术方案：Python、FastAPI、PostgreSQL"""

    result = parse_profile_text(text)

    assert result.name == "王五"
    assert result.gender == "男"
    assert result.birth_year == "2002年"
    assert result.educations[0].school == "清华大学"
    assert result.educations[0].major == "计算机科学与技术"
    assert result.educations[0].degree == "硕士"
    assert result.educations[0].start_date == "2024"
    assert result.experiences[0].company == "云帆科技"
    assert result.experiences[0].role == "后端开发工程师"
    assert result.experiences[0].description == "负责服务架构设计"
    assert result.projects[0].name == "简历优化平台"
    assert result.projects[0].role == "后端负责人"
    assert result.projects[0].tech_stack == "Python、FastAPI、PostgreSQL"


def test_parse_profile_text_separates_phone_and_email_from_generic_contact_label():
    result = parse_profile_text(
        "姓名：赵六\n联系方式：13912345678 / zhaoliu@example.com\n个人简介：熟悉后端服务"
    )

    assert result.phone == "13912345678"
    assert result.email == "zhaoliu@example.com"


def test_parse_profile_text_supports_english_header_labels_and_degree_names():
    result = parse_profile_text(
        "Education\n"
        "School: University of Example | Major: Computer Science | Degree: Bachelor | Time: 2021-2025\n"
        "Courses: Algorithms, Databases\n"
        "Work Experience\n"
        "Company: Example Inc | Position: Backend Engineer | Period: 2025-present\n"
        "Responsibilities: Built internal services."
    )

    assert result.educations[0].school == "University of Example"
    assert result.educations[0].major == "Computer Science"
    assert result.educations[0].degree == "Bachelor"
    assert result.educations[0].start_date == "2021"
    assert result.educations[0].end_date == "2025"
    assert result.educations[0].courses == "Algorithms、Databases"
    assert result.experiences[0].company == "Example Inc"
    assert result.experiences[0].role == "Backend Engineer"
    assert result.experiences[0].end_date == "present"
    assert result.experiences[0].description == "Built internal services."


def test_parse_profile_text_does_not_split_on_dates_inside_long_descriptions():
    result = parse_profile_text(
        "项目经历\n"
        "项目A | 后端开发 | 2024-2025\n"
        "项目描述：2024-2025 完成服务迁移并持续优化性能。\n"
        "亮点：将接口耗时降低 30%。"
    )

    assert len(result.projects) == 1
    assert "2024-2025 完成服务迁移" in result.projects[0].description


def test_parse_profile_text_supports_multiline_synonym_fields_without_splitting_entries():
    result = parse_profile_text(
        "姓名：张三\n"
        "工作履历\n"
        "公司名称：星河科技有限公司\n"
        "岗位名称：后端开发工程师\n"
        "任职期间：2024.01-至今\n"
        "工作内容：负责服务端开发\n"
        "技能特长\n"
        "熟练使用：Python、Fast API、Vue.js、Postgres、K8s"
    )

    assert len(result.experiences) == 1
    assert result.experiences[0].company == "星河科技有限公司"
    assert result.experiences[0].role == "后端开发工程师"
    assert result.experiences[0].start_date == "2024.01"
    assert result.experiences[0].end_date == "至今"
    assert result.experiences[0].description == "负责服务端开发"
    assert {skill.name for skill in result.skills} >= {
        "Python",
        "FastAPI",
        "Vue",
        "PostgreSQL",
        "Kubernetes",
    }

