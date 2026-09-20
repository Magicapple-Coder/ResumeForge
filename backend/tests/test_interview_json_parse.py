"""R-11 参考答案/题库 JSON 解析的容错与重试（根因修复）。

覆盖三类真实会发生的脏输出：

1. 带 Markdown 代码围栏（```json ... ```）；
2. JSON 前后夹着解释文字（前缀/后缀）；
3. 纯文本坏返回（没有 JSON）——应当报错且错误信息附原始返回摘要。

另外验证 `_chat_json` 的"失败自动重试一次"：第一次脏、第二次好，应当成功。
"""
import json

import pytest

from app.services.interview_questions import generate_question_answer, generate_question_bank
from app.services.llm.base import LLMError
from app.services.llm.structured_output import parse_json_object

_ANSWER_PAYLOAD = {
    "answer": "我会先介绍在交易系统里负责的撮合引擎。",
    "key_points": ["先亮结论", "拆到个人贡献"],
    "sample_phrasing": "以我在 X 项目为例……",
}

_BANK_PAYLOAD = {
    "基础题": [{"question": "请自我介绍", "purpose": "考察表达", "answer_hint": "STAR"}],
    "项目深挖题": [{"question": "交易系统难点", "purpose": "考察取舍", "answer_hint": "边界"}],
    "反问HR题": [{"question": "团队如何协作", "purpose": "了解团队", "answer_hint": "成长"}],
}


class _FakeProvider:
    """假 provider：``replies`` 按顺序返回，可模拟"第一次脏、第二次好"的重试。"""

    def __init__(self, replies) -> None:
        self._replies = list(replies) if isinstance(replies, (list, tuple)) else [replies]
        self.calls = 0

    async def chat(self, _messages):
        self.calls += 1
        return self._replies[min(self.calls, len(self._replies)) - 1]


def _fenced(text: dict) -> str:
    return "```json\n" + json.dumps(text, ensure_ascii=False) + "\n```"


def _wrapped(text: dict, prefix: str = "好的，以下是结果：\n", suffix: str = "\n希望对你有帮助。") -> str:
    return prefix + json.dumps(text, ensure_ascii=False) + suffix


# ===== 直接测 parse_json_object =====


def test_parse_strips_code_fence():
    value = parse_json_object(_fenced(_ANSWER_PAYLOAD), label="参考答案")
    assert value["answer"].startswith("我会先介绍")


def test_parse_extracts_balanced_object_with_prefix_suffix():
    value = parse_json_object(_wrapped(_ANSWER_PAYLOAD), label="参考答案")
    assert value["key_points"] == ["先亮结论", "拆到个人贡献"]


def test_parse_handles_trailing_commas():
    dirty = '{"answer": "正文", "key_points": ["a", "b",],}'
    value = parse_json_object(dirty, label="参考答案")
    assert value["key_points"] == ["a", "b"]


def test_parse_ignores_braces_inside_strings():
    text = '{"answer": "包含 { 与 } 的正文", "key_points": []}'
    value = parse_json_object(text, label="参考答案")
    assert "包含 { 与 }" in value["answer"]


def test_parse_bad_text_raises_clean_message():
    # parse_json_object 自身只给干净的提示；原始返回摘要在 _chat_json 重试层附加。
    with pytest.raises(LLMError) as exc:
        parse_json_object("抱歉，我无法生成参考答案。", label="参考答案")
    assert "参考答案" in str(exc.value)
    assert "原始返回" not in str(exc.value)


# ===== 经 _chat_json 重试后，业务函数应能消化脏输出 =====


async def test_generate_question_answer_accepts_fenced_json():
    provider = _FakeProvider(_fenced(_ANSWER_PAYLOAD))
    result = await generate_question_answer(
        provider, question="讲讲项目难点", job_payload="", resume_text=""
    )
    assert result.answer.startswith("我会先介绍")


async def test_generate_question_answer_accepts_prefixed_suffix_json():
    provider = _FakeProvider(_wrapped(_ANSWER_PAYLOAD))
    result = await generate_question_answer(
        provider, question="讲讲项目难点", job_payload="", resume_text=""
    )
    assert result.key_points == ["先亮结论", "拆到个人贡献"]


async def test_generate_question_answer_retries_and_succeeds():
    # 第一次返回没有 JSON 的脏内容，第二次返回合法 JSON —— 应当靠重试成功。
    provider = _FakeProvider(["这不是 JSON，请重试。", _fenced(_ANSWER_PAYLOAD)])
    result = await generate_question_answer(
        provider, question="讲讲项目难点", job_payload="", resume_text=""
    )
    assert provider.calls == 2
    assert result.answer.startswith("我会先介绍")


async def test_generate_question_answer_bad_text_raises_with_snippet():
    bad = "模型开小差了，没返回 JSON。"
    provider = _FakeProvider([bad, bad])
    with pytest.raises(LLMError) as exc:
        await generate_question_answer(
            provider, question="讲讲项目难点", job_payload="", resume_text=""
        )
    assert provider.calls == 2
    assert bad in str(exc.value)


async def test_generate_question_bank_accepts_fenced_json():
    provider = _FakeProvider(_fenced(_BANK_PAYLOAD))
    result = await generate_question_bank(provider, job_text="", resume_json="", claims_json="")
    assert any(group.questions for group in result["groups"])
