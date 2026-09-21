"""简历写作增强：四个 LLM 变换 + LLM 未配置降级 + 提示词登记。"""
import json

import pytest
from pydantic import ValidationError

from app import preflight
from app.models.claim import ClaimRecord
from app.models.resume import ResumeRecord
from app.schemas.resume_writing import StarRewriteRequest
from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider, LLMError
from app.services.resume.resume_writing import (
    generate_phrases,
    polish,
    rewrite_star,
    translate,
)


class WritingProvider(BaseLLMProvider):
    """返回预设 JSON 的假模型，顺带记录它收到的消息，供断言提示词内容。"""

    def __init__(self, payload):
        super().__init__(LLMConfig(base_url="http://fake", api_key="fake", model="fake-model"))
        self.payload = payload
        self.messages: list[list[dict]] = []

    async def chat(self, messages):
        self.messages.append(messages)
        return json.dumps(self.payload, ensure_ascii=False)

    async def stream_chat(self, messages):
        yield ""


def _resume_record(db_session, **kwargs):
    record = ResumeRecord(
        title=kwargs.get("title", "张三-后端开发工程师"),
        job_title="后端开发工程师",
        company="示例公司",
        content=kwargs.get("content", {"name": "张三"}),
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


async def test_rewrite_star_returns_result_and_injects_text():
    provider = WritingProvider({"result": "负责后端服务开发，接口性能提升 30%"})
    result = await rewrite_star(provider, "负责后端服务开发")
    assert result == "负责后端服务开发，接口性能提升 30%"
    assert "负责后端服务开发" in provider.messages[0][1]["content"]


async def test_rewrite_star_injects_claim_fact_boundary():
    """带 claim 的 STAR 改写把候选表述与个人边界作为「事实边界」注入提示词。"""
    claim = ClaimRecord(
        title="后端接口优化",
        subject="示例公司",
        source_fact="负责后端接口开发",
        candidate_wording="负责后端接口开发，接口性能优化 30%",
        boundary="性能优化由团队共同完成，本人负责接口层",
    )
    provider = WritingProvider({"result": "STAR 改写结果"})
    result = await rewrite_star(provider, "负责后端接口开发", claim)

    assert result == "STAR 改写结果"
    prompt = provider.messages[0][1]["content"]
    assert "事实边界" in prompt
    assert "接口性能优化 30%" in prompt
    assert "本人负责接口层" in prompt


async def test_generate_phrases_only_fills_requested_modes():
    provider = WritingProvider({"star": "STAR 版", "resume": "简历版", "interview": "口述版"})
    result = await generate_phrases(provider, "负责后端服务开发", ["star", "resume"])
    assert result["star"] == "STAR 版"
    assert result["resume"] == "简历版"
    assert result["interview"] == ""


async def test_polish_injects_style():
    provider = WritingProvider({"result": "润色后的文本"})
    result = await polish(provider, "负责后端服务开发", "big_tech")
    assert result == "润色后的文本"
    assert "big_tech" in provider.messages[0][1]["content"]


async def test_translate_roundtrip_preserves_direction():
    zh2en = WritingProvider({"result": "responsible for backend development"})
    en2zh = WritingProvider({"result": "负责后端开发"})
    english = await translate(zh2en, "负责后端服务开发", "zh2en")
    chinese = await translate(en2zh, english, "en2zh")
    assert english == "responsible for backend development"
    assert chinese == "负责后端开发"
    assert "zh2en" in zh2en.messages[0][1]["content"]
    assert "en2zh" in en2zh.messages[0][1]["content"]


async def test_transform_rejects_empty_result():
    provider = WritingProvider({"result": ""})
    with pytest.raises(LLMError):
        await rewrite_star(provider, "负责后端服务开发")


def test_writing_prompts_are_registered_in_preflight():
    covered = {relative for relative, _ in preflight._REQUIRED_FILES}
    for name in ("resume_star.md", "resume_phrases.md", "resume_polish.md", "resume_translate.md"):
        assert f"app/prompts/{name}" in covered


def test_writing_endpoints_reject_unconfigured_llm(client, db_session):
    record = _resume_record(db_session)
    cases = [
        (f"/api/resumes/{record.id}/writing/star", {"text": "负责后端服务开发"}),
        (f"/api/resumes/{record.id}/writing/phrases", {"text": "负责后端服务开发"}),
        (
            f"/api/resumes/{record.id}/writing/polish",
            {"text": "负责后端服务开发", "style": "big_tech"},
        ),
        (
            f"/api/resumes/{record.id}/writing/translate",
            {"text": "负责后端服务开发", "direction": "zh2en"},
        ),
    ]
    for path, body in cases:
        response = client.post(path, json=body)
        assert response.status_code == 400
        assert "配置大模型" in response.json()["detail"]


def test_star_endpoint_returns_result(client, db_session, monkeypatch):
    record = _resume_record(db_session)
    provider = WritingProvider({"result": "STAR 改写结果"})
    monkeypatch.setattr("app.api.resume_writing.get_llm_config", lambda _db: provider.config)
    monkeypatch.setattr("app.api.resume_writing.create_provider", lambda _config: provider)

    response = client.post(
        f"/api/resumes/{record.id}/writing/star", json={"text": "负责后端服务开发"}
    )

    assert response.status_code == 200
    assert response.json() == {"result": "STAR 改写结果"}


def test_phrases_endpoint_returns_three_fields(client, db_session, monkeypatch):
    record = _resume_record(db_session)
    provider = WritingProvider({"star": "STAR", "resume": "简历", "interview": "口述"})
    monkeypatch.setattr("app.api.resume_writing.get_llm_config", lambda _db: provider.config)
    monkeypatch.setattr("app.api.resume_writing.create_provider", lambda _config: provider)

    response = client.post(
        f"/api/resumes/{record.id}/writing/phrases",
        json={"text": "负责后端服务开发", "modes": ["star", "resume", "interview"]},
    )

    assert response.status_code == 200
    assert response.json() == {"star": "STAR", "resume": "简历", "interview": "口述"}


def test_polish_and_translate_endpoints_return_result(client, db_session, monkeypatch):
    record = _resume_record(db_session)
    provider = WritingProvider({"result": "处理结果"})
    monkeypatch.setattr("app.api.resume_writing.get_llm_config", lambda _db: provider.config)
    monkeypatch.setattr("app.api.resume_writing.create_provider", lambda _config: provider)

    polish_response = client.post(
        f"/api/resumes/{record.id}/writing/polish",
        json={"text": "负责后端服务开发", "style": "concise_tech"},
    )
    translate_response = client.post(
        f"/api/resumes/{record.id}/writing/translate",
        json={"text": "负责后端服务开发", "direction": "zh2en"},
    )

    assert polish_response.status_code == 200
    assert polish_response.json() == {"result": "处理结果"}
    assert translate_response.status_code == 200
    assert translate_response.json() == {"result": "处理结果"}


def test_writing_endpoint_404s_for_missing_resume(client):
    response = client.post("/api/resumes/9999/writing/star", json={"text": "负责后端服务开发"})
    assert response.status_code == 404


def test_writing_schema_rejects_whitespace_only_text():
    """text 字段拦纯空白：空串与只有空格/换行的输入都在 schema 层 422。"""
    for blank in ("", "   ", "\n\t", " \n "):
        with pytest.raises(ValidationError):
            StarRewriteRequest(text=blank)
    # 有实际内容时首尾空白被 strip，但不会误伤。
    assert StarRewriteRequest(text="  负责后端服务开发  ").text == "负责后端服务开发"
