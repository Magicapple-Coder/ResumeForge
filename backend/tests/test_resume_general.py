"""通用简历（不关联岗位）的筛选、生成与接口行为。

这一组用例的重点是**别退化成"传个空 job 走岗位路径"**：那条路径在没有岗位信号时
会丢掉校园经历、奖项、大部分技能和个人总结，而且丢得悄无声息。
"""

import json

import pytest

from app.schemas.resume import GenerateOptions
from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider
from app.services.profile.profile_relevance import build_general_profile_context
from app.services.resume.resume_generator import ResumeGenerator
from tests.test_profile_relevance import (
    CapturingProvider,
    make_diverse_profile,
    make_job,
    prompt_candidate_data,
)

AWARD = {"id": 1, "name": "国家励志奖学金", "date": "2024.10", "description": "专业前 5%"}


def make_profile_with_awards(**overrides):
    overrides.setdefault("awards", [AWARD])
    return make_diverse_profile(**overrides)


def section_names(data: dict, section: str) -> list[str]:
    field = {"educations": "school", "experiences": "company", "campus_experiences": "organization",
             "projects": "name", "skills": "name", "awards": "name"}[section]
    return [item[field] for item in data[section]]


# ===== 候选资料筛选 =====


def test_general_context_keeps_campus_awards_skills_and_summary():
    """无岗位信号时最容易悄悄丢掉的四类内容，必须原样保留。"""
    profile = make_profile_with_awards()
    selection = build_general_profile_context(profile)
    data = selection.data

    assert section_names(data, "campus_experiences") == ["校学生会"]
    assert section_names(data, "awards") == ["国家励志奖学金"]
    # 技能不做"只保留被经历提到的那些"的过滤：10 项全部保留（栏目上限是 14）
    assert section_names(data, "skills") == [item.name for item in profile.skills]
    # 个人总结保留用户自己写的那份，不被清空
    assert data["summary"] == profile.summary
    # 求职意向沿用资料原文，不被任何岗位名替换
    assert data["job_intent"] == profile.job_intent


def test_general_context_keeps_profile_order_and_respects_limits():
    profile = make_profile_with_awards()
    selection = build_general_profile_context(profile)

    # 顺序沿用用户录入顺序，不做任何打分重排
    assert section_names(selection.data, "experiences") == [
        "星云云服务",
        "青年创新中心",
    ][: len(section_names(selection.data, "experiences"))]
    assert selection.data == json.loads(selection.serialized)


def test_general_context_still_drops_items_without_a_primary_field():
    profile = make_profile_with_awards(
        awards=[AWARD, {"id": 2, "name": "", "date": "2023.01", "description": "无名奖项"}]
    )

    selection = build_general_profile_context(profile)

    assert section_names(selection.data, "awards") == ["国家励志奖学金"]


def test_general_context_keeps_reference_facts():
    """附件事实不能因为"没有岗位可打分"就被清空。"""
    profile = make_diverse_profile(
        projects=[
            {
                "id": 1,
                "name": "在线预约服务",
                "role": "后端开发",
                "reference_file_name": "总结.md",
                "reference_content": "实现预约与排班 API\n设计 Redis 缓存和数据库查询",
            }
        ]
    )

    selection = build_general_profile_context(profile, include_references=True)

    project = selection.data["projects"][0]
    assert project["reference_file_name"] == "总结.md"
    assert project["reference_facts"]


# ===== 生成 =====


async def _run_general_generation(profile, options=None):
    provider = CapturingProvider(
        {
            "summary": "覆盖后端与运营两个方向。",
            "campus_experience": [{"organization": "校学生会", "role": "宣传部部长"}],
            "awards": [{"name": "国家励志奖学金", "date": "2024.10"}],
            "projects": [{"name": "在线预约服务", "role": "后端开发"}],
            "skills": [{"name": "Python", "level": "熟练"}],
        }
    )
    events = [
        event
        async for event in ResumeGenerator(provider).generate(
            profile, None, options or GenerateOptions()
        )
    ]
    return provider, events


@pytest.mark.asyncio
async def test_generation_without_a_job_drops_job_framing():
    profile = make_profile_with_awards()

    provider, events = await _run_general_generation(profile)

    system_prompt = provider.messages[0]["content"]
    user_prompt = provider.messages[1]["content"]
    assert "岗位匹配" not in system_prompt
    assert "已经过岗位筛选" not in system_prompt
    assert "全貌优先" in system_prompt
    assert "## 目标岗位" not in user_prompt
    assert "## 岗位 JD" not in user_prompt
    assert "通用简历说明" in user_prompt

    candidate = prompt_candidate_data(provider.messages)
    assert section_names(candidate, "campus_experiences") == ["校学生会"]
    assert section_names(candidate, "awards") == ["国家励志奖学金"]

    done = next(event for event in events if event["type"] == "done")
    assert done["resume"]["campus_experience"]
    assert done["resume"]["awards"]
    assert done["resume"]["job_intent"] == profile.job_intent


@pytest.mark.asyncio
async def test_job_generation_still_uses_job_framing():
    """对照用例：有岗位时口径不变。"""
    profile = make_profile_with_awards()
    job = make_job("后端开发工程师", "负责后端服务开发", "熟悉 Python")

    provider = CapturingProvider({"summary": "具备后端开发能力。", "skills": []})
    async for _ in ResumeGenerator(provider).generate(profile, job, GenerateOptions()):
        pass

    assert "岗位匹配" in provider.messages[0]["content"]
    assert "## 目标岗位" in provider.messages[1]["content"]
    assert "## 岗位 JD" in provider.messages[1]["content"]


@pytest.mark.asyncio
async def test_general_generation_warns_when_content_exceeds_the_budget():
    # 造出超过栏目上限的资料，触发 omitted_count
    profile = make_profile_with_awards(
        awards=[{**AWARD, "id": index, "name": f"奖项{index}"} for index in range(1, 6)]
    )

    _, events = await _run_general_generation(profile)

    done = next(event for event in events if event["type"] == "done")
    assert any("篇幅预算" in warning for warning in done["warnings"])
    # 说明白这是通用简历，别让用户以为资料被按岗位筛掉了
    assert any("不按岗位筛选" in warning for warning in done["warnings"])


@pytest.mark.asyncio
async def test_general_generation_does_not_claim_a_target_job_in_warnings():
    profile = make_profile_with_awards()

    _, events = await _run_general_generation(profile)

    done = next(event for event in events if event["type"] == "done")
    assert not any("本岗位候选资料" in warning for warning in done["warnings"])


# ===== 接口 =====


def _configure(client):
    config = LLMConfig(
        base_url="https://api.example.com/v1", api_key="k", model="m"
    )
    assert client.put("/api/settings/llm", json=config.model_dump()).status_code == 200


def _seed_profile(client):
    assert (
        client.put(
            "/api/profile",
            json={"name": "张三", "job_intent": "后端开发", "summary": "熟悉 Python。"},
        ).status_code
        == 200
    )


def _fake_general_provider(monkeypatch):
    class Provider(BaseLLMProvider):
        async def chat(self, _messages):
            raise AssertionError("合法流式 JSON 不应触发修复调用")

        async def stream_chat(self, _messages):
            yield json.dumps(
                {"summary": "覆盖多方向的经历。", "job_intent": "后端开发"},
                ensure_ascii=False,
            )

    monkeypatch.setattr("app.api.resumes.create_provider", lambda resolved: Provider(resolved))


def _events(response) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_generate_without_a_job_creates_a_general_resume(client, monkeypatch):
    _seed_profile(client)
    _configure(client)
    _fake_general_provider(monkeypatch)

    response = client.post("/api/resumes/generate", json={})

    assert response.status_code == 200
    saved = next(event for event in _events(response) if event["type"] == "saved")
    record = client.get(f"/api/resumes/{saved['record_id']}").json()
    assert record["job_id"] is None
    assert record["company"] == ""
    # 无岗位时 job_title 存求职意向，与手写简历的既有约定一致
    assert record["job_title"] == "后端开发"
    assert "通用简历" in record["title"]


def test_generate_accepts_a_requested_title(client, monkeypatch):
    _seed_profile(client)
    _configure(client)
    _fake_general_provider(monkeypatch)

    response = client.post("/api/resumes/generate", json={"title": "研发通用版"})

    saved = next(event for event in _events(response) if event["type"] == "saved")
    assert client.get(f"/api/resumes/{saved['record_id']}").json()["title"] == "研发通用版"


def test_generate_still_404s_for_an_unknown_job(client, monkeypatch):
    _seed_profile(client)
    _configure(client)
    _fake_general_provider(monkeypatch)

    response = client.post("/api/resumes/generate", json={"job_id": 999})

    assert response.status_code == 404


def test_generate_persists_style_and_format_template(client, monkeypatch):
    """真实环境跑出来的问题：生成时选的版式没有存进记录，重开预览/导出就悄悄退回默认。

    样式与格式是两个独立选择，都要跟着记录走——漏掉任何一个，用户都会觉得"我选的没生效"。
    """
    _seed_profile(client)
    _configure(client)
    _fake_general_provider(monkeypatch)
    assert (
        client.post(
            "/api/resume-templates",
            json={"name": "紧凑版式", "kind": "format", "config": {"line_height": 1.45}},
        ).status_code
        == 201
    )

    response = client.post(
        "/api/resumes/generate",
        json={
            "options": {
                "enhance": False,
                "enhancement_level": "balanced",
                "page_limit": 2,
                "font_scale": "small",
                "template": "elegant",
                "format_name": "紧凑版式",
                "custom_instruction": "",
            }
        },
    )

    record_id = next(event for event in _events(response) if event["type"] == "saved")["record_id"]
    record = client.get(f"/api/resumes/{record_id}").json()
    assert record["template"] == "elegant"
    assert record["format_name"] == "紧凑版式"
    assert record["page_limit"] == 2
    assert record["font_scale"] == "small"


def test_generate_drops_an_unknown_format_template(client, monkeypatch):
    """格式模板名解析不出来时存空串：存一个查不到的引用会让导出拿不到配置。"""
    _seed_profile(client)
    _configure(client)
    _fake_general_provider(monkeypatch)

    response = client.post("/api/resumes/generate", json={"options": {"format_name": "并不存在"}})

    record_id = next(event for event in _events(response) if event["type"] == "saved")["record_id"]
    assert client.get(f"/api/resumes/{record_id}").json()["format_name"] == ""


def test_list_can_filter_general_resumes_only(client, monkeypatch):
    _seed_profile(client)
    _configure(client)
    _fake_general_provider(monkeypatch)
    job = client.post("/api/jobs", json={"title": "后端开发工程师", "company": "示例公司"}).json()

    general = client.post("/api/resumes/generate", json={})
    general_id = next(e for e in _events(general) if e["type"] == "saved")["record_id"]
    linked = client.post("/api/resumes/generate", json={"job_id": job["id"]})
    linked_id = next(e for e in _events(linked) if e["type"] == "saved")["record_id"]

    only_general = client.get("/api/resumes?has_job=false").json()
    only_linked = client.get("/api/resumes?has_job=true").json()
    everything = client.get("/api/resumes").json()

    assert {item["id"] for item in only_general["items"]} == {general_id}
    assert {item["id"] for item in only_linked["items"]} == {linked_id}
    assert {item["id"] for item in everything["items"]} == {general_id, linked_id}

    # 与既有过滤条件可以叠加
    combined = client.get("/api/resumes?has_job=false&favorite=true").json()
    assert combined["total"] == 0


def test_rename_a_resume(client, monkeypatch):
    _seed_profile(client)
    _configure(client)
    _fake_general_provider(monkeypatch)
    created = client.post("/api/resumes/generate", json={})
    record_id = next(e for e in _events(created) if e["type"] == "saved")["record_id"]
    before = client.get(f"/api/resumes/{record_id}").json()

    response = client.patch(f"/api/resumes/{record_id}", json={"title": "  研发通用版  "})

    assert response.status_code == 200
    after = response.json()
    assert after["title"] == "研发通用版"
    # 改名不该动正文与告警
    assert after["content"] == before["content"]
    assert after["warnings"] == before["warnings"]


def test_rename_rejects_a_blank_title_and_missing_record(client, monkeypatch):
    _seed_profile(client)
    _configure(client)
    _fake_general_provider(monkeypatch)
    created = client.post("/api/resumes/generate", json={})
    record_id = next(e for e in _events(created) if e["type"] == "saved")["record_id"]

    assert client.patch(f"/api/resumes/{record_id}", json={"title": "   "}).status_code == 422
    assert client.patch("/api/resumes/9999", json={"title": "x"}).status_code == 404
