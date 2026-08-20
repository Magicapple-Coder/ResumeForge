"""AI 求职助手会话、附件、上下文与联网搜索的离线测试。"""

import base64
import json

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database_migrations import build_alembic_config
from app.api.assistant import send_message
from app.models.assistant import ChatConversation, ChatMessage
from app.schemas.assistant import AssistantAttachmentInput, AssistantMessageCreate
from app.schemas.setting import LLMConfig
from app.services.assistant_service import normalize_attachments
from app.services.assistant_web_search import (
    BING_SEARCH_URL,
    AssistantSearchError,
    parse_bing_rss,
    search_web,
)
from app.services.llm.base import LLMError


def _configure_llm(client) -> None:
    config = LLMConfig(
        base_url="https://api.example.com/v1",
        api_key="assistant-secret",
        model="assistant-model",
    )
    response = client.put("/api/settings/llm", json=config.model_dump())
    assert response.status_code == 200


def _create_conversation(client, title: str = "") -> dict:
    response = client.post("/api/assistant/conversations", json={"title": title})
    assert response.status_code == 201
    return response.json()


def _events(response) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _successful_provider(monkeypatch, captured: dict | None = None, reply: str = "建议内容"):
    class Provider:
        async def stream_chat(self, messages):
            if captured is not None:
                captured["messages"] = messages
            yield reply[:2]
            yield reply[2:]

    monkeypatch.setattr("app.api.assistant.create_provider", lambda _config: Provider())


def test_conversation_crud_and_cascade_delete(client, db_session, monkeypatch):
    _configure_llm(client)
    _successful_provider(monkeypatch)
    conversation = _create_conversation(client)

    listed = client.get("/api/assistant/conversations")
    assert listed.status_code == 200
    assert listed.json()[0]["title"] == "新对话"

    renamed = client.patch(
        f"/api/assistant/conversations/{conversation['id']}", json={"title": "  面试 准备  "}
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "面试 准备"

    sent = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "帮我准备面试"},
    )
    assert [event["type"] for event in _events(sent)] == ["start", "delta", "delta", "done"]

    detail = client.get(f"/api/assistant/conversations/{conversation['id']}").json()
    assert [item["role"] for item in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["content"] == "建议内容"

    deleted = client.delete(f"/api/assistant/conversations/{conversation['id']}")
    assert deleted.status_code == 204
    db_session.expire_all()
    assert db_session.query(ChatConversation).count() == 0
    assert db_session.query(ChatMessage).count() == 0
    assert client.get(f"/api/assistant/conversations/{conversation['id']}").status_code == 404


def test_first_message_generates_truncated_local_title(client, monkeypatch):
    _configure_llm(client)
    _successful_provider(monkeypatch)
    conversation = _create_conversation(client)
    question = "请帮我分析这个岗位是否适合我的经历并给出具体改进建议" * 3

    events = _events(
        client.post(
            f"/api/assistant/conversations/{conversation['id']}/messages",
            json={"content": question},
        )
    )
    title = events[0]["conversation_title"]
    assert title.endswith("…")
    assert len(title) == 37
    assert client.get(f"/api/assistant/conversations/{conversation['id']}").json()["title"] == title


def test_selected_context_is_read_only_bounded_and_excludes_profile_identity(client, monkeypatch):
    _configure_llm(client)
    job = client.post(
        "/api/jobs",
        json={
            "title": "数据分析师",
            "company": "示例企业",
            "requirements": "熟悉 SQL 和业务分析",
        },
    ).json()
    profile = client.put(
        "/api/profile",
        json={
            "name": "不应发送的姓名",
            "phone": "13800000000",
            "projects": [{"name": "销售分析项目", "description": "分析区域销售趋势"}],
        },
    )
    assert profile.status_code == 200
    resume = client.post(
        "/api/resumes/manual",
        json={
            "job_id": job["id"],
            "title": "数据岗简历",
            "content": {"name": "简历姓名", "summary": "掌握数据分析"},
        },
    ).json()
    captured: dict = {}
    _successful_provider(monkeypatch, captured)
    conversation = _create_conversation(client)

    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={
            "content": "我应该重点准备什么？",
            "job_id": job["id"],
            "resume_id": resume["id"],
            "include_profile": True,
        },
    )
    assert response.status_code == 200
    prompt = captured["messages"][-1]["content"]
    assert "数据分析师" in prompt
    assert "数据岗简历" in prompt
    assert "销售分析项目" in prompt
    assert "不应发送的姓名" not in prompt
    assert "13800000000" not in prompt

    detail = client.get(f"/api/assistant/conversations/{conversation['id']}").json()
    context = detail["messages"][0]["context"]
    assert context["job_id"] == job["id"]
    assert context["resume_id"] == resume["id"]
    assert context["include_profile"] is True
    assert client.get(f"/api/jobs/{job['id']}").json()["title"] == "数据分析师"


@pytest.mark.parametrize(
    ("request_body", "message"),
    [
        ({"content": "问题", "job_id": 999}, "岗位不存在"),
        ({"content": "问题", "resume_id": 999}, "简历不存在"),
    ],
)
def test_missing_selected_context_returns_404(client, request_body, message):
    _configure_llm(client)
    conversation = _create_conversation(client)
    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages", json=request_body
    )
    assert response.status_code == 404
    assert message in response.json()["detail"]


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


def test_model_failure_emits_error_and_persists_failed_message(client, monkeypatch):
    _configure_llm(client)

    class FailingProvider:
        async def stream_chat(self, _messages):
            raise LLMError("模型服务暂时不可用")
            yield ""  # pragma: no cover

    monkeypatch.setattr("app.api.assistant.create_provider", lambda _config: FailingProvider())
    conversation = _create_conversation(client)
    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "帮我分析"},
    )
    events = _events(response)
    assert events[-1] == {"type": "error", "message": "模型服务暂时不可用"}
    assistant = client.get(f"/api/assistant/conversations/{conversation['id']}").json()["messages"][
        1
    ]
    assert assistant["status"] == "error"
    assert assistant["error"] == "模型服务暂时不可用"


@pytest.mark.asyncio
async def test_closing_stream_after_start_marks_pending_message_cancelled(client, monkeypatch):
    _configure_llm(client)
    _successful_provider(monkeypatch)
    conversation = _create_conversation(client)

    from app.database import SessionLocal

    db = SessionLocal()
    response = await send_message(
        conversation["id"],
        AssistantMessageCreate(content="帮我分析岗位"),
        db,
    )
    stream = response.body_iterator
    first_event = await anext(stream)
    assert '"type": "start"' in first_event
    await stream.aclose()

    assistant = client.get(f"/api/assistant/conversations/{conversation['id']}").json()[
        "messages"
    ][1]
    assert assistant["status"] == "cancelled"
    assert assistant["error"] == "回复已中断"


def test_web_search_results_are_cited_context_and_search_does_not_create_jobs(client, monkeypatch):
    _configure_llm(client)
    captured: dict = {}
    _successful_provider(monkeypatch, captured, "可参考来源。")

    async def fake_search(query: str):
        assert query == "寻找数据分析师校招"
        return [
            {
                "title": "示例企业招聘官网",
                "url": "https://careers.example.com/jobs/1",
                "snippet": "数据分析师校园招聘",
            }
        ]

    monkeypatch.setattr("app.api.assistant.search_web", fake_search)
    conversation = _create_conversation(client)
    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "寻找数据分析师校招", "web_search": True},
    )
    events = _events(response)
    sources_event = next(event for event in events if event["type"] == "sources")
    assert sources_event["sources"][0]["url"] == "https://careers.example.com/jobs/1"
    assert "[来源1]" in captured["messages"][-1]["content"]
    assert client.get("/api/jobs").json()["total"] == 0

    context = client.get(f"/api/assistant/conversations/{conversation['id']}").json()["messages"][
        0
    ]["context"]
    assert context["sources"] == sources_event["sources"]


def test_web_search_failure_degrades_without_claiming_sources(client, monkeypatch):
    _configure_llm(client)
    captured: dict = {}
    _successful_provider(monkeypatch, captured)

    async def unavailable(_query: str):
        raise AssistantSearchError("联网搜索响应超时，请稍后重试")

    monkeypatch.setattr("app.api.assistant.search_web", unavailable)
    conversation = _create_conversation(client)
    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "搜索岗位", "web_search": True},
    )
    sources_event = next(event for event in _events(response) if event["type"] == "sources")
    assert sources_event["sources"] == []
    assert "响应超时" in sources_event["error"]
    assert "请勿声称已获得联网资料" in captured["messages"][-1]["content"]


def test_parse_bing_rss_limits_and_sanitizes_results():
    assert BING_SEARCH_URL == "https://cn.bing.com/search"
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <rss><channel>
      <item><title>Official &amp; Careers</title><link>https://example.com/jobs</link>
      <description><![CDATA[<b>Campus hiring</b> now]]></description></item>
      <item><title>Unsafe</title><link>javascript:alert(1)</link><description>x</description></item>
    </channel></rss>"""
    assert parse_bing_rss(xml) == [
        {
            "title": "Official & Careers",
            "url": "https://example.com/jobs",
            "snippet": "Campus hiring now",
        }
    ]

    with pytest.raises(AssistantSearchError, match="不安全"):
        parse_bing_rss(b"<!DOCTYPE rss [<!ENTITY x 'boom'>]><rss>&x;</rss>")


@pytest.mark.asyncio
async def test_search_web_uses_fetch_function_without_network(monkeypatch):
    xml = b"<rss><channel><item><title>Result</title><link>https://example.com</link></item></channel></rss>"
    captured = {}

    async def fake_fetch(query: str):
        captured["query"] = query
        return xml

    monkeypatch.setattr("app.services.assistant_web_search.fetch_bing_rss", fake_fetch)
    results = await search_web("  Python   jobs  ")
    assert captured["query"] == "Python jobs"
    assert results[0]["title"] == "Result"


def test_chat_migration_builds_history_tables_and_cascades(tmp_path):
    migration_engine = create_engine(f"sqlite:///{tmp_path / 'assistant-migration.db'}")
    config = build_alembic_config(migration_engine)
    try:
        command.upgrade(config, "head")
        inspector = inspect(migration_engine)
        assert {"chat_conversation", "chat_message"} <= set(inspector.get_table_names())
        assert {"title", "created_at", "updated_at"} <= {
            item["name"] for item in inspector.get_columns("chat_conversation")
        }
        assert {"attachments", "context", "status", "error", "model"} <= {
            item["name"] for item in inspector.get_columns("chat_message")
        }
        with migration_engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0005_chat_assistant"
            )

        with Session(migration_engine) as session:
            conversation = ChatConversation(title="迁移测试")
            conversation.messages.append(
                ChatMessage(role="user", content="测试", status="complete")
            )
            session.add(conversation)
            session.commit()
            conversation_id = conversation.id

        with migration_engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
            connection.execute(
                text("DELETE FROM chat_conversation WHERE id = :id"), {"id": conversation_id}
            )
            connection.commit()
            assert connection.execute(text("SELECT COUNT(*) FROM chat_message")).scalar_one() == 0

        command.upgrade(config, "head")
    finally:
        migration_engine.dispose()
