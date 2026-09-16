"""AI 粘贴识别的离线单元测试，不访问真实模型服务。"""

import json

import pytest

from app.schemas.setting import LLMConfig
from app.schemas.job import JobTextParseResult
from app.services.job_text_parser import parse_job_text
from app.services.llm.base import BaseLLMProvider, LLMError
from app.services.profile_text_parser import parse_profile_text
from app.services.text_extraction import extract_job_text, extract_profile_text
from app.services.text_extraction_normalization import normalize_job_result


class FakeProvider(BaseLLMProvider):
    def __init__(self, response: str | Exception):
        super().__init__(LLMConfig(base_url="https://model.example/v1", model="test-model"))
        self.response = response
        self.messages: list[dict] = []

    async def chat(self, messages: list[dict]) -> str:
        self.messages = messages
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def stream_chat(self, _messages):
        yield ""


JOB_TEXT = """北京-全栈开发工程师(J103963)百度
北京市校招技术岗位 2026-07-30
工作职责：负责前端和服务端开发，参与 AI 工具建设。
职责要求：本科及以上学历，熟练使用 Python、TypeScript。
福利：弹性办公。"""


def job_response() -> str:
    return json.dumps(
        {
            "title": "全栈开发工程师",
            "company": "百度",
            "location": "北京市",
            "salary": "",
            "job_type": "校招",
            "description": "负责前端和服务端开发，参与 AI 工具建设。",
            "requirements": "本科及以上学历，熟练使用 Python、TypeScript。",
            "additional_info": "福利：弹性办公。",
            "source_url": "",
            "posted_at": "2026-07-30",
            "status": "开放中",
        },
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_extract_job_text_separates_sections_and_uses_ai_result():
    local = parse_job_text(JOB_TEXT)
    provider = FakeProvider(job_response())

    result = await extract_job_text(provider, JOB_TEXT, local)

    assert result.parse_engine == "ai"
    assert result.title == "全栈开发工程师"
    assert result.company == "百度"
    assert result.location == "北京市"
    assert result.posted_at == "2026-07-30"
    assert "前端和服务端" in result.description
    assert "本科及以上" in result.requirements
    assert "福利" in result.additional_info
    assert "不可信资料" in provider.messages[1]["content"]


@pytest.mark.asyncio
async def test_extract_job_text_accepts_markdown_fenced_json_and_grounded_fallback():
    local = parse_job_text(JOB_TEXT)
    response = "```json\n" + json.dumps(
        {"title": "不存在的岗位", "description": "负责前端和服务端开发"}, ensure_ascii=False
    ) + "\n```"

    result = await extract_job_text(FakeProvider(response), JOB_TEXT, local)

    assert result.title == local.title
    assert result.description == "负责前端和服务端开发"


@pytest.mark.asyncio
async def test_extract_job_text_keeps_local_text_when_ai_text_is_not_in_source():
    local = parse_job_text(JOB_TEXT)
    response = json.dumps(
        {
            "title": "全栈开发工程师",
            "description": "独立负责千万级分布式系统架构设计",
            "requirements": "拥有十年行业经验",
        },
        ensure_ascii=False,
    )

    result = await extract_job_text(FakeProvider(response), JOB_TEXT, local)

    assert result.description == local.description
    assert result.requirements == local.requirements


@pytest.mark.asyncio
async def test_extract_profile_text_keeps_local_entries_and_ignores_unanchored_model_facts():
    text = """姓名：李四
教育经历
天津工业大学｜软件工程｜本科｜2022-2026
项目经历
简历通｜核心开发｜Python、FastAPI
项目描述：搭建简历生成平台
技能：Python、FastAPI"""
    local = parse_profile_text(text)
    response = json.dumps(
        {
            "name": "李四",
            "projects": [
                {
                    "name": "简历通",
                    "role": "核心开发",
                    "tech_stack": "Python、FastAPI",
                    "description": "独立负责千万级用户平台架构",
                },
                {"name": "不存在的项目", "description": "虚构内容"},
            ],
            "skills": [{"name": "Python", "level": "熟练"}],
        },
        ensure_ascii=False,
    )

    result = await extract_profile_text(FakeProvider(response), text, local)

    assert result.parse_engine == "ai"
    assert result.name == "李四"
    assert [item["name"] for item in result.model_dump()["projects"]] == ["简历通"]
    assert result.model_dump()["projects"][0]["description"] == "搭建简历生成平台"
    assert result.model_dump()["skills"][0]["name"] == "Python"
    assert result.photo == ""


@pytest.mark.asyncio
async def test_extract_profile_text_rejects_invalid_model_json():
    local = parse_profile_text("姓名：李四\n技能：Python")

    with pytest.raises(LLMError, match="有效的资料识别 JSON"):
        await extract_profile_text(FakeProvider("模型暂时无法回答"), "姓名：李四", local)


@pytest.mark.asyncio
async def test_extract_job_text_propagates_provider_error_for_api_fallback():
    local = parse_job_text(JOB_TEXT)

    with pytest.raises(LLMError, match="服务不可用"):
        await extract_job_text(FakeProvider(LLMError("服务不可用")), JOB_TEXT, local)


def test_normalize_job_result_drops_ungrounded_value_without_local_fallback():
    result = normalize_job_result(
        {"title": "后端开发工程师", "company": "虚构公司"},
        JobTextParseResult(),
        "后端开发工程师",
    )

    assert result.title == "后端开发工程师"
    assert result.company == ""
