"""按岗位需求发现候选公司。

两组用例，各自守一条容易做错的事：

- **第三方招聘平台的页面必须整个剔掉**（不是降权）。把智联、拉勾的页面当成"某公司的官网"
  去采集是错的，而用户看到它在清单里就会以为那就是官网；
- **措辞必须说清这是线索**。用户把它当完整名单，就会漏掉一大批公司而不自知——那正是这个
  功能最该避免的错误。
"""
from __future__ import annotations

import pytest

from app.schemas.setting import SearchConfig
from app.services.assistant.assistant_web_search import AssistantSearchError
from app.services.sites.official.discovery import (
    CANDIDATE_LIMIT,
    build_queries,
    discover_companies,
)

CONFIG = SearchConfig()


def _result(title: str, url: str) -> dict[str, str]:
    return {"title": title, "url": url, "snippet": ""}


def _search_returning(*groups):
    """按查询顺序返回不同结果的假搜索；调用记录也留下来供断言。"""
    calls: list[str] = []

    async def search(query: str, config: SearchConfig):
        del config
        index = min(len(calls), len(groups) - 1)
        calls.append(query)
        return list(groups[index]) if groups else []

    search.calls = calls
    return search


# ===== 查询构造 =====


def test_build_queries_uses_two_phrasings():
    """两条查询换召回：真实的中文招聘页大量使用「加入我们」，而它常不在通用查询的前排。"""
    queries = build_queries("大模型应用开发", "北京")

    assert len(queries) == 2
    assert all("大模型应用开发" in q for q in queries)
    assert all("北京" in q for q in queries)
    assert any("加入我们" in q for q in queries)


def test_build_queries_without_city():
    assert build_queries("算法工程师") == ["算法工程师 招聘", "算法工程师 加入我们 招聘"]


def test_build_queries_normalises_whitespace():
    assert build_queries("  AI   应用  ", " 上海 ") == [
        "AI 应用 上海 招聘",
        "AI 应用 上海 加入我们 招聘",
    ]


def test_build_queries_without_keywords():
    assert build_queries("   ") == []


# ===== 第三方平台 =====


@pytest.mark.parametrize(
    "url",
    [
        "https://www.zhipin.com/gongsi/abc.html",
        "https://www.lagou.com/wn/jobs/123.html",
        "https://www.liepin.com/company/1/",
        "https://www.51job.com/",
        "https://www.nowcoder.com/company/1",
        "https://www.zhihu.com/question/1",
    ],
)
async def test_third_party_pages_are_excluded_entirely(url):
    """**整个剔掉，不是降权**：它们在清单里会让用户以为那就是这家公司的官网。"""
    search = _search_returning([_result("某公司招聘", url)])
    result = await discover_companies("算法", config=CONFIG, search=search)

    assert result.candidates == []


async def test_company_site_survives_next_to_a_third_party_result():
    search = _search_returning(
        [
            _result("招聘 - 拉勾网", "https://www.lagou.com/wn/jobs/1.html"),
            _result("示例科技招聘", "https://careers.example.com/jobs"),
        ]
    )
    result = await discover_companies("算法", config=CONFIG, search=search)

    assert [c.host for c in result.candidates] == ["careers.example.com"]


# ===== 去重与上限 =====


async def test_same_host_is_kept_once():
    """同一家公司的多个页面只留一条——列表是给人勾选的，重复项只会碍事。"""
    search = _search_returning(
        [
            _result("示例科技招聘", "https://careers.example.com/jobs"),
            _result("示例科技 - 社会招聘", "https://careers.example.com/social"),
            _result("另一家公司招聘", "https://jobs.other.com/"),
        ]
    )
    result = await discover_companies("算法", config=CONFIG, search=search)

    assert [c.host for c in result.candidates] == ["careers.example.com", "jobs.other.com"]


async def test_candidate_count_is_capped():
    many = [_result(f"公司{i}招聘", f"https://careers.company{i}.com/jobs") for i in range(50)]
    result = await discover_companies("算法", config=CONFIG, search=_search_returning(many))

    assert len(result.candidates) == CANDIDATE_LIMIT


# ===== 公司名建议 =====


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("示例科技招聘", "示例科技"),
        ("腾讯校园招聘", "腾讯"),
        ("字节跳动社会招聘 - 加入我们", "字节跳动"),
        ("某公司 招聘官网", "某公司"),
        ("某某公司 - 诚聘英才", "某某公司"),
        # 标记在**开头**时，公司名只可能在它后面——"招聘 - 某某科技"是常见写法。
        ("招聘 - 某某科技", "某某科技"),
        ("校园招聘 | 某某集团", "某某集团"),
    ],
)
async def test_company_name_is_suggested_from_the_title(title, expected):
    """**按长到短切**：先切「校园招聘」再切「招聘」，否则"腾讯校园招聘"会被切成"腾讯校园"。"""
    search = _search_returning([_result(title, "https://careers.example.com/jobs")])
    result = await discover_companies("算法", config=CONFIG, search=search)

    assert result.candidates[0].company == expected


@pytest.mark.parametrize("title", ["招聘", "加入我们", "校园招聘", "招聘 - 加入我们"])
async def test_company_name_falls_back_to_the_host(title):
    """标题**只有**招聘词时切不出公司名，用域名标签兜底——总比把"招聘"当公司名强，
    而且用户可以改。"""
    search = _search_returning([_result(title, "https://careers.bytedance.com/jobs")])
    result = await discover_companies("算法", config=CONFIG, search=search)

    assert result.candidates[0].company == "bytedance"


async def test_noise_prefixes_are_stripped():
    search = _search_returning([_result("知乎 - 某公司招聘", "https://careers.example.com/jobs")])
    result = await discover_companies("算法", config=CONFIG, search=search)

    assert "知乎" not in result.candidates[0].company


# ===== 目标字段 =====


async def test_careers_pages_and_homepages_are_told_apart():
    """招聘页进 ``careers_url``，公司首页进 ``homepage_url``（后者靠通用路径多跳找招聘栏目）。"""
    search = _search_returning(
        [
            _result("示例科技招聘", "https://careers.example.com/jobs"),
            _result("另一家", "https://www.other.com/about"),
        ]
    )
    result = await discover_companies("算法", config=CONFIG, search=search)

    by_host = {c.host: c for c in result.candidates}
    assert by_host["careers.example.com"].is_careers_page is True
    assert by_host["www.other.com"].is_careers_page is False


# ===== 措辞与容错 =====


async def test_empty_result_says_search_found_nothing_not_that_nobody_is_hiring():
    """**搜不到 ≠ 没有公司在招。** 这句必须说清楚，否则用户会以为市场上就这些。"""
    result = await discover_companies("很冷门的岗位", config=CONFIG, search=_search_returning([], []))

    assert result.candidates == []
    assert "不代表没有公司在招" in result.detail
    assert result.queries, "搜了什么要如实告诉用户"


async def test_success_message_says_it_is_a_lead_list():
    """用户把线索当完整名单，就会漏掉一大批公司而不自知。"""
    search = _search_returning([_result("示例科技招聘", "https://careers.example.com/jobs")])
    result = await discover_companies("算法", config=CONFIG, search=search)

    assert "线索" in result.detail
    assert "不代表在招的公司就这些" in result.detail


async def test_queries_are_reported_for_both_attempts():
    search = _search_returning([_result("示例科技招聘", "https://careers.example.com/jobs")])
    result = await discover_companies("算法", "北京", config=CONFIG, search=search)

    assert len(result.queries) == 2
    assert len(search.calls) == 2


async def test_one_failing_query_does_not_lose_the_other():
    """单条查询没结果不该让整次发现失败——另一条可能还有货。"""
    calls: list[str] = []

    async def search(query: str, config: SearchConfig):
        del config
        calls.append(query)
        if len(calls) == 1:
            raise AssistantSearchError("没有找到相关的公开来源")
        return [_result("示例科技招聘", "https://careers.example.com/jobs")]

    result = await discover_companies("算法", config=CONFIG, search=search)

    assert len(result.candidates) == 1


async def test_all_queries_failing_still_reports_honestly():
    async def search(query: str, config: SearchConfig):
        del query, config
        raise AssistantSearchError("没有找到相关的公开来源")

    result = await discover_companies("算法", config=CONFIG, search=search)

    assert result.candidates == []
    assert result.detail


async def test_missing_keywords_short_circuits_without_searching():
    called: list[str] = []

    async def search(query: str, config: SearchConfig):
        del config
        called.append(query)
        return []

    result = await discover_companies("   ", config=CONFIG, search=search)

    assert result.candidates == []
    assert called == []
    assert "关键词" in result.detail


async def test_results_without_a_url_are_skipped():
    search = _search_returning(
        [
            {"title": "没有链接的结果", "url": "", "snippet": ""},
            _result("示例科技招聘", "https://careers.example.com/jobs"),
        ]
    )
    result = await discover_companies("算法", config=CONFIG, search=search)

    assert len(result.candidates) == 1
