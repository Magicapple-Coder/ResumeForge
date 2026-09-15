"""求职助手附件校验、持久化和模型消息转换测试。"""

import base64

import pytest

from app.schemas.assistant import AssistantAttachmentInput
from app.services.assistant_service import normalize_attachments
from tests.test_assistant import _configure_llm, _create_conversation, _successful_provider


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
