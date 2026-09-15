"""求职助手联网搜索与聊天迁移的离线测试。"""

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database_migrations import build_alembic_config
from app.models.assistant import ChatConversation, ChatMessage
from app.services.assistant_web_search import (
    BING_SEARCH_URL,
    AssistantSearchError,
    build_search_query,
    filter_relevant_results,
    parse_bing_rss,
    search_web,
)


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


def test_career_query_drops_conversational_filler_and_keeps_concrete_terms():
    query = build_search_query("如果我秋招投递互联网大厂没通过，会有投递冷却期吗？")

    assert query == "秋招 投递 互联网大厂 冷却期 招聘"
    assert "如果" not in query


def test_recent_internet_recruitment_query_uses_stable_short_keywords():
    question = "给我一些最近刚发布招聘信息的互联网企业"

    assert build_search_query(question) == "互联网企业 招聘"


def test_recruitment_discovery_keeps_careers_pages_without_chinese_recruitment_words():
    question = "给我一些最近刚发布招聘信息的互联网企业"
    results = filter_relevant_results(
        [
            {
                "title": "Careers at Example",
                "url": "https://careers.example.com/jobs",
                "snippet": "Explore open opportunities.",
            },
            {
                "title": "给（汉语汉字）_百度百科",
                "url": "https://baike.baidu.com/item/example",
                "snippet": "汉语常用字释义。",
            },
        ],
        question,
    )

    assert [result["url"] for result in results] == ["https://careers.example.com/jobs"]


def test_career_search_filters_unrelated_dictionary_and_poem_results():
    question = "如果我秋招投递互联网大厂没通过，会有投递冷却期吗？"
    results = filter_relevant_results(
        [
            {
                "title": "如果（汉语假设连词）_百度百科",
                "url": "https://baike.baidu.com/item/example",
                "snippet": "如果是表示假设关系的连词。",
            },
            {
                "title": "互联网企业校园招聘常见问题",
                "url": "https://careers.example.com/campus-faq",
                "snippet": "秋招投递未通过后的再次申请与招聘安排说明。",
            },
            {
                "title": "诗歌《如果》原文",
                "url": "https://example.com/poem",
                "snippet": "一首关于人生选择的诗歌。",
            },
        ],
        question,
    )

    assert [result["url"] for result in results] == ["https://careers.example.com/campus-faq"]


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


@pytest.mark.asyncio
async def test_search_web_rejects_unrelated_results_for_a_career_question(monkeypatch):
    xml = """<rss><channel>
    <item><title>如果（汉语假设连词）_百度百科</title>
    <link>https://baike.baidu.com/item/example</link><description>表示假设关系。</description></item>
    </channel></rss>""".encode("utf-8")
    captured = {}

    async def fake_fetch(query: str):
        captured["query"] = query
        return xml

    monkeypatch.setattr("app.services.assistant_web_search.fetch_bing_rss", fake_fetch)
    with pytest.raises(AssistantSearchError, match="直接相关"):
        await search_web("如果我秋招投递互联网大厂没通过，会有投递冷却期吗？")
    assert captured["query"] == "秋招 投递 互联网大厂 冷却期 招聘"


@pytest.mark.asyncio
async def test_search_web_filters_ten_candidates_before_limiting_results(monkeypatch):
    unrelated_items = "".join(
        f"<item><title>无关结果 {index}</title>"
        f"<link>https://example.com/article/{index}</link>"
        "<description>与求职无关的普通新闻内容。</description></item>"
        for index in range(1, 6)
    )
    xml = (
        "<rss><channel>"
        f"{unrelated_items}"
        "<item><title>Example Careers</title>"
        "<link>https://careers.example.org/jobs</link>"
        "<description>Explore open opportunities.</description></item>"
        "</channel></rss>"
    ).encode("utf-8")

    async def fake_fetch(_query: str):
        return xml

    monkeypatch.setattr("app.services.assistant_web_search.fetch_bing_rss", fake_fetch)

    results = await search_web("给我一些最近刚发布招聘信息的互联网企业")

    assert [result["url"] for result in results] == ["https://careers.example.org/jobs"]


def test_chat_migration_builds_history_tables_and_cascades(tmp_path):
    migration_engine = create_engine(f"sqlite:///{tmp_path / 'assistant-migration.db'}")
    config = build_alembic_config(migration_engine)
    try:
        command.upgrade(config, "head")
        inspector = inspect(migration_engine)
        assert {"chat_conversation", "chat_message"} <= set(inspector.get_table_names())
        assert {"title", "pinned", "favorite", "created_at", "updated_at"} <= {
            item["name"] for item in inspector.get_columns("chat_conversation")
        }
        assert {"attachments", "context", "status", "error", "model"} <= {
            item["name"] for item in inspector.get_columns("chat_message")
        }
        with migration_engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0007_assistant_skills"
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
