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
