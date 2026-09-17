"""多来源搜索聚合与正文抓取的离线测试。

联网部分（真实端点）不在测试范围内——那些由运行时的降级逻辑兜住；这里钉住的是
容易写错又难发现的部分：合并顺序、去重、单来源失败降级、正文只抓前 N 条、
以及「不允许抓内网地址」这条安全边界。
"""
import pytest

from app.schemas.setting import SearchConfig
from app.services.assistant_web_search import AssistantSearchError
from app.services.search import aggregate as aggregate_module
from app.services.search.aggregate import aggregate_search
from app.services.search.duckduckgo import _unwrap_redirect
from app.services.search.page_reader import extract_text, is_public_http_url


def _result(title: str, url: str, snippet: str = "摘要") -> dict[str, str]:
    return {"title": title, "url": url, "snippet": snippet}


def test_unwrap_redirect_decodes_duckduckgo_links():
    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fcareers.example.com%2Fjobs&rut=abc"
    assert _unwrap_redirect(wrapped) == "https://careers.example.com/jobs"
    # 普通外链原样返回，DuckDuckGo 自家页面被丢掉（那是广告与设置页）。
    assert _unwrap_redirect("https://careers.example.com/jobs") == "https://careers.example.com/jobs"
    assert _unwrap_redirect("https://duckduckgo.com/y.js?ad=1") == ""


def test_extract_text_skips_scripts_and_short_noise():
    html = """
    <html><head><style>.a{color:red}</style><script>alert(1)</script></head>
    <body>
      <nav><p>首页 关于我们</p></nav>
      <p>这是一段足够长的正文内容，用来验证正文提取会保留它。</p>
      <p>短</p>
      <ul><li>第二条足够长的列表内容，也应被保留下来。</li></ul>
    </body></html>
    """
    text = extract_text(html)
    assert "足够长的正文内容" in text
    assert "第二条足够长的列表内容" in text
    assert "alert(1)" not in text
    assert "color:red" not in text
    # 过短的片段（导航、标签）被丢掉。
    assert "\n短" not in text


def test_is_public_http_url_rejects_local_targets():
    assert is_public_http_url("http://127.0.0.1:8080/jobs") is False
    assert is_public_http_url("http://localhost/jobs") is False
    assert is_public_http_url("http://10.0.0.5/internal") is False
    assert is_public_http_url("file:///etc/passwd") is False
    assert is_public_http_url("https://user:pass@example.com/jobs") is False


@pytest.mark.asyncio
async def test_aggregate_interleaves_deduplicates_and_ranks_official_first(monkeypatch):
    # 注意：标题与摘要要带招聘语义，否则会被既有的相关性过滤丢掉——那正是它该做的事。
    async def fake_bing(_query: str):
        return [
            _result("第三方平台的招聘信息", "https://www.zhipin.com/job/1"),
            _result("后端工程师招聘（转载）", "https://careers.example.com/jobs/9"),
        ]

    async def fake_ddg(_query: str, limit: int = 10):
        return [
            _result("后端工程师招聘（转载）", "https://careers.example.com/jobs/9/"),
            _result("后端工程师招聘官网", "https://careers.example.com/jobs/2"),
        ]

    monkeypatch.setattr(aggregate_module, "bing_search", fake_bing)
    monkeypatch.setattr(aggregate_module, "search_duckduckgo", fake_ddg)

    results = await aggregate_search(
        "后端 招聘", SearchConfig(sources=["bing", "duckduckgo"], max_results=8)
    )

    urls = [item["url"] for item in results]
    # 重复（含 / 与不带 / 的同一路径）只留一条。
    assert len(urls) == len(set(urls))
    assert sum(1 for url in urls if url.startswith("https://careers.example.com")) == 2
    # 用人单位官网排在第三方平台之前。
    assert urls[0].startswith("https://careers.example.com")


@pytest.mark.asyncio
async def test_aggregate_survives_a_failing_source(monkeypatch):
    async def failing_bing(_query: str):
        raise AssistantSearchError("超时")

    async def fake_ddg(_query: str, limit: int = 10):
        return [_result("后端工程师招聘官网", "https://careers.example.com/jobs/2")]

    monkeypatch.setattr(aggregate_module, "bing_search", failing_bing)
    monkeypatch.setattr(aggregate_module, "search_duckduckgo", fake_ddg)

    results = await aggregate_search("后端 招聘", SearchConfig(sources=["bing", "duckduckgo"]))
    assert [item["url"] for item in results] == ["https://careers.example.com/jobs/2"]


@pytest.mark.asyncio
async def test_aggregate_raises_when_every_source_is_empty(monkeypatch):
    async def empty_bing(_query: str):
        raise AssistantSearchError("没有结果")

    async def empty_ddg(_query: str, limit: int = 10):
        return []

    monkeypatch.setattr(aggregate_module, "bing_search", empty_bing)
    monkeypatch.setattr(aggregate_module, "search_duckduckgo", empty_ddg)

    with pytest.raises(AssistantSearchError, match="没有找到"):
        await aggregate_search("后端 招聘", SearchConfig(sources=["bing", "duckduckgo"]))


@pytest.mark.asyncio
async def test_aggregate_fetches_page_text_only_for_the_first_n(monkeypatch):
    async def fake_bing(_query: str):
        return [
            _result(f"后端工程师招聘 {index}", f"https://careers.example.com/jobs/{index}")
            for index in range(1, 4)
        ]

    fetched: list[str] = []

    async def fake_fetch(url: str, max_chars: int = 0):
        fetched.append(url)
        return "这是抓回来的正文节选。"

    monkeypatch.setattr(aggregate_module, "bing_search", fake_bing)
    monkeypatch.setattr(aggregate_module, "fetch_page_text", fake_fetch)

    results = await aggregate_search(
        "后端 招聘", SearchConfig(sources=["bing"], fetch_pages=2)
    )

    assert len(fetched) == 2
    assert results[0]["text"] == "这是抓回来的正文节选。"
    assert results[1]["text"]
    assert "text" not in results[2]


@pytest.mark.asyncio
async def test_searxng_source_is_skipped_without_a_url(monkeypatch):
    called: list[str] = []

    async def fake_searxng(_query: str, base_url: str, limit: int = 10):
        called.append(base_url)
        return [_result("后端工程师招聘官网", "https://careers.example.com/jobs/2")]

    async def fake_bing(_query: str):
        return [_result("后端工程师招聘汇总", "https://careers.example.com/jobs/3")]

    monkeypatch.setattr(aggregate_module, "search_searxng", fake_searxng)
    monkeypatch.setattr(aggregate_module, "bing_search", fake_bing)

    # 没填地址时不该去请求任何 SearXNG 端点。
    await aggregate_search("后端 招聘", SearchConfig(sources=["bing", "searxng"]))
    assert called == []

    await aggregate_search(
        "后端 招聘",
        SearchConfig(sources=["bing", "searxng"], searxng_url="http://localhost:8080"),
    )
    assert called == ["http://localhost:8080"]


def test_search_config_validates_urls_and_limits():
    with pytest.raises(ValueError):
        SearchConfig(searxng_url="localhost:8080")
    assert SearchConfig(searxng_url="http://localhost:8080/").searxng_url == "http://localhost:8080"
    # 去重来源，避免同一个引擎被查两次。
    assert SearchConfig(sources=["bing", "bing"]).sources == ["bing"]
