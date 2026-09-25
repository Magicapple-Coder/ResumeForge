"""求职助手联网搜索引用和降级行为测试。"""

from app.services.assistant.assistant_web_search import AssistantSearchError
from app.services.llm.base import LLMDelta
from tests.test_assistant import (
    _configure_llm,
    _create_conversation,
    _events,
    _successful_provider,
    _tool_call,
    _ScriptedProvider,
)


def test_web_search_results_are_cited_context_and_search_does_not_create_jobs(client, monkeypatch):
    _configure_llm(client)
    captured: dict = {}
    _successful_provider(monkeypatch, captured, "可参考来源。")

    # 助手现在走多来源聚合（Bing + DuckDuckGo + 可选 SearXNG），所以替换的是聚合入口：
    # 它的签名多一个搜索设置参数。
    #
    # 这里断言预搜把**用户原话**交给 aggregate_search——这是有意的接口约定：查询改写
    # （build_search_query / 剥口语填充词）集中发生在聚合层，三个来源都在那里统一改写，
    # 免得在预搜处改写后又被聚合层二次改写（build_search_query 对已是关键词列表的输入
    # 并不幂等）。改写行为本身由 test_search_aggregate 里那条用例钉住。
    async def fake_search(query: str, _config):
        assert query == "寻找数据分析师校招"
        return [
            {
                "title": "示例企业招聘官网",
                "url": "https://careers.example.com/jobs/1",
                "snippet": "数据分析师校园招聘",
            }
        ]

    monkeypatch.setattr("app.api.assistant.aggregate_search", fake_search)
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
    # 助手只在被明确要求时才写数据；这轮对话没有让它写入，假 Provider 也没产出
    # 工具调用，所以岗位表应当仍是空的。
    assert client.get("/api/jobs").json()["total"] == 0

    context = client.get(f"/api/assistant/conversations/{conversation['id']}").json()["messages"][
        0
    ]["context"]
    assert context["sources"] == sources_event["sources"]


def test_web_search_failure_degrades_without_claiming_sources(client, monkeypatch):
    _configure_llm(client)
    captured: dict = {}
    _successful_provider(monkeypatch, captured)

    async def unavailable(_query: str, _config):
        raise AssistantSearchError("联网搜索响应超时，请稍后重试")

    monkeypatch.setattr("app.api.assistant.aggregate_search", unavailable)
    conversation = _create_conversation(client)
    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "搜索岗位", "web_search": True},
    )
    sources_event = next(event for event in _events(response) if event["type"] == "sources")
    assert sources_event["sources"] == []
    assert "响应超时" in sources_event["error"]
    assert "请勿声称已获得联网资料" in captured["messages"][-1]["content"]


def test_resume_forge_usage_question_skips_public_search(client, monkeypatch):
    """简历通自身的使用问题应使用本地说明，不被同名网页带偏。"""
    _configure_llm(client)
    captured: dict = {}
    _successful_provider(monkeypatch, captured, "请按本地使用说明操作。")

    async def unexpected_search(_query: str, _config):
        raise AssertionError("ResumeForge 使用问题不应调用公开搜索")

    monkeypatch.setattr("app.api.assistant.aggregate_search", unexpected_search)
    conversation = _create_conversation(client)
    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "简历通怎么在 macOS 上使用？", "web_search": True},
    )

    assert response.status_code == 200
    events = _events(response)
    sources_event = next(event for event in events if event["type"] == "sources")
    assert sources_event["sources"] == []
    assert sources_event["error"] == ""
    assert "已跳过公开搜索" in captured["messages"][-1]["content"]

    message = client.get(f"/api/assistant/conversations/{conversation['id']}").json()["messages"][0]
    assert message["context"]["search_skipped"] == "local_resume_forge_question"


def test_source_numbers_are_globally_unique_across_pre_search_and_tool_search(
    client, monkeypatch
):
    """来源编号在一次回答内全局单调：预搜与工具搜索不各自从 1 重新编号。

    前端要把正文里的 [来源N] 渲染成链接，靠的是"编号 → url"映射；如果预搜占 1、2，
    工具搜索又从 1 开始，模型看到的 [来源1] 就会指到两条不同的 URL，链接必然跳错。
    这条测试走完整链路：预搜命中两条 → 工具再搜一条 → 断言工具结果里那条是 [来源3]，
    且助手消息的 context 里持久化了 1/2/3 三条编号映射。
    """
    _configure_llm(client)
    calls: list[str] = []

    async def fake_search(query: str, _config):
        calls.append(query)
        index = len(calls)
        if index == 1:
            return [
                {"title": "预搜A", "url": "https://example.com/pre-a", "snippet": "摘要A"},
                {"title": "预搜B", "url": "https://example.com/pre-b", "snippet": "摘要B"},
            ]
        return [
            {"title": "工具C", "url": "https://example.com/tool-c", "snippet": "摘要C"},
        ]

    monkeypatch.setattr("app.services.search.aggregate_search", fake_search)
    monkeypatch.setattr("app.api.assistant.aggregate_search", fake_search)
    provider = _ScriptedProvider(
        [
            [_tool_call("web_search", {"query": "后端 招聘"})],
            [LLMDelta(text="见 [来源1] 与 [来源3]。")],
        ]
    )
    monkeypatch.setattr("app.api.assistant.create_provider", lambda _config: provider)
    conversation = _create_conversation(client)

    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages",
        json={"content": "帮我搜最新的招聘信息", "web_search": True},
    )
    assert response.status_code == 200
    # 预搜一次 + 工具一次。
    assert len(calls) == 2

    # 模型看到的上下文里：预搜占 [来源1]/[来源2]，工具搜索是 [来源3]，不重号。
    model_text = "\n".join(
        str(message.get("content", "")) for message in provider.requests[-1]["messages"]
    )
    assert "[来源1]" in model_text
    assert "[来源2]" in model_text
    assert "[来源3]" in model_text
    # 那句"编号只在本次搜索结果内有效"必须删掉——编号现在是全局唯一。
    assert "编号只在本次搜索结果内有效" not in model_text

    messages = client.get(f"/api/assistant/conversations/{conversation['id']}").json()["messages"]
    assistant_message = messages[1]
    assert assistant_message["content"] == "见 [来源1] 与 [来源3]。"
    # 编号 → url 映射持久化在助手消息的 context 里，前端按编号解析链接就靠它。
    assert assistant_message["context"]["source_map"] == [
        {"number": 1, "url": "https://example.com/pre-a"},
        {"number": 2, "url": "https://example.com/pre-b"},
        {"number": 3, "url": "https://example.com/tool-c"},
    ]
    # 去重后的"参考来源"面板仍按 URL 合并展示（这里没有重复 URL，所以是三条）。
    assert len(messages[0]["context"]["sources"]) == 3
