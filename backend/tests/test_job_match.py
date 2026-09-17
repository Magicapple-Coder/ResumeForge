"""匹配分析离线测试：五类状态、证据锚定、禁分数、硬门槛、准入映射、本地降级、招呼语。"""
import json
from types import SimpleNamespace

import pytest

from app.schemas.setting import LLMConfig
from app.services.job_match import (
    analyze_match,
    build_match_messages,
    finalize_match_result,
    generate_greeting,
    job_payload,
    local_match_result,
    parse_greeting,
    parse_match_result,
)
from app.services.llm.base import BaseLLMProvider, LLMError


class ScriptedProvider(BaseLLMProvider):
    def __init__(self, response: str):
        super().__init__(LLMConfig(base_url="http://fake", model="fake-model"))
        self.response = response
        self.messages: list[dict] | None = None

    async def chat(self, messages: list[dict]) -> str:
        self.messages = messages
        return self.response

    async def stream_chat(self, messages: list[dict]):  # pragma: no cover - 未用到
        yield ""


def _payload() -> dict:
    return job_payload(
        SimpleNamespace(
            title="后端开发",
            company="A公司",
            location="北京",
            salary="20k",
            job_type="社招",
            description="负责后端服务开发",
            requirements="熟悉 Python；本科及以上学历",
            additional_info="",
        )
    )


_PROFILE_TEXT = json.dumps({"name": "张三", "education": "本科", "skills": ["Python"]}, ensure_ascii=False)
_RESUME_TEXT = json.dumps({"title": "后端版", "content": {"skills": "Python 后端"}}, ensure_ascii=False)


def _valid_result(**overrides) -> dict:
    data = {
        "hard_conditions": [
            {
                "label": "本科及以上",
                "jd_quote": "本科及以上学历",
                "status": "matched",
                "evidence": "本科",
            }
        ],
        "core_abilities": [
            {
                "label": "熟悉 Python",
                "jd_quote": "熟悉 Python",
                "status": "expression_gap",
                "evidence": "Python",
            }
        ],
        "bonus_items": [
            {
                "label": "有开源经历",
                "jd_quote": "",
                "status": "evidence_insufficient",
                "evidence": "资料中未提供",
            }
        ],
        "hard_gate": "met",
        "admission": "allow",
        "advice": "建议投递，使用「后端版」简历。",
        "notes": ["团队成果不计入个人能力"],
    }
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_analyze_match_returns_five_status_taxonomy_and_recomputes_admission():
    provider = ScriptedProvider(json.dumps(_valid_result(), ensure_ascii=False))

    result = await analyze_match(provider, _payload(), _PROFILE_TEXT, _RESUME_TEXT)

    statuses = {
        result.hard_conditions[0].status,
        result.core_abilities[0].status,
        result.bonus_items[0].status,
    }
    assert statuses == {"matched", "expression_gap", "evidence_insufficient"}
    # admission_of 是唯一权威：含"证据不足"→需确认，覆盖模型自报的 allow。
    assert result.hard_gate == "met"
    assert result.admission == "needs_confirm"
    assert provider.messages is not None
    assert [m["role"] for m in provider.messages] == ["system", "user"]
    assert "<MATCH_DATA>" in provider.messages[1]["content"]


@pytest.mark.asyncio
async def test_analyze_match_rejects_a_percentage_score_field():
    payload = _valid_result()
    payload["score"] = 82  # 禁伪精确：任何数值评分字段都必须被拒

    with pytest.raises(LLMError):
        await analyze_match(
            ScriptedProvider(json.dumps(payload, ensure_ascii=False)),
            _payload(),
            _PROFILE_TEXT,
            _RESUME_TEXT,
        )


@pytest.mark.asyncio
async def test_analyze_match_rejects_unverifiable_evidence():
    payload = _valid_result()
    payload["core_abilities"][0]["evidence"] = "精通 Kubernetes 与微服务治理"

    with pytest.raises(LLMError):
        await analyze_match(
            ScriptedProvider(json.dumps(payload, ensure_ascii=False)),
            _payload(),
            _PROFILE_TEXT,
            _RESUME_TEXT,
        )


def test_finalize_marks_hard_gate_unmet_and_blocks_on_real_gap():
    result = parse_match_result(
        json.dumps(
            _valid_result(
                hard_conditions=[
                    {
                        "label": "硕士及以上",
                        "jd_quote": "本科及以上学历",
                        "status": "real_gap",
                        "evidence": "资料中未提供",
                    }
                ]
            ),
            ensure_ascii=False,
        )
    )

    finalized = finalize_match_result(result)

    assert finalized.hard_gate == "unmet"
    assert finalized.admission == "block"


def test_local_match_result_is_honest_and_never_fabricates():
    result = local_match_result(_payload())

    assert result.notes and "未配置大模型" in result.notes[0]
    assert result.hard_conditions and all(
        condition.status == "to_confirm" for condition in result.hard_conditions
    )
    # 本地降级一律"需确认"，不给出任何匹配结论式的放行。
    assert result.admission == "needs_confirm"


def test_result_model_forbids_numeric_fields():
    with pytest.raises(LLMError):
        parse_match_result(json.dumps({"hard_conditions": [], "match_percent": 88}, ensure_ascii=False))


@pytest.mark.asyncio
async def test_generate_greeting_strips_fences_and_caps_length():
    provider = ScriptedProvider("```\n您好，我有 Python 后端经验，期待沟通。\n```")

    greeting = await generate_greeting(provider, _payload(), _RESUME_TEXT)

    assert greeting == "您好，我有 Python 后端经验，期待沟通。"


def test_parse_greeting_caps_at_record_limit():
    from app.schemas.apply import GREETING_RECORD_MAX_CHARS

    parsed = parse_greeting("好" * (GREETING_RECORD_MAX_CHARS + 500))

    assert len(parsed) == GREETING_RECORD_MAX_CHARS


def test_build_match_messages_declares_untrusted_boundary():
    messages = build_match_messages(_payload(), _PROFILE_TEXT, _RESUME_TEXT)

    assert messages[0]["role"] == "system"
    assert "不可信数据" in messages[1]["content"]
