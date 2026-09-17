"""进度识别的解析与本地降级。

模型这条路径用脚本化的假 Provider 钉住解析行为；本地这条路径单独测，因为它最容易
出错——招聘通知的自动回执长得都差不多，关键词匹配稍一宽松就会把「感谢投递」读成
「进入面试」，而用户会照着一个错的「面试中」去准备。
"""
import json

import pytest

from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider, LLMError
from app.services.tracker_extract import (
    build_tracker_messages,
    extract_tracker_records,
    local_tracker_records,
    parse_tracker_records,
)


class ScriptedProvider(BaseLLMProvider):
    def __init__(self, response: str):
        super().__init__(LLMConfig(base_url="http://fake", model="fake-model"))
        self.response = response
        self.messages: list[dict] | None = None

    async def chat(self, messages):
        self.messages = messages
        return self.response

    async def stream_chat(self, messages):  # pragma: no cover - 未用到
        yield ""


# ===== 消息构造 =====


def test_messages_mark_the_material_as_untrusted():
    messages = build_tracker_messages("恭喜您通过筛选，请参加面试。")
    assert "<NOTICE>" in messages[1]["content"]
    assert "不可信数据" in messages[1]["content"]
    # 纯文本时 content 保持字符串，与其它识别链路一致。
    assert isinstance(messages[1]["content"], str)


def test_messages_attach_images_as_content_parts():
    messages = build_tracker_messages("", ["data:image/png;base64,AAA"])
    content = messages[1]["content"]
    assert isinstance(content, list)
    assert content[-1]["type"] == "image_url"
    # 有图片时要带上抄录要求，否则模型会对着没有原文的图直接编字段。
    assert "抄录" in messages[0]["content"]


# ===== 解析 =====


def test_parse_reads_a_clean_response():
    raw = json.dumps(
        {
            "records": [
                {
                    "company": "示例科技",
                    "title": "后端开发实习生",
                    "status": "interview",
                    "stage_note": "一面",
                    "status_date": "2026-09-20",
                    "evidence": "邀请您参加面试",
                }
            ],
            "notes": ["邮件里没写投递日期"],
        },
        ensure_ascii=False,
    )
    records, notes = parse_tracker_records(raw)
    assert len(records) == 1
    assert records[0].status == "interview"
    assert records[0].stage_note == "一面"
    assert notes == ["邮件里没写投递日期"]


def test_parse_accepts_a_markdown_fenced_response():
    body = json.dumps({"records": [{"company": "A", "title": "B", "status": "applied"}]})
    records, _ = parse_tracker_records(f"```json\n{body}\n```")
    assert len(records) == 1


def test_unknown_status_from_the_model_falls_back_to_to_be_confirmed():
    """模型给出没见过的状态时不能猜，落到「待确认」让用户自己判断。"""
    raw = json.dumps(
        {"records": [{"company": "A", "title": "B", "status": "差不多进面试了吧"}]}
    )
    records, _ = parse_tracker_records(raw)
    assert records[0].status == "unknown"


def test_records_without_a_company_or_title_are_dropped():
    """缺公司或岗位的条目并不到任何一条记录上，留着只会让用户困惑。"""
    raw = json.dumps(
        {
            "records": [
                {"company": "", "title": "后端开发", "status": "applied"},
                {"company": "示例科技", "title": "", "status": "applied"},
                {"company": "示例科技", "title": "后端开发", "status": "applied"},
            ]
        }
    )
    records, _ = parse_tracker_records(raw)
    assert len(records) == 1
    assert records[0].company == "示例科技"


def test_parse_rejects_malformed_responses():
    for bad in ("", "不是 JSON", json.dumps({"没有 records": []}), json.dumps(["数组"])):
        with pytest.raises(LLMError):
            parse_tracker_records(bad)


async def test_extract_uses_the_provider_and_returns_records():
    provider = ScriptedProvider(
        json.dumps({"records": [{"company": "A", "title": "B", "status": "offer"}]})
    )
    records, _ = await extract_tracker_records(provider, "恭喜，我们决定录用您。")
    assert records[0].status == "offer"


# ===== 本地降级 =====


def test_local_extraction_needs_company_title_and_signal_together():
    """三个要素缺一个就不产出记录——猜错的进度比没有进度更糟。"""
    records, notes = local_tracker_records("感谢您的投递，我们会尽快处理。")
    assert records == []
    assert any("本地规则" in note for note in notes)


def test_local_extraction_reads_a_formulaic_notice():
    text = (
        "【示例科技有限公司】您好，您投递的「后端开发实习生」岗位已进入面试环节，"
        "请于 2026-09-20 前确认面试时间。"
    )
    records, _ = local_tracker_records(text)
    assert len(records) == 1
    assert records[0].company == "示例科技有限公司"
    assert records[0].title == "后端开发实习生"
    assert records[0].status == "interview"
    assert records[0].status_date == "2026-09-20"


def test_local_extraction_prefers_the_more_decisive_signal():
    """「感谢投递，但很遗憾…」是拒信，不能读成已投递。"""
    text = "【示例科技有限公司】感谢您投递「后端开发实习生」岗位，但很遗憾，本次未能通过筛选。"
    records, _ = local_tracker_records(text)
    assert records[0].status == "rejected"


def test_auto_receipts_never_become_interview_or_offer():
    """自动回执只能落到「已投递」。"""
    text = "【示例网络科技有限公司】您投递的「算法实习生」岗位简历已收到，我们会尽快安排评估。"
    records, _ = local_tracker_records(text)
    assert records[0].status == "applied"


def test_local_extraction_deduplicates_the_same_position():
    text = (
        "【示例科技有限公司】感谢投递「后端开发实习生」。\n\n"
        "【示例科技有限公司】您投递的「后端开发实习生」岗位已进入面试环节。"
    )
    records, _ = local_tracker_records(text)
    assert len(records) == 1
