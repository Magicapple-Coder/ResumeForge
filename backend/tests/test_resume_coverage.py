"""覆盖度检查：资料里有、但这份简历里没写的内容，要说清是什么、为什么、怎么办。

背景是一条真实用户反馈：项目写进了资料、台账也确认了，生成出来的简历却没有它。
根因在生成链路的两道静默关卡（岗位相关性筛选、模型取舍）。这里钉住的是
"检查本身不误报、原因分类正确、提醒里带着下一步"。
"""

from __future__ import annotations

import json
import re

from app.schemas.claim import ClaimDigestOut
from app.schemas.resume import ResumeContent
from app.services.resume.resume_coverage import (
    all_entry_names,
    confirmed_claims_about,
    find_unwritten_items,
)

# 筛选前的资料里"都有谁"：两个项目、一段工作、一段校园、一个奖项、一所学校。
ENTRY_NAMES = {
    "projects": ("会员增长系统", "内部工具迁移"),
    "experiences": ("示例科技有限公司",),
    "campus_experiences": ("示例辩论队",),
    "awards": ("示例奖学金",),
    "educations": ("示例大学",),
}

# 真正发给模型的候选资料：只有「会员增长系统」这个项目被留下（另一条被相关性筛掉）。
CANDIDATES = {
    "projects": [{"name": "会员增长系统", "description": ["负责从 0 到 1 的增长"]}],
    "experiences": [{"company": "示例科技有限公司", "description": ["负责增长"]}],
    "campus_experiences": [{"organization": "示例辩论队", "description": ["队长"]}],
    "awards": [{"name": "示例奖学金"}],
    "educations": [{"school": "示例大学"}],
}


def _resume_with(*sections: str) -> ResumeContent:
    """造一份只写了指定分区的简历（其余分区留空）。"""
    return ResumeContent(
        name="张示例",
        projects=[{"name": "会员增长系统"}] if "projects" in sections else [],
        experience=[{"company": "示例科技有限公司"}] if "experience" in sections else [],
        campus_experience=[{"organization": "示例辩论队"}] if "campus_experience" in sections else [],
        awards=[{"name": "示例奖学金"}] if "awards" in sections else [],
        education=[{"school": "示例大学"}] if "education" in sections else [],
    )


def _resume_with_everything() -> ResumeContent:
    """每个分区、每一条都写了（含两个项目）。"""
    return ResumeContent(
        name="张示例",
        projects=[{"name": "会员增长系统"}, {"name": "内部工具迁移"}],
        experience=[{"company": "示例科技有限公司"}],
        campus_experience=[{"organization": "示例辩论队"}],
        awards=[{"name": "示例奖学金"}],
        education=[{"school": "示例大学"}],
    )


def test_no_warning_when_everything_was_written():
    """资料里的每一条都写进去了：一个字都不该多说。"""
    assert find_unwritten_items(_resume_with_everything(), ENTRY_NAMES, CANDIDATES) == []


def test_missing_entry_says_whether_it_reached_the_model():
    """「内部工具迁移」没进候选资料、「会员增长系统」进了但没被写——两类原因要分开。"""
    # 简历里只写了工作经历：两个项目都缺，但缺的原因不同。
    resume = _resume_with("experience")
    warnings = find_unwritten_items(resume, ENTRY_NAMES, CANDIDATES)
    project_warning = next(w for w in warnings if "项目经历" in w)

    assert "「内部工具迁移」" in project_warning
    assert "关键词交集不足" in project_warning
    assert "「会员增长系统」" in project_warning
    assert "模型没有把它写进简历" in project_warning
    # 提醒必须带着下一步，不能只说"少了东西"。
    assert "微调内容" in project_warning


def test_written_entries_are_never_reported():
    """写进去的内容绝不能被误报成缺失——宁可少报，不能冤枉。"""
    everything = {"projects": [{"name": "会员增长系统"}, {"name": "内部工具迁移"}]}
    assert find_unwritten_items(
        _resume_with_everything(), ENTRY_NAMES, {**CANDIDATES, **everything}
    ) == []


def test_missing_sections_of_an_empty_profile_are_silent():
    """资料里本来就没有的分区不产生提醒（否则每个新用户都会收到一面墙的警告）。"""
    resume = _resume_with("projects", "experience", "campus_experience", "awards", "education")
    assert find_unwritten_items(resume, {}, CANDIDATES) == []


def test_too_many_missing_entries_are_summarised_not_dumped():
    """缺一大片时列出前几条并给出总数，不把警告变成一面墙。"""
    entry_names = {"projects": tuple(f"项目{i}" for i in range(1, 9))}
    resume = _resume_with("experience")
    warnings = find_unwritten_items(resume, entry_names, {"projects": []})
    assert len(warnings) == 1
    assert "（共 8 条）" in warnings[0]
    # 列出的条目不超过上限。
    listed = re.findall(r"「([^」]+)」", warnings[0])
    assert len([name for name in listed if name.startswith("项目")]) <= 4


def test_confirmed_claims_are_matched_by_subject():
    baseline = ClaimDigestOut(
        confirmed_count=2,
        baseline_text="\n".join(
            json.dumps(entry, ensure_ascii=False)
            for entry in (
                {
                    "subject": "会员增长系统的注册转化提升了 18%",
                    "category": "项目",
                    "fact": "fact",
                    "responsibility": "主导",
                    "boundary": "",
                    "allowed_uses": "",
                },
                {
                    "subject": "示例大学期间担任班长",
                    "category": "教育",
                    "fact": "fact",
                    "responsibility": "负责",
                    "boundary": "",
                    "allowed_uses": "",
                },
            )
        ),
    )
    assert confirmed_claims_about({"会员增长系统"}, baseline) == ["会员增长系统"]
    assert confirmed_claims_about({"内部工具迁移"}, baseline) == []
    # 全部条目里有两个能对上已确认的主张。
    assert confirmed_claims_about(all_entry_names(ENTRY_NAMES), baseline) == [
        "会员增长系统",
        "示例大学",
    ]


def test_malformed_baseline_lines_do_not_break_the_check():
    baseline = ClaimDigestOut(confirmed_count=0, baseline_text="不是 JSON\n{也是坏的\n")
    assert confirmed_claims_about({"会员增长系统"}, baseline) == []
