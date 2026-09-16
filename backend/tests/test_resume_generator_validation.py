"""简历生成输出校验、隐私边界和增强选项测试。"""

import json

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import ValidationError

from app.schemas.resume import GenerateOptions
from app.services.resume_generator import (
    PROMPTS_DIR,
    ResumeGenerator,
    build_profile_prompt_data,
    check_consistency,
    coerce_resume,
    extract_json,
    split_commas,
    split_lines,
)
from tests.test_resume_generator import (
    GOOD_RESUME,
    PHOTO_DATA_URL,
    FakeProvider,
    collect_events,
    make_job,
    make_profile,
)


async def test_generate_injects_profile_photo_without_sending_it_to_llm():
    profile = make_profile(
        photo=PHOTO_DATA_URL,
        name="PRIVATE_NAME_TOKEN",
        gender="PRIVATE_GENDER_TOKEN",
        birth_year="PRIVATE_BIRTH_TOKEN",
        phone="PRIVATE_PHONE_TOKEN",
        email="private-email-token@example.com",
        city="PRIVATE_CITY_TOKEN",
        github="https://example.com/private-github-token",
        personal_website="https://example.com/private-site-token",
    )
    prompt_data = build_profile_prompt_data(profile)
    provider = FakeProvider(stream_text=json.dumps(GOOD_RESUME, ensure_ascii=False))

    events = await collect_events(ResumeGenerator(provider).generate(profile, make_job(), GenerateOptions()))
    done = next(event for event in events if event["type"] == "done")

    assert "photo" not in prompt_data
    assert PHOTO_DATA_URL not in json.dumps(prompt_data, ensure_ascii=False)
    sent_prompt = json.dumps(provider.messages, ensure_ascii=False)
    for private_value in (
        profile.name,
        profile.gender,
        profile.birth_year,
        profile.phone,
        profile.email,
        profile.city,
        profile.github,
        profile.personal_website,
    ):
        assert private_value not in sent_prompt
    assert done["resume"]["name"] == profile.name
    assert done["resume"]["phone"] == profile.phone
    assert done["resume"]["email"] == profile.email
    assert done["resume"]["photo"] == PHOTO_DATA_URL


async def test_generate_repairs_broken_json_once():
    # 首次流式输出不是 JSON，修复对话返回合法 JSON
    provider = FakeProvider(
        stream_text="抱歉，我无法生成：xxx",
        chat_replies=[json.dumps(GOOD_RESUME, ensure_ascii=False)],
    )
    events = await collect_events(ResumeGenerator(provider).generate(make_profile(), make_job(), GenerateOptions()))
    done = next(event for event in events if event["type"] == "done")
    assert done["resume"]["name"] == "张三"


async def test_generate_fails_gracefully():
    provider = FakeProvider(stream_text="彻底乱码", chat_replies=["仍然乱码"])
    events = await collect_events(ResumeGenerator(provider).generate(make_profile(), make_job(), GenerateOptions()))
    assert events[-1]["type"] == "error"
    assert "JSON" in events[-1]["message"]


@pytest.mark.parametrize(
    ("level", "instruction"),
    [
        ("light", "保持原有要点数量与职责边界"),
        ("balanced", "补足动作、方法和业务目的"),
        ("strong", "可以增加描述要点"),
    ],
)
async def test_generate_uses_explicit_enhancement_level_guide(level, instruction):
    provider = FakeProvider(stream_text=json.dumps(GOOD_RESUME, ensure_ascii=False))

    events = await collect_events(
        ResumeGenerator(provider).generate(
            make_profile(),
            make_job(),
            GenerateOptions(enhance=True, enhancement_level=level),
        )
    )

    assert events[-1]["type"] == "done"
    assert instruction in provider.messages[1]["content"]


async def test_generate_disables_expansion_by_default():
    provider = FakeProvider(stream_text=json.dumps(GOOD_RESUME, ensure_ascii=False))

    await collect_events(
        ResumeGenerator(provider).generate(make_profile(), make_job(), GenerateOptions())
    )

    assert "美化拓展已关闭" in provider.messages[1]["content"]


def test_generate_options_rejects_removed_tone_option():
    with pytest.raises(ValidationError):
        GenerateOptions.model_validate({"tone": "tech"})


def test_extract_json_tolerates_wrappers():
    assert extract_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert extract_json("前置说明 {\"a\": 1} 后置说明") == {"a": 1}
    assert extract_json("{\"resume\": {\"a\": 1}}") == {"a": 1}
    assert extract_json("") is None
    assert extract_json("没有任何花括号") is None


def test_coerce_resume_fills_defaults():
    resume = coerce_resume({"name": "李四", "education": [{"school": "某大学", "courses": "数学\n英语"}]})
    assert resume.name == "李四"
    assert resume.summary == ""
    assert resume.education[0].courses == ["数学", "英语"]
    assert resume.projects == []
    assert coerce_resume({"photo": PHOTO_DATA_URL}).photo == ""  # 不信任模型回传的照片


def test_campus_experience_is_in_prompt_and_model_output():
    profile = make_profile(
        campus_experiences=[
            {
                "id": 1,
                "organization": "学生会",
                "role": "宣传部部长",
                "start_date": "2023.09",
                "end_date": "2024.06",
                "description": "策划校园活动\n管理宣传渠道",
            }
        ]
    )

    prompt_data = build_profile_prompt_data(profile)
    assert prompt_data["campus_experiences"] == [
        {
            "organization": "学生会",
            "role": "宣传部部长",
            "start_date": "2023.09",
            "end_date": "2024.06",
            "description": ["策划校园活动", "管理宣传渠道"],
        }
    ]

    resume = coerce_resume(
        {
            "campus_experience": {
                "organization": "学生会（校级）",
                "role": "宣传部部长",
                "description": "策划校园活动\n管理宣传渠道",
            }
        }
    )
    assert resume.campus_experience[0].description == ["策划校园活动", "管理宣传渠道"]
    assert check_consistency(resume, profile) == []


def test_check_consistency_detects_unknown_campus_organization():
    profile = make_profile(campus_experiences=[{"id": 1, "organization": "学生会"}])
    resume = coerce_resume({"campus_experience": [{"organization": "青年志愿者协会"}]})

    warnings = check_consistency(resume, profile)
    assert len(warnings) == 1
    assert "青年志愿者协会" in warnings[0]


def test_coerce_resume_handles_garbage():
    resume = coerce_resume(None)
    assert resume.name == "" and resume.skills == []
    resume = coerce_resume({"education": "不是列表", "projects": [123]})
    assert resume.education == [] and resume.projects == []


def test_check_consistency_detects_hallucination():
    resume = coerce_resume(
        {
            "education": [{"school": "北京大学"}],  # 资料里没有
            "experience": [{"company": "某科技公司"}],  # 资料里有
            "projects": [{"name": "简历通（开源项目）"}],  # 轻度改写，应视为一致
        }
    )
    warnings = check_consistency(resume, make_profile())
    assert len(warnings) == 1
    assert "北京大学" in warnings[0]


def test_split_helpers():
    assert split_lines("第一行\n第二行\n\n第三行\n") == ["第一行", "第二行", "第三行"]
    assert split_commas("Python, FastAPI、React") == ["Python", "FastAPI", "React"]


def _render_system_prompt(job: bool) -> str:
    """直接渲染系统提示模板：这两种口径都只存在于文本里，没有别的抓手。"""
    env = Environment(
        loader=FileSystemLoader(PROMPTS_DIR), undefined=StrictUndefined, autoescape=False
    )
    return env.get_template("resume_generate_system.md").render(job=job)


def test_system_prompt_pins_writing_rules_for_both_modes():
    """措辞、篇幅与分模块要求是「资深 HR 版」口径，改模板时最容易整段丢。"""
    job_prompt = _render_system_prompt(job=True)
    general_prompt = _render_system_prompt(job=False)

    for prompt in (job_prompt, general_prompt):
        assert "分模块呈现要求" in prompt
        assert "不得升格职责范围" in prompt
        assert "30 字以内" in prompt
        assert "不超过 6 条" in prompt

    # 关键词融入只属于岗位模式：通用简历没有 JD，写进去只会让模型硬塞关键词。
    assert "JD 的高频关键词" in job_prompt
    assert "JD 的高频关键词" not in general_prompt
    # 通用简历的"全貌优先"是既有约束，不能被这次改口径顺手改掉。
    assert "全貌优先" in general_prompt
