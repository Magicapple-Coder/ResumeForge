"""模板预览用的示例简历内容。

工作台里"每个模板都要有预览"这件事不能依赖用户手上有简历：新装的用户打开工作台时
一条记录都没有。所以这里备一份结构完整、长度接近真实一页的示例内容——它的作用是
展示版式（标题层级、条目间距、技能标签排布），不是给用户看的简历。
"""
from __future__ import annotations

from ..schemas.resume import (
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
    return ResumeContent(
        name="张示例",
        job_intent="后端开发工程师",
        phone="138-0000-0000",
        email="zhang@example.com",
        city="上海",
        summary="3 年服务端开发经验，负责过日均千万级请求的订单系统重构，"
        "擅长把接口耗时压到百毫秒以内。",
        education=[
            ResumeEducation(
                school="示例大学",
                major="计算机科学与技术",
                degree="本科",
                start_date="2019.09",
                end_date="2023.06",
                gpa="3.7/4.0",
                courses=["数据结构", "操作系统", "数据库系统"],
                achievements=["连续两年获得校级奖学金"],
            )
        ],
        experience=[
            ResumeExperience(
                company="示例科技有限公司",
                role="后端开发工程师",
                start_date="2023.07",
                end_date="至今",
                description=[
                    "重构订单查询链路，把 P99 耗时从 1.2 秒降到 220 毫秒。",
                    "设计分库分表方案，支撑单表数据量从 2000 万增长到 4 亿。",
                    "推动接口自动化回归覆盖率达到 85%，线上事故减少一半。",
                ],
            ),
            ResumeExperience(
                company="示例网络技术有限公司",
                role="后端开发实习生",
                start_date="2022.06",
                end_date="2022.12",
                description=[
                    "开发内部告警聚合服务，把重复告警压缩到原来的三成。",
                ],
            ),
        ],
        campus_experience=[
            ResumeCampusExperience(
                organization="示例大学计算机协会",
                role="技术部部长",
                start_date="2021.09",
                end_date="2022.06",
                description=["组织 6 场技术分享，累计参与 300 余人次。"],
            )
        ],
        projects=[
            ResumeProject(
                name="高并发短链服务",
                role="个人项目",
                start_date="2024.03",
                end_date="2024.06",
                tech_stack=["Go", "Redis", "MySQL"],
                description=["从零实现短链生成与跳转服务，单机压测 8000 QPS。"],
                highlights=["用布隆过滤器挡住无效 key，缓存穿透率降到 0.1% 以下。"],
            )
        ],
        skills=[
            ResumeSkill(name="Go", level="熟练"),
            ResumeSkill(name="Python", level="熟练"),
            ResumeSkill(name="MySQL", level="掌握"),
            ResumeSkill(name="Redis", level="掌握"),
            ResumeSkill(name="Docker", level="了解"),
        ],
        awards=[
            ResumeAward(name="示例大学一等奖学金", date="2021.10", description=""),
            ResumeAward(name="全国大学生程序设计竞赛三等奖", date="2021.05", description=""),
        ],
    )


__all__ = ["sample_resume_content"]
