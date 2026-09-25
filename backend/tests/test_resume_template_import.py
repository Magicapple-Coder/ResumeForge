"""从上传的目标模板反推格式模板：参数必须在白名单内，且绝不落一个空模板。

这条链路的失败方式很隐蔽：模型给出范围外的取值（例如 `line_height: 3.5`）会被
`validated_format_config` 静默丢弃——如果全部被丢，最后存进库的就是一个"什么都没有"的
格式模板，界面上看起来"导入成功了"，套上去却一点变化都没有。所以这里把"没有合法取值
就是失败"钉死。
"""

from __future__ import annotations

import base64

import pytest

from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider
from app.services.resume.resume_template_import import (
    MAX_SOURCE_CHARS,
    TemplateImportError,
    TemplateImportSource,
    build_import_messages,
    derive_format_template,
    missing_format_keys,
    source_summary,
)
from app.services.resume.resume_templates import FORMAT_FIELD_KEYS


# 一张 1×1 的合法 PNG：用它验证"按内容判类型"这条路径。
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class ImportProvider(BaseLLMProvider):
    """返回预设 JSON 的假模型，同时记录它收到的消息。"""

    def __init__(self, payload: str):
        super().__init__(LLMConfig(base_url="http://fake", api_key="fake", model="fake-model"))
        self.payload = payload
        self.messages: list[list[dict]] = []

    async def chat(self, messages):
        self.messages.append(messages)
        return self.payload

    async def stream_chat(self, messages):
        yield ""


@pytest.mark.asyncio
async def test_valid_config_is_kept_and_normalized():
    provider = ImportProvider(
        '{"name": "深蓝简洁", "description": "深蓝强调色、大留白", '
        '"config": {"accent": "#1F4E79", "line_height": 1.6, "page_padding": 20}}'
    )
    result = await derive_format_template(
        provider, TemplateImportSource(filename="目标模板.png", image_data_urls=["data:image/png;base64,AA"])
    )

    assert result["name"] == "深蓝简洁"
    assert result["config"]["accent"] == "#1f4e79"  # 归一化成小写
    assert result["config"]["line_height"] == 1.6
    assert missing_format_keys(result["config"]) == [
        key for key in FORMAT_FIELD_KEYS if key not in result["config"]
    ]


@pytest.mark.asyncio
async def test_out_of_range_values_do_not_become_an_empty_template():
    """全部取值都越界时必须报错，而不是存一个空模板。"""
    provider = ImportProvider('{"config": {"line_height": 9.9, "accent": "深蓝色"}}')

    with pytest.raises(TemplateImportError):
        await derive_format_template(provider, TemplateImportSource(filename="x.png"))


@pytest.mark.asyncio
async def test_model_name_falls_back_to_the_filename():
    provider = ImportProvider('{"config": {"line_height": 1.5}}')
    result = await derive_format_template(
        provider, TemplateImportSource(filename="张三的简历模板.pdf")
    )
    assert result["name"] == "张三的简历模板"


def test_image_source_is_sent_as_an_image_message():
    source = TemplateImportSource(
        filename="模板.png", image_data_urls=["data:image/png;base64,AAA"]
    )
    messages = build_import_messages(source)

    user_content = messages[-1]["content"]
    assert isinstance(user_content, list), "带图片时必须是多段内容"
    assert any(part["type"] == "image_url" for part in user_content)
    # 图片版提示词要带上"图片是不可信资料"的补充说明。
    assert "不可信" in messages[0]["content"]


def test_document_source_is_sent_as_text_only():
    source = TemplateImportSource(filename="模板.pdf", text="张三 教育经历 ……")
    messages = build_import_messages(source)

    user_content = messages[-1]["content"]
    assert isinstance(user_content, str), "纯文本时保持字符串形状（与既有识别链路一致）"
    assert "张三" in user_content


def test_source_text_is_clipped():
    source = TemplateImportSource(filename="大.pdf", text="字" * (MAX_SOURCE_CHARS * 2))
    messages = build_import_messages(source)
    assert len(messages[-1]["content"]) < MAX_SOURCE_CHARS * 2


def test_source_summary_says_what_was_analyzed():
    assert "文档文字" in source_summary(TemplateImportSource(filename="a.pdf", text="x"))
    assert "1 张图片" in source_summary(
        TemplateImportSource(filename="a.png", image_data_urls=["data:image/png;base64,AA"])
    )
    assert source_summary(TemplateImportSource(filename="a.txt")) == "空文件"


# ===== 接口层 =====


def test_endpoint_rejects_an_empty_file(client):
    response = client.post(
        "/api/resume-templates/import-from-file",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 422
    assert "空的" in response.json()["detail"]


def test_endpoint_rejects_a_file_whose_content_is_not_an_image(client):
    """扩展名说是图片、内容不是图片：必须按内容判，否则就是把任意文件转给了模型。"""
    response = client.post(
        "/api/resume-templates/import-from-file",
        files={"file": ("fake.png", b"MZ\x90\x00 not really an image", "image/png")},
    )
    assert response.status_code == 422


def test_endpoint_requires_a_model(client, monkeypatch):
    """没配模型时说清楚，而不是给一个"分析失败"的含糊错误。"""
    from app.api import resume_templates as api_module

    monkeypatch.setattr(
        api_module, "get_llm_config", lambda _db: LLMConfig(base_url="", api_key="", model="")
    )
    response = client.post(
        "/api/resume-templates/import-from-file",
        files={"file": ("t.png", TINY_PNG, "image/png")},
    )
    assert response.status_code == 400
    assert "配置大模型" in response.json()["detail"]


def test_endpoint_creates_a_format_template_that_can_be_used(client, db_session, monkeypatch):
    """正常路径：分析结果落成一份格式模板，并且能被列表读出来（生成简历时可选）。"""
    from app.api import resume_templates as api_module

    png = TINY_PNG
    provider = ImportProvider(
        '{"name": "导入的深蓝版式", "description": "按上传图片取样", '
        '"config": {"accent": "#1F4E79", "page_padding": 18}}'
    )
    monkeypatch.setattr(api_module, "get_llm_config", lambda _db: provider.config)
    monkeypatch.setattr(api_module, "create_provider", lambda _config: provider)

    response = client.post(
        "/api/resume-templates/import-from-file",
        files={"file": ("目标.png", png, "image/png")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "导入的深蓝版式"
    assert body["kind"] == "format"
    assert body["source_name"] == "目标.png"

    listed = client.get("/api/resume-templates", params={"kind": "format"}).json()
    assert any(item["id"] == body["id"] for item in listed)


def test_endpoint_accepts_a_pdf_and_uses_its_text(client, db_session, monkeypatch):
    """PDF 走本地抽文字：断言模型收到的是文档文字，而不是被塞了图片。"""
    from app.api import resume_templates as api_module
    from app.services.document_text import ExtractedDocument

    captured: dict[str, object] = {}

    class CapturingProvider(ImportProvider):
        async def chat(self, messages):
            captured["messages"] = messages
            return self.payload

    provider = CapturingProvider('{"name": "文档版式", "config": {"line_height": 1.5}}')
    monkeypatch.setattr(api_module, "get_llm_config", lambda _db: provider.config)
    monkeypatch.setattr(api_module, "create_provider", lambda _config: provider)
    monkeypatch.setattr(
        api_module,
        "extract_document_text",
        lambda name, mime, data: ExtractedDocument(
            name=name or "x.pdf", mime_type=mime, size_bytes=10, text="张三 求职意向 前端开发", warnings=[]
        ),
    )

    response = client.post(
        "/api/resume-templates/import-from-file",
        files={"file": ("目标.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 201, response.text
    messages = captured["messages"]
    assert isinstance(messages[-1]["content"], str)
    assert "张三" in messages[-1]["content"]
