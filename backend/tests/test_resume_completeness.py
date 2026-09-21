"""简历完整性检查：找出没写完的位置，以及导出闸门的拦截文案。

这套检查的价值全在"导出那一刻"，所以这里既测它**找得全**（每个区块都扫），
也测它**不误报**——误报会把用户直接劝退。
"""
from app.schemas.resume import (
    ResumeAward,
    ResumeCampusExperience,
    ResumeContent,
    ResumeEducation,
    ResumeExperience,
    ResumeProject,
    ResumeSkill,
)
from app.services.resume.resume_completeness import MAX_REPORTED, find_incomplete, incomplete_detail


def test_a_finished_resume_reports_nothing():
    resume = ResumeContent(
        name="张三",
        summary="软件工程本科生，关注后端与检索系统。",
        education=[ResumeEducation(school="某大学", major="软件工程", achievements=["专业前 10%"])],
        experience=[
            ResumeExperience(company="某公司", role="后端实习生", description=["实现检索接口"])
        ],
        projects=[ResumeProject(name="检索平台", description=["负责接口设计"], highlights=["上线试运行"])],
        skills=[ResumeSkill(name="Python", level="熟练")],
        awards=[ResumeAward(name="校级奖学金", description="一等")],
    )
    assert find_incomplete(resume) == []


def test_every_section_is_scanned():
    """一个区块漏扫，用户就可能带着那一处的占位符把简历投出去。"""
    resume = ResumeContent(
        summary="总结里还有【待补：口径】",
        job_intent="意向【待确认】",
        education=[
            ResumeEducation(school="某大学", gpa="3.8/4.0【待补：排名】", courses=["课程 A【待补】"])
        ],
        experience=[ResumeExperience(company="某公司", description=["做了接口【待补：规模】"])],
        campus_experience=[ResumeCampusExperience(organization="某社团", description=["组织活动【待补】"])],
        projects=[
            ResumeProject(
                name="检索平台",
                tech_stack=["Python【待补：版本】"],
                description=["负责设计【待补】"],
                highlights=["上线【待补：用户量】"],
            )
        ],
        skills=[ResumeSkill(name="Python", level="【待补：程度】")],
        awards=[ResumeAward(name="奖学金", description="【待补：等级】")],
    )
    found = find_incomplete(resume)
    labels = " | ".join(found)
    for expected in (
        "个人总结",
        "求职意向",
        "绩点",
        "核心课程",
        "工作内容",
        "校园经历",
        "技术栈",
        "亮点",
        "专业技能",
        "荣誉奖项",
    ):
        assert expected in labels, f"漏扫了 {expected}：{labels}"
    # 定位要指到具体条目，而不是只说"简历里有占位符"。
    assert "教育经历「某大学」" in labels
    assert "项目经历「检索平台」" in labels
    assert "实习/工作经历「某公司」" in labels


def test_unfilled_names_still_get_a_readable_label():
    resume = ResumeContent(projects=[ResumeProject(name="", description=["【待补】"])])
    found = find_incomplete(resume)
    assert found and "未填项目名" in found[0]


def test_detail_message_lists_positions_and_stays_bounded():
    resume = ResumeContent(
        summary="【待补：一句】",
        experience=[
            ResumeExperience(company=f"公司{i}", description=[f"要点【待补：{i}】"]) for i in range(20)
        ],
    )
    found = find_incomplete(resume)
    assert len(found) == 21

    detail = incomplete_detail(found)
    assert "21 处" in detail
    # 只说前几条、其余用数量带过：列一百条没人看，用户只需要知道去哪儿改。
    assert f"另有 {21 - MAX_REPORTED} 处未列出" in detail
    assert "导出草稿" in detail


def test_empty_detail_is_an_empty_string():
    assert incomplete_detail([]) == ""
