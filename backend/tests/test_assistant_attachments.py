"""求职助手附件校验、持久化和模型消息转换测试。"""

import base64

import pytest

from app.schemas.assistant import AssistantAttachmentInput
from app.services.assistant_service import normalize_attachments
from tests.test_assistant import _configure_llm, _create_conversation, _successful_provider
from tests.test_document_text import DOCX_MIME, PDF_MIME, build_docx, build_pdf, data_url


def test_text_and_image_attachments_are_validated_stored_and_sent(client, monkeypatch):
    _configure_llm(client)
    captured: dict = {}
    _successful_provider(monkeypatch, captured)
    conversation = _create_conversation(client)
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"test-image"
    image_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode()

    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={
            "content": "结合附件给建议",
            "attachments": [
                {"name": "project.md", "mime_type": "text/markdown", "data": "项目事实：完成调研"},
                {"name": "screenshot.png", "mime_type": "image/png", "data": image_url},
            ],
        },
    )
    assert response.status_code == 200
    model_content = captured["messages"][-1]["content"]
    assert isinstance(model_content, list)
    assert "项目事实：完成调研" in model_content[0]["text"]
    assert model_content[1] == {"type": "image_url", "image_url": {"url": image_url}}

    attachments = client.get(f"/api/assistant/conversations/{conversation['id']}").json()[
        "messages"
    ][0]["attachments"]
    assert attachments[0]["text"] == "项目事实：完成调研"
    assert attachments[1]["data_url"] == image_url
    assert attachments[1]["size_bytes"] == len(image_bytes)


@pytest.mark.parametrize(
    "attachment",
    [
        {"name": "document.pdf", "mime_type": "application/pdf", "data": "not-pdf"},
        {
            "name": "fake.png",
            "mime_type": "image/png",
            "data": "data:image/png;base64," + base64.b64encode(b"not-a-png").decode(),
        },
        {
            "name": "wrong.jpg",
            "mime_type": "image/jpeg",
            "data": "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode(),
        },
    ],
)
def test_unsupported_or_forged_attachment_returns_422(client, attachment):
    _configure_llm(client)
    conversation = _create_conversation(client)
    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "分析附件", "attachments": [attachment]},
    )
    assert response.status_code == 422


def test_attachment_count_and_size_limits(client):
    _configure_llm(client)
    conversation = _create_conversation(client)
    five_files = [
        {"name": f"{index}.txt", "mime_type": "text/plain", "data": "x"} for index in range(5)
    ]
    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "分析附件", "attachments": five_files},
    )
    assert response.status_code == 422

    oversized = "x" * (2 * 1024 * 1024 + 1)
    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={
            "content": "分析附件",
            "attachments": [{"name": "large.txt", "mime_type": "text/plain", "data": oversized}],
        },
    )
    assert response.status_code == 422
    assert "2 MB" in response.json()["detail"]

    items = [
        AssistantAttachmentInput(name=f"{index}.txt", mime_type="text/plain", data="x" * 1_800_000)
        for index in range(3)
    ]
    with pytest.raises(ValueError, match="总大小不能超过 5 MB"):
        normalize_attachments(items)


def test_document_attachment_is_extracted_locally_and_sent_as_text(client, monkeypatch):
    """文档在本机提取成文字后再进模型：不需要多模态，原始文件也不会外发。"""
    _configure_llm(client)
    captured: dict = {}
    _successful_provider(monkeypatch, captured)
    conversation = _create_conversation(client)
    raw = build_docx("项目事实：完成调研", "技术栈：Python、FastAPI")

    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={
            "content": "这份简历写得怎么样",
            "attachments": [
                {"name": "resume.docx", "mime_type": DOCX_MIME, "data": data_url(raw, DOCX_MIME)}
            ],
        },
    )

    assert response.status_code == 200
    model_content = captured["messages"][-1]["content"]
    assert isinstance(model_content, str)
    assert "项目事实：完成调研" in model_content
    assert "技术栈：Python、FastAPI" in model_content

    attachments = client.get(f"/api/assistant/conversations/{conversation['id']}").json()[
        "messages"
    ][0]["attachments"]
    assert attachments[0]["kind"] == "document"
    assert attachments[0]["mime_type"] == DOCX_MIME
    assert attachments[0]["data_url"] == ""
    assert attachments[0]["size_bytes"] == len(raw)
    assert "项目事实：完成调研" in attachments[0]["text"]


def test_pdf_attachment_text_reaches_the_model(client, monkeypatch):
    _configure_llm(client)
    captured: dict = {}
    _successful_provider(monkeypatch, captured)
    conversation = _create_conversation(client)
    raw = build_pdf("ResumeForge PDF Resume")

    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={
            "content": "帮我看看这份 PDF",
            "attachments": [
                {"name": "resume.pdf", "mime_type": PDF_MIME, "data": data_url(raw, PDF_MIME)}
            ],
        },
    )

    assert response.status_code == 200
    assert "ResumeForge PDF Resume" in captured["messages"][-1]["content"]


def test_mislabeled_but_real_image_is_accepted_by_its_real_format(client, monkeypatch):
    """文件名说 .jpeg、内容其实是 PNG：按内容处理，而不是逼用户改名。"""
    _configure_llm(client)
    captured: dict = {}
    _successful_provider(monkeypatch, captured)
    conversation = _create_conversation(client)
    png = b"\x89PNG\r\n\x1a\n" + b"real-png-body"

    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={
            "content": "看看这张参考图",
            "attachments": [
                {
                    "name": "参考图.jpeg",
                    "mime_type": "image/jpeg",
                    "data": data_url(png, "image/jpeg"),
                }
            ],
        },
    )

    assert response.status_code == 200
    # 发给模型的是真实格式，不是扩展名
    parts = captured["messages"][-1]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")

    attachments = client.get(f"/api/assistant/conversations/{conversation['id']}").json()[
        "messages"
    ][0]["attachments"]
    assert attachments[0]["mime_type"] == "image/png"
    assert attachments[0]["notes"] == ["文件实际是 PNG，已按真实格式处理。"]


def test_scanned_or_broken_document_returns_422_with_guidance(client):
    _configure_llm(client)
    conversation = _create_conversation(client)
    empty_pdf = build_pdf(blank=True)

    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={
            "content": "看看这份文件",
            "attachments": [
                {
                    "name": "scan.pdf",
                    "mime_type": PDF_MIME,
                    "data": data_url(empty_pdf, PDF_MIME),
                }
            ],
        },
    )

    assert response.status_code == 422
    assert "截图" in response.json()["detail"]
