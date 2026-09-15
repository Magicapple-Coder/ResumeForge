"""AI 求职助手会话、附件、上下文与联网搜索的离线测试。"""

import json

import pytest

from app.api.assistant import send_message
from app.models.assistant import ChatConversation, ChatMessage
from app.schemas.assistant import AssistantMessageCreate
from app.schemas.setting import LLMConfig
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
    assert listed.json()[0]["pinned"] is False
    assert listed.json()[0]["favorite"] is False

    renamed = client.patch(
        f"/api/assistant/conversations/{conversation['id']}", json={"title": "  面试 准备  "}
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "面试 准备"

    flagged = client.patch(
        f"/api/assistant/conversations/{conversation['id']}",
        json={"pinned": True, "favorite": True},
    )
    assert flagged.status_code == 200
    assert flagged.json()["pinned"] is True
    assert flagged.json()["favorite"] is True

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


def test_conversation_list_places_pinned_items_first_and_supports_partial_flags(client, db_session):
    first = _create_conversation(client, "普通对话")
    second = _create_conversation(client, "重要对话")

    # Make the intended chronological order explicit instead of relying on
    # SQLite timestamp resolution when both conversations are created quickly.
    first_row = db_session.get(ChatConversation, first["id"])
    second_row = db_session.get(ChatConversation, second["id"])
    assert first_row is not None and second_row is not None
    first_row.updated_at = first_row.updated_at.replace(microsecond=1)
    second_row.updated_at = first_row.updated_at.replace(microsecond=0)
    db_session.commit()
    original_second_updated_at = second_row.updated_at

    updated = client.patch(
        f"/api/assistant/conversations/{second['id']}", json={"pinned": True}
    )
    assert updated.status_code == 200
    assert updated.json()["pinned"] is True
    assert updated.json()["favorite"] is False
    db_session.expire_all()
    assert db_session.get(ChatConversation, second["id"]).updated_at == original_second_updated_at

    listed = client.get("/api/assistant/conversations").json()
    assert [item["id"] for item in listed[:2]] == [second["id"], first["id"]]

    unpinned = client.patch(
        f"/api/assistant/conversations/{second['id']}", json={"pinned": False}
    )
    assert unpinned.status_code == 200
    listed_after_unpin = client.get("/api/assistant/conversations").json()
    assert [item["id"] for item in listed_after_unpin[:2]] == [first["id"], second["id"]]

    # The first conversation was newer before the second was pinned, so the
    # original order is restored after unpinning.


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
