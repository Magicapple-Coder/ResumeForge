"""岗位和个人资料粘贴识别接口的 AI/本地回退回归测试。"""

import json

import pytest

from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider, LLMError


class FakeExtractionProvider(BaseLLMProvider):
    def __init__(self, response: str | Exception):
        super().__init__(LLMConfig(base_url="https://model.example/v1", model="test-model"))
        self.response = response

    async def chat(self, _messages: list[dict]) -> str:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def stream_chat(self, _messages):
        yield ""


JOB_TEXT = """北京后端开发工程师 - 示例科技
工作职责：负责 Python 服务开发。
任职要求：本科及以上学历，熟悉 Python。
"""
PROFILE_TEXT = """姓名：李四
项目经历
简历工具｜后端开发｜Python
项目描述：搭建简历平台
"""


def _configure_model(client) -> None:
    response = client.put(
        "/api/settings/llm",
        json=LLMConfig(
            base_url="https://model.example/v1",
            api_key="test-key",
            model="test-model",
        ).model_dump(),
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("path", "text", "factory_path", "response", "field", "expected"),
    [
        (
            "/api/jobs/parse-text",
            JOB_TEXT,
            "app.api.jobs.create_provider",
            {
                "title": "后端开发工程师",
                "company": "示例科技",
                "location": "北京",
                "job_type": "社招",
                "description": "负责 Python 服务开发。",
                "requirements": "本科及以上学历，熟悉 Python。",
            },
            "title",
            "后端开发工程师",
        ),
        (
            "/api/profile/parse-text",
            PROFILE_TEXT,
            "app.api.profile.create_provider",
            {
                "name": "李四",
                "projects": [
                    {
                        "name": "简历工具",
                        "role": "后端开发",
                        "tech_stack": "Python",
                        "description": "搭建简历平台",
                    }
                ],
            },
            "name",
            "李四",
        ),
    ],
)
def test_parse_text_uses_configured_ai(
    client, monkeypatch, path, text, factory_path, response, field, expected
):
    _configure_model(client)
    monkeypatch.setattr(
        factory_path,
        lambda _config: FakeExtractionProvider(json.dumps(response, ensure_ascii=False)),
    )

    result = client.post(path, json={"text": text})

    assert result.status_code == 200
    assert result.json()["parse_engine"] == "ai"
    assert result.json()[field] == expected


@pytest.mark.parametrize(
    ("path", "text", "factory_path"),
    [
        ("/api/jobs/parse-text", JOB_TEXT, "app.api.jobs.create_provider"),
        ("/api/profile/parse-text", PROFILE_TEXT, "app.api.profile.create_provider"),
    ],
)
def test_parse_text_falls_back_when_ai_fails(client, monkeypatch, path, text, factory_path):
    _configure_model(client)
    monkeypatch.setattr(
        factory_path,
        lambda _config: FakeExtractionProvider(LLMError("服务不可用")),
    )

    result = client.post(path, json={"text": text})

    assert result.status_code == 200
    body = result.json()
    assert body["parse_engine"] == "local"
    assert any("本地规则" in warning for warning in body["warnings"])


@pytest.mark.parametrize(
    ("path", "text", "factory_path"),
    [
        ("/api/jobs/parse-text", JOB_TEXT, "app.api.jobs.create_provider"),
        ("/api/profile/parse-text", PROFILE_TEXT, "app.api.profile.create_provider"),
    ],
)
def test_parse_text_uses_local_parser_without_model(client, monkeypatch, path, text, factory_path):
    def fail_if_called(_config):
        raise AssertionError("未配置模型时不应创建 provider")

    monkeypatch.setattr(factory_path, fail_if_called)

    result = client.post(path, json={"text": text})

    assert result.status_code == 200
    body = result.json()
    assert body["parse_engine"] == "local"
    assert any("未配置大模型" in warning for warning in body["warnings"])
