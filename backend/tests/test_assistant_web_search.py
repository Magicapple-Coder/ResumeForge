"""求职助手联网搜索引用和降级行为测试。"""

from app.services.assistant_web_search import AssistantSearchError
from tests.test_assistant import (
    _configure_llm,
    _create_conversation,
    _events,
    _successful_provider,
)


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
    assert "不得将结果称为刚发布或最新招聘" in captured["messages"][-1]["content"]
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
