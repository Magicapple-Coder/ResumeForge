"""图片识别的离线单元测试：锚点、防虚构与失败形态。"""

import base64
import json

import pytest

from app.schemas.extraction import MAX_RECOGNIZED_TEXT_CHARS
from app.schemas.setting import LLMConfig
from app.services.attachments import normalize_extraction_images
from app.services.job_text_parser import parse_job_text
from app.services.llm.base import BaseLLMProvider, LLMError
from app.services.profile_text_parser import parse_profile_text
from app.services.text_extraction import (
    MAX_EXTRACTION_RESPONSE_CHARS,
    ai_failed_warning,
    attach_image_review_warning,
    extract_job_text,
    extract_profile_text,
    no_model_warning,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64
PNG_URL = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")

SCREENSHOT_TEXT = """北京-全栈开发工程师 百度
北京市校招技术岗位
工作职责：负责前端和服务端开发，参与 AI 工具建设。
职责要求：本科及以上学历，熟练使用 Python、TypeScript。"""


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


def job_response(**overrides) -> str:
    payload = {
        "transcription": SCREENSHOT_TEXT,
        "title": "全栈开发工程师",
        "company": "百度",
        "location": "北京市",
        "salary": "",
        "job_type": "校招",
        "description": "负责前端和服务端开发，参与 AI 工具建设。",
        "requirements": "本科及以上学历，熟练使用 Python、TypeScript。",
        "additional_info": "",
        "source_url": "",
        "posted_at": "",
        "status": "开放中",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def empty_local_job():
    return parse_job_text("")


def test_messages_keep_plain_string_content_without_images():
    """没有图片时必须保持字符串 content——模型与既有断言都依赖这个形状。"""
    from app.services.text_extraction import build_job_extraction_messages

    messages = build_job_extraction_messages("招聘文本", parse_job_text("招聘文本"))

    assert isinstance(messages[1]["content"], str)
    assert "不可信资料" in messages[1]["content"]


def test_messages_add_image_parts_and_the_addendum():
    from app.services.text_extraction import build_job_extraction_messages

    messages = build_job_extraction_messages("", empty_local_job(), [PNG_URL, PNG_URL])

    parts = messages[1]["content"]
    assert isinstance(parts, list)
    assert parts[0]["type"] == "text" and "不可信资料" in parts[0]["text"]
    assert [part["type"] for part in parts[1:]] == ["image_url", "image_url"]
    assert parts[1]["image_url"]["url"] == PNG_URL
    # 图片模式必须带上抄录要求，否则锚点无从谈起
    assert "transcription" in messages[0]["content"]


@pytest.mark.asyncio
async def test_extract_job_text_grounds_fields_in_the_transcription():
    provider = FakeProvider(job_response())

    result = await extract_job_text(provider, "", empty_local_job(), [PNG_URL])

    assert result.recognition_source == "ai"
    assert result.title == "全栈开发工程师"
    assert result.company == "百度"
    assert "前端和服务端" in result.description
    assert result.recognized_text.startswith("北京-全栈开发工程师")


@pytest.mark.asyncio
async def test_extract_job_text_drops_fields_absent_from_the_transcription():
    """本次改动最关键的保证：模型编不进抄录里的事实，仍然进不了字段。"""
    provider = FakeProvider(
        job_response(title="全栈开发工程师", salary="30-50K", company="腾讯")
    )

    result = await extract_job_text(provider, "", empty_local_job(), [PNG_URL])

    assert result.title == "全栈开发工程师"  # 抄录里有
    assert result.company == ""  # 抄录里是百度，腾讯是无据的
    assert result.salary == ""  # 抄录里根本没有薪资


@pytest.mark.asyncio
async def test_extract_job_text_rejects_a_missing_transcription_when_images_are_sent():
    """同时给了文本和图片时，没抄录图片也不能算成功。

    否则粘贴文本里合法锚定的字段会全部活下来、结果被标成"AI 识别成功"，而图片
    一个字段都没贡献——这是最隐蔽的一种假成功。
    """
    provider = FakeProvider(job_response(transcription=""))
    local = parse_job_text("百度招聘全栈开发工程师，北京市。")

    with pytest.raises(LLMError, match="未抄录图片"):
        await extract_job_text(provider, "百度招聘全栈开发工程师，北京市。", local, [PNG_URL])


@pytest.mark.asyncio
async def test_extract_job_text_anchors_on_pasted_text_and_transcription_together():
    """文本与图片同时给：两边都算来源，不能因为加了图反而丢掉文本的字段。"""
    pasted = "补充：公司提供免费三餐。"
    provider = FakeProvider(
        job_response(transcription=SCREENSHOT_TEXT, additional_info="公司提供免费三餐。")
    )

    result = await extract_job_text(provider, pasted, parse_job_text(pasted), [PNG_URL])

    assert "免费三餐" in result.additional_info
    assert result.title == "全栈开发工程师"  # 来自抄录


@pytest.mark.asyncio
async def test_extract_job_text_ignores_a_stray_transcription_without_images():
    """纯文本请求即使被塞了 transcription 也不该改变行为。"""
    provider = FakeProvider(job_response(transcription="完全无关的内容"))
    source = "百度招聘全栈开发工程师，北京市。"

    result = await extract_job_text(provider, source, parse_job_text(source))

    assert result.title == "全栈开发工程师"
    # 展示字段不该把无关内容带给用户
    assert result.recognized_text == ""


@pytest.mark.asyncio
async def test_extract_profile_text_grounds_entries_in_the_transcription():
    transcription = "张三\n13800000000\n教育经历：示例大学 软件工程 本科 2022-09 至 2026-06"
    provider = FakeProvider(
        json.dumps(
            {
                "transcription": transcription,
                "name": "张三",
                "phone": "13800000000",
                "educations": [
                    {"school": "示例大学", "major": "软件工程", "degree": "本科"},
                    {"school": "不存在的大学", "major": "神秘学"},
                ],
            },
            ensure_ascii=False,
        )
    )

    result = await extract_profile_text(provider, "", parse_profile_text(""), [PNG_URL])

    assert result.name == "张三"
    assert [item.school for item in result.educations] == ["示例大学"]
    assert "示例大学" in result.recognized_text


@pytest.mark.asyncio
async def test_recognized_text_is_truncated_without_a_truncation_warning():
    # 抄录要长过展示上限、但又短过整个响应的解析上限，否则测试会因为别的原因失败
    long_transcription = SCREENSHOT_TEXT + "补充说明。" * 5_000
    assert MAX_RECOGNIZED_TEXT_CHARS < len(long_transcription) < MAX_EXTRACTION_RESPONSE_CHARS
    provider = FakeProvider(job_response(transcription=long_transcription))

    result = await extract_job_text(provider, "", empty_local_job(), [PNG_URL])

    assert len(result.recognized_text) == MAX_RECOGNIZED_TEXT_CHARS
    # 展示用的辅助信息被截断，不该冒充"字段被截断"
    assert not any("截断" in warning for warning in result.warnings)


def _image_stub(name="a.png", raw=PNG_BYTES, mime="image/png"):
    from types import SimpleNamespace

    return SimpleNamespace(
        name=name,
        mime_type=mime,
        data="data:image/png;base64," + base64.b64encode(raw).decode("ascii"),
    )


def _png_of(size: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"0" * (size - 8)


def test_normalize_extraction_images_rejects_text_attachments_and_oversized_total():
    with pytest.raises(ValueError, match="仅支持"):
        normalize_extraction_images([_image_stub(name="笔记.txt", mime="text/plain")])

    with pytest.raises(ValueError, match="不能超过 2 MB"):
        normalize_extraction_images([_image_stub(raw=_png_of(2 * 1024 * 1024 + 1))])

    # 单张都合法，但合计超限：这是请求体不超 8 MB 的保证所在
    two_mb = _image_stub(raw=_png_of(2 * 1024 * 1024))
    with pytest.raises(ValueError, match="总大小不能超过 5 MB"):
        normalize_extraction_images([two_mb, two_mb, two_mb])


def test_image_warnings_say_what_the_user_can_do():
    # 没配模型：本地规则读不了图片，必须说清楚，否则用户看到的是"识别成功但表单是空的"
    assert "图片识别无法进行" in no_model_warning(has_images=True)
    # 配了模型但调用失败：最可能的原因就是模型不支持图片，给出可行动的提示
    assert "多模态" in ai_failed_warning(has_images=True)
    assert "多模态" in ai_failed_warning(has_images=True, detail="HTTP 400")
    # 纯文本的两条文案必须逐字不变，既有断言依赖它们
    assert no_model_warning(has_images=False) == "未配置大模型，已使用本地规则识别，请核对后保存。"
    assert ai_failed_warning(has_images=False) == "AI 识别暂不可用，已使用本地规则识别，请核对后保存。"


@pytest.mark.asyncio
async def test_image_results_carry_a_review_warning():
    provider = FakeProvider(job_response())

    result = await extract_job_text(provider, "", empty_local_job(), [PNG_URL])
    with_warning = attach_image_review_warning(result, has_images=True)

    assert any("对照截图核对" in warning for warning in with_warning.warnings)
    # 纯文本不加这条
    assert attach_image_review_warning(result, has_images=False).warnings == result.warnings
