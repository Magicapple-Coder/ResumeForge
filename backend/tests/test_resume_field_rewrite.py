"""按栏定向改写：路径解析必须精确，且服务端不落库。

这条能力的风险点不在模型，而在**路径**：路径解析错一位，用户点了"项目第 2 条要点"，
AI 改的却可能是另一栏。所以这里把"能改哪些位置、指不到时怎么报错"钉死。
"""

from __future__ import annotations

import pytest

from app.schemas.resume import ResumeContent
from app.services.resume.resume_field_rewrite import (
    FieldPathError,
    resolve_field_target,
    rewrite_field,
)


def _content() -> ResumeContent:
    return ResumeContent(
        name="张示例",
        summary="一段总结",
        education=[{"school": "示例大学", "major": "示例专业"}],
        experience=[
            {
                "company": "示例科技有限公司",
                "role": "示例岗位",
                "description": ["负责示例模块开发"],
            }
        ],
        projects=[
            {
                "name": "会员增长系统",
                "role": "前端负责人",
                "description": ["第一条要点", "第二条要点"],
                "highlights": ["亮点"],
            }
        ],
        skills=[{"name": "Python", "level": "熟练"}],
    )


def test_top_level_scalar_path():
    target = resolve_field_target(_content(), "summary")
    assert target.text == "一段总结"
    assert target.label == "个人总结"
    assert target.context == ""


def test_list_item_path_carries_its_own_context():
    """改的是"某条要点"，那就必须知道它属于哪个项目——否则模型只能瞎猜语气。"""
    target = resolve_field_target(_content(), "projects.0.description.1")
    assert target.text == "第二条要点"
    assert "会员增长系统" in target.label
    assert "第 2 条" in target.label
    assert "会员增长系统" in target.context
    assert "前端负责人" in target.context


def test_item_scalar_path():
    target = resolve_field_target(_content(), "experience.0.company")
    assert target.text == "示例科技有限公司"
    assert "示例科技有限公司" in target.context


def test_paths_that_point_nowhere_are_rejected():
    """宁可报错，也不要"猜一个最接近的"——那可能改到别的字段上。"""
    content = _content()
    for path in (
        "",
        "   ",
        "not_a_field",
        "projects",
        "projects.x.description",
        "projects.9.name",
        "projects.0.description.9",
        "projects.0.nope",
        "projects.0.description.0.too.deep",
        "summary.extra",
    ):
        with pytest.raises(FieldPathError):
            resolve_field_target(content, path)


@pytest.mark.asyncio
async def test_rewrite_field_returns_model_text_without_touching_the_resume():
    """服务端只返回建议：它拿到的 ResumeContent 是副本，任何情况下都不该被改。"""
    captured: dict[str, str] = {}

    class FakeProvider:
        async def chat(self, messages):
            captured["prompt"] = messages[-1]["content"]
            return '{"text": "改写后的要点"}'

    content = _content()
    target = resolve_field_target(content, "projects.0.description.0")
    result = await rewrite_field(FakeProvider(), target, "再短一点")

    # 单段（text）返回长度 1 的列表：调用方按 `kind` 决定回填成文本还是一条列表。
    assert result == ["改写后的要点"]
    # 提示词里必须同时有"原文""这一栏是什么""用户要求"三样。
    assert "第一条要点" in captured["prompt"]
    assert "会员增长系统" in captured["prompt"]
    assert "再短一点" in captured["prompt"]
    # 原内容一字未动。
    assert content.projects[0].description[0] == "第一条要点"


def test_whole_segment_path_returns_lines_kind():
    """「重新生成这段实习的工作内容」= 整段路径，形状是 lines。"""
    target = resolve_field_target(_content(), "experience.0.description")
    assert target.kind == "lines"
    assert target.text == "负责示例模块开发"
    assert "要点" in target.label

    target2 = resolve_field_target(_content(), "projects.0.description")
    assert target2.kind == "lines"
    # 给模型看的是"一行一条"的原文。
    assert target2.text == "第一条要点\n第二条要点"
    assert "整段" in target2.label and "2 条" in target2.label


@pytest.mark.asyncio
async def test_rewrite_whole_segment_asks_for_a_list_and_returns_one():
    """整段改写必须要求模型按条返回——糊成一段会把简历排版弄塌（原本一行一条）。"""
    captured: dict[str, str] = {}

    class FakeProvider:
        async def chat(self, messages):
            captured["prompt"] = messages[-1]["content"]
            return '{"lines": ["新第一条", "新第二条", "新第三条"]}'

    target = resolve_field_target(_content(), "projects.0.description")
    result = await rewrite_field(FakeProvider(), target, "各加一个数字")

    assert result == ["新第一条", "新第二条", "新第三条"]
    # 提示词里要出现"按条返回"的形状说明，否则模型很可能给一段话。
    assert "lines" in captured["prompt"]


@pytest.mark.asyncio
async def test_rewrite_whole_segment_rejects_a_plain_paragraph():
    """整段路径下模型只回了一段话：必须报错，不能塞进列表里当成一条。"""
    from app.services.resume.resume_field_rewrite import MAX_FIELD_LINES

    class FakeProvider:
        async def chat(self, messages):
            return '{"text": "一整段话"}'

    target = resolve_field_target(_content(), "projects.0.description")
    with pytest.raises(ValueError):
        await rewrite_field(FakeProvider(), target, "各加一个数字")

    # 上限也要挡住"一口气写 30 条"的模型。
    assert MAX_FIELD_LINES >= 5


@pytest.mark.asyncio
async def test_rewrite_field_rejects_an_empty_model_answer():
    class FakeProvider:
        async def chat(self, messages):
            return '{"text": "   "}'

    target = resolve_field_target(_content(), "summary")
    with pytest.raises(ValueError):
        await rewrite_field(FakeProvider(), target, "再短一点")
