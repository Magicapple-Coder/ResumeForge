"""模板预览用的示例简历内容。

工作台里"每个模板都要有预览"这件事不能依赖用户手上有简历：新装的用户打开工作台时
一条记录都没有。所以这里备一份结构完整、长度接近真实一页的示例内容——它的作用是
展示版式（标题层级、条目间距、技能标签排布），不是给用户看的简历。
"""
from __future__ import annotations

from ...schemas.resume import (
    ResumeAward,
    ResumeCampusExperience,
    ResumeContent,
    ResumeEducation,
    ResumeExperience,
    ResumeProject,
    ResumeSkill,
)

_SAMPLE_MARKER = "示例"


def sample_resume_content() -> ResumeContent:
    """跨行业的通用示例：**刻意不写技术岗**。

    工作台默认示例是每个新用户看到的第一份简历，如果它长成"后端开发 + 高并发 + Go/Redis"，
    非技术岗的用户第一眼就会觉得"这不是给我用的"。所以这里用一个不依赖具体行业的岗位
    （市场运营）与通用办公技能（活动策划、Excel、数据复盘）来展示版式。
    """
    return ResumeContent(
        name="张示例",
        job_intent="市场运营专员",
        phone="138-0000-0000",
        email="zhang@example.com",
        city="上海",
        summary="6 年市场与运营经验，主导过从 0 到 1 的会员增长项目，"
        "擅长把一次性的活动经验沉淀成可复用的流程。",
        education=[
            ResumeEducation(
                school="示例大学",
                major="市场营销",
                degree="本科",
                start_date="2019.09",
                end_date="2023.06",
                gpa="3.7/4.0",
                courses=["市场调研", "消费者行为", "应用统计"],
                achievements=["连续两年获得校级奖学金"],
            )
        ],
        experience=[
            ResumeExperience(
                company="示例科技有限公司",
                role="市场运营专员",
                start_date="2023.07",
                end_date="至今",
                description=[
                    "主导季度主题营销活动，参与人数 1.2 万，活动转化率环比提升 18%。",
                    "把活动复盘模板沉淀成 SOP，团队复用后单场筹备时间从 10 天压缩到 4 天。",
                    "对接 12 家外部渠道并建立效果台账，年度渠道成本下降 15%。",
                ],
            ),
            ResumeExperience(
                company="示例文化传播有限公司",
                role="市场部实习生",
                start_date="2022.06",
                end_date="2022.12",
                description=[
                    "负责社群日常维护与内容排期，月均产出 20 篇内容，粉丝净增 3000。",
                ],
            ),
        ],
        campus_experience=[
            ResumeCampusExperience(
                organization="示例大学学生会宣传部",
                role="副部长",
                start_date="2021.09",
                end_date="2022.06",
                description=["统筹 6 场校园活动的宣传排期，累计触达 3000 余人次。"],
            )
        ],
        projects=[
            ResumeProject(
                name="校园招聘会策划",
                role="项目负责人",
                start_date="2024.03",
                end_date="2024.06",
                tech_stack=["活动策划", "渠道对接", "预算管理"],
                description=["从 0 到 1 策划校园招聘会，到会企业 40 家、学生 1200 人。"],
                highlights=["用分时段报名数据调度入场，把现场排队时间控制在 10 分钟以内。"],
            )
        ],
        skills=[
            ResumeSkill(name="活动策划", level="熟练"),
            ResumeSkill(name="Excel", level="熟练"),
            ResumeSkill(name="数据复盘", level="掌握"),
            ResumeSkill(name="沟通协作", level="熟练"),
            ResumeSkill(name="商务英语", level="了解"),
        ],
        awards=[
            ResumeAward(name="示例大学一等奖学金", date="2021.10", description=""),
            ResumeAward(name="校级优秀学生干部", date="2021.05", description=""),
        ],
    )


__all__ = ["sample_resume_content"]
