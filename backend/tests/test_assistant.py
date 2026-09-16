"""AI 求职助手会话、附件、上下文与联网搜索的离线测试。"""

import io
import json
import zipfile

import pytest

from app.api.assistant import send_message
from app.api.assistant_stream import MAX_TOOL_ROUNDS
from app.models.assistant import ChatConversation, ChatMessage
from app.schemas.assistant import AssistantMessageCreate
from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider, LLMDelta, LLMError


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


def _send(client, conversation_id: int, content: str) -> None:
    response = client.post(
        f"/api/assistant/conversations/{conversation_id}/messages", json={"content": content}
    )
    assert response.status_code == 200


def _events(response) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


class _FakeProvider(BaseLLMProvider):
    """测试用假 Provider。

    继承基类是为了拿到默认的 ``stream_chat_events``（它退化成纯文本流），这样
    只想验证普通对话的用例不必重复实现工具调用那一套。
    """

    def __init__(self, _config=None):  # 假 Provider 不使用配置
        pass

    async def chat(self, _messages):  # pragma: no cover - 助手只走流式
        raise NotImplementedError


def _successful_provider(monkeypatch, captured: dict | None = None, reply: str = "建议内容"):
    class Provider(_FakeProvider):
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

    class FailingProvider(_FakeProvider):
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


class _ScriptedProvider(_FakeProvider):
    """按预设脚本逐轮返回：先给工具调用，再给正文。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.requests = []

    async def stream_chat_events(self, messages, tools=None):
        self.requests.append({"messages": list(messages), "tools": tools})
        index = min(len(self.requests) - 1, len(self.rounds) - 1)
        for delta in self.rounds[index]:
            yield delta

    async def stream_chat(self, messages):
        async for delta in self.stream_chat_events(messages):
            if delta.text:
                yield delta.text


def _tool_call(name, arguments, call_id="call_1"):
    return LLMDelta(
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }
        ],
        finish_reason="tool_calls",
    )


def test_tool_call_runs_and_its_result_reaches_the_model(client, monkeypatch):
    _configure_llm(client)
    provider = _ScriptedProvider(
        [
            [LLMDelta(text="我来查一下。"), _tool_call("list_jobs", {})],
            [LLMDelta(text="你目前有 0 个岗位。")],
        ]
    )
    monkeypatch.setattr("app.api.assistant.create_provider", lambda _config: provider)
    conversation = _create_conversation(client)

    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "我一共有几个岗位？"},
    )

    events = _events(response)
    tool_events = [event for event in events if event["type"] == "tool"]
    assert len(tool_events) == 1
    assert tool_events[0]["name"] == "list_jobs" and tool_events[0]["ok"] is True
    # 工具声明发出去了，结果也作为 role=tool 的消息回给了模型
    assert provider.requests[0]["tools"]
    second_round = provider.requests[1]["messages"]
    assert second_round[-1]["role"] == "tool"
    assert "总数" in second_round[-1]["content"]
    # 记录进消息的 context，历史回看时能看到助手做了什么
    assistant = client.get(f"/api/assistant/conversations/{conversation['id']}").json()["messages"][
        1
    ]
    assert assistant["context"]["tool_calls"][0]["name"] == "list_jobs"


def test_assistant_writes_only_when_asked(client, monkeypatch):
    _configure_llm(client)
    provider = _ScriptedProvider(
        [
            [_tool_call("create_job", {"title": "字节跳动后端实习"})],
            [LLMDelta(text="已经帮你存好了。")],
        ]
    )
    monkeypatch.setattr("app.api.assistant.create_provider", lambda _config: provider)
    conversation = _create_conversation(client)

    client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "帮我把字节跳动的后端实习岗位存进去"},
    )

    assert client.get("/api/jobs").json()["total"] == 1


def test_a_failing_tool_does_not_break_the_reply(client, monkeypatch):
    _configure_llm(client)
    provider = _ScriptedProvider(
        [
            [_tool_call("get_job", {"job_id": 999})],
            [LLMDelta(text="没找到这个岗位。")],
        ]
    )
    monkeypatch.setattr("app.api.assistant.create_provider", lambda _config: provider)
    conversation = _create_conversation(client)

    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "看看 999 号岗位"},
    )

    events = _events(response)
    tool_event = next(event for event in events if event["type"] == "tool")
    assert tool_event["ok"] is False and "不存在" in tool_event["error"]
    # 失败信息作为工具结果回给模型，整轮对话继续而不是中断
    assert "工具执行失败" in provider.requests[1]["messages"][-1]["content"]
    assert any(event["type"] == "delta" for event in events)


def _import_skill(client, name: str, prompt: str, files: dict[str, str] | None = None) -> dict:
    if files is None:
        content = f"---\nname: {name}\n---\n\n{prompt}\n".encode()
        content_type = "text/markdown"
    else:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("SKILL.md", f"---\nname: {name}\n---\n\n{prompt}\n")
            for path, body in files.items():
                archive.writestr(path, body)
        content, content_type = buffer.getvalue(), "application/zip"
    response = client.post(
        "/api/assistant/skills/import", content=content, headers={"Content-Type": content_type}
    )
    assert response.status_code == 200
    return response.json()


def test_enabled_skills_reach_the_system_prompt(client, monkeypatch):
    """技能提示词必须真的进到发给模型的 system 消息里，而不是只躺在库里。"""
    _configure_llm(client)
    provider = _ScriptedProvider([[LLMDelta(text="好。")]])
    monkeypatch.setattr("app.api.assistant.create_provider", lambda _config: provider)
    conversation = _create_conversation(client)
    skill = _import_skill(client, "面试模拟官", "先连问三道八股题，再逐条点评。")
    _send(client, conversation["id"], "我们开始吧")

    system = provider.requests[0]["messages"][0]
    assert system["role"] == "system"
    assert "面试模拟官" in system["content"]
    assert "先连问三道八股题，再逐条点评。" in system["content"]

    # 停用之后下一轮就不再注入：系统提示是每条消息现拼的，改技能不需要重启应用。
    client.patch(f"/api/assistant/skills/{skill['id']}", json={"enabled": False})
    _send(client, conversation["id"], "继续")

    assert "面试模拟官" not in provider.requests[1]["messages"][0]["content"]


def test_knowledge_files_are_listed_but_not_preloaded(client, monkeypatch):
    """知识文件只列清单，正文由模型按需读——否则一个技能包就能塞满上下文。"""
    _configure_llm(client)
    provider = _ScriptedProvider([[LLMDelta(text="好。")]])
    monkeypatch.setattr("app.api.assistant.create_provider", lambda _config: provider)
    conversation = _create_conversation(client)
    _import_skill(client, "面试模拟官", "照题库提问。", files={"题库.md": "压舱石级别的独特句子"})
    _send(client, conversation["id"], "开始")

    system = provider.requests[0]["messages"][0]["content"]
    assert "题库.md" in system
    assert "压舱石级别的独特句子" not in system


def test_tool_rounds_are_capped(client, monkeypatch):
    _configure_llm(client)
    # 每一轮都要求调用工具，永不收敛
    provider = _ScriptedProvider([[_tool_call("get_overview", {})]])
    monkeypatch.setattr("app.api.assistant.create_provider", lambda _config: provider)
    conversation = _create_conversation(client)

    client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "一直查下去"},
    )

    assert len(provider.requests) == MAX_TOOL_ROUNDS
    assistant = client.get(f"/api/assistant/conversations/{conversation['id']}").json()["messages"][
        1
    ]
    assert "先停在这里" in assistant["content"]


def test_web_search_never_exceeds_the_documented_limit(client, monkeypatch):
    """系统提示、README 与使用指南都写着"一次回答最多 3 次"，这里验证它真的是上限。

    此前那句话只活在提示词里：代码侧真正的约束是 5 轮工具调用，而且每轮可以并行发多个
    搜索请求，用户按 3 次的预期可能会多花几倍。
    """
    from app.api.assistant_stream import MAX_WEB_SEARCHES, MAX_TOOL_ROUNDS

    _configure_llm(client)
    executed: list[str] = []

    async def fake_search(query: str) -> list[dict[str, str]]:
        executed.append(query)
        index = len(executed)
        return [{"title": f"招聘 {index}", "url": f"https://example.com/{index}", "snippet": "摘要"}]

    monkeypatch.setattr("app.services.assistant_web_search.search_web", fake_search)
    # 每一轮都要搜索，永不收敛：没有上限就会一直搜到工具轮次用尽。
    provider = _ScriptedProvider([[_tool_call("web_search", {"query": "后端 招聘"})]])
    monkeypatch.setattr("app.api.assistant.create_provider", lambda _config: provider)
    conversation = _create_conversation(client)

    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "帮我搜最新的招聘信息", "web_search": True},
    )

    assert response.status_code == 200
    assert len(executed) == MAX_WEB_SEARCHES
    # 确实是被搜索上限拦下的，而不是因为工具轮次用尽才停。
    assert MAX_WEB_SEARCHES < MAX_TOOL_ROUNDS
