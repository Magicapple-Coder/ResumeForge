"""站点地图的取回与解析。

两组用例各有明确目的：

- **安全**：站点地图是不可信 XML。实体展开类攻击（billion laughs 能把几 KB 炸成几 GB）
  必须被前置拒绝，且这条检查要在**解析之前**——解析器一旦开始展开就已经晚了。
- **诚实**：取不到、格式不认识、被上限截断都要如实说出来。安静地返回空集合会让上层
  把"这一层做不了"当成"站点地图是空的"，进而给出一个看起来干净、实际没有依据的结论。
"""
from __future__ import annotations

from app.models.official import BLOCK_NONE, BLOCK_NOT_FOUND
from app.services.sites.official.base import FeedHttp, FetchResult
from app.services.sites.official.sitemap import (
    fetch_sitemap_urls,
    is_safe_xml,
    parse_sitemap,
)

URLSET = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.example/jobs/1</loc></url>
  <url><loc>https://acme.example/jobs/2</loc></url>
  <url><loc>https://acme.example/about</loc></url>
</urlset>"""

SITEMAPINDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://acme.example/jobs-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://acme.example/blog-sitemap.xml</loc></sitemap>
</sitemapindex>"""


class FakeHttp(FeedHttp):
    def __init__(self, routes: dict[str, FetchResult]):
        self._routes = routes
        self.calls: list[str] = []

    async def request(self, method, url, *, params=None, json_body=None, headers=None,
                      max_bytes=None):
        del method, params, json_body, headers, max_bytes
        self.calls.append(url)
        for prefix, result in self._routes.items():
            if url.startswith(prefix):
                return result
        return FetchResult(block=BLOCK_NOT_FOUND, status_code=404)


def _xml(text: str) -> FetchResult:
    return FetchResult(block=BLOCK_NONE, status_code=200, text=text, headers={})


ALLOW_ALL = FetchResult(block=BLOCK_NONE, status_code=200, text="User-agent: *\nDisallow:\n")


def _robots(host: str) -> dict[str, FetchResult]:
    """该主机的 robots 路由（放行）。站点地图取回本身也要过这道闸门。"""
    return {f"https://{host}/robots.txt": ALLOW_ALL}


# ===== 解析 =====


def test_parse_urlset():
    pages, nested = parse_sitemap(URLSET)
    assert pages == [
        "https://acme.example/jobs/1",
        "https://acme.example/jobs/2",
        "https://acme.example/about",
    ]
    assert nested == []


def test_parse_sitemap_index():
    pages, nested = parse_sitemap(SITEMAPINDEX)
    assert pages == []
    assert nested == [
        "https://acme.example/jobs-sitemap.xml",
        "https://acme.example/blog-sitemap.xml",
    ]


def test_parse_ignores_namespace_variants():
    """命名空间前缀写法不统一是常态，认本地名即可。"""
    text = (
        '<urlset xmlns:s="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<s:url><s:loc>https://acme.example/jobs/9</s:loc></s:url></urlset>"
    )
    pages, _ = parse_sitemap(text)
    assert pages == ["https://acme.example/jobs/9"]


def test_parse_malformed_returns_empty():
    assert parse_sitemap("<urlset><url>") == ([], [])
    assert parse_sitemap("完全不是 XML") == ([], [])


def test_parse_empty_loc_is_skipped():
    text = "<urlset><url><loc></loc></url><url><loc>https://a.example/1</loc></url></urlset>"
    pages, _ = parse_sitemap(text)
    assert pages == ["https://a.example/1"]


# ===== 安全边界 =====


def test_entity_declarations_are_rejected_before_parsing():
    """billion laughs 的入口就是内部实体声明。一旦交给解析器展开就晚了，所以必须前置拒绝。"""
    bomb = """<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
]>
<urlset><url><loc>&lol2;</loc></url></urlset>"""
    assert is_safe_xml(bomb) is False
    assert parse_sitemap(bomb) == ([], [])


def test_external_entity_declaration_is_rejected():
    """XXE：``SYSTEM`` 声明能把本地文件读进解析结果。"""
    xxe = '<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><urlset/>'
    assert is_safe_xml(xxe) is False
    assert parse_sitemap(xxe) == ([], [])


def test_safe_documents_pass_the_check():
    assert is_safe_xml(URLSET) is True
    assert is_safe_xml(SITEMAPINDEX) is True


# ===== 取回 =====


async def test_fetches_and_follows_the_index():
    http = FakeHttp({
        **_robots("acme.example"),
        "https://acme.example/sitemap.xml": _xml(SITEMAPINDEX),
        "https://acme.example/jobs-sitemap.xml": _xml(URLSET),
        "https://acme.example/blog-sitemap.xml": _xml(
            "<urlset><url><loc>https://acme.example/blog/1</loc></url></urlset>"
        ),
    })

    result = await fetch_sitemap_urls(http, ["https://acme.example/sitemap.xml"])

    assert result.usable is True
    assert "https://acme.example/jobs/1" in result.urls
    assert "https://acme.example/blog/1" in result.urls
    assert len(result.fetched) == 3


async def test_missing_sitemap_is_reported_not_silently_empty():
    """取不到要如实说——安静的返回空集合会让上层把"做不了"当成"地图是空的"。"""
    http = FakeHttp({})

    result = await fetch_sitemap_urls(http, ["https://acme.example/sitemap.xml"])

    assert result.usable is False
    assert result.detail


async def test_no_declared_sitemap_is_reported():
    result = await fetch_sitemap_urls(FakeHttp({}), [])
    assert result.usable is False
    assert "未声明" in result.detail


async def test_gzipped_sitemap_is_reported_as_unsupported():
    """压缩站点地图取回来是二进制，会被按 UTF-8 容错解码成乱码。

    与其安静地解析出一个空集合，不如明说这一层做不了。
    """
    http = FakeHttp({})

    result = await fetch_sitemap_urls(http, ["https://acme.example/sitemap.xml.gz"])

    assert result.usable is False
    assert "压缩" in result.detail
    assert http.calls == [], "既然不支持，就不该白打一次请求"


async def test_nested_sitemap_limit_marks_the_result_unusable():
    """被上限截断的收集**不能**拿去做集合对账：差额会凭空多出一堆。"""
    many = "".join(
        f"<sitemap><loc>https://acme.example/s{index}.xml</loc></sitemap>"
        for index in range(20)
    )
    routes = {
        **_robots("acme.example"),
        "https://acme.example/sitemap.xml": _xml(f"<sitemapindex>{many}</sitemapindex>"),
    }
    for index in range(20):
        routes[f"https://acme.example/s{index}.xml"] = _xml(URLSET)

    result = await fetch_sitemap_urls(
        FakeHttp(routes), ["https://acme.example/sitemap.xml"], max_sitemaps=3
    )

    assert result.truncated is True
    assert result.usable is False
    assert "截断" in result.detail


async def test_url_limit_marks_the_result_unusable():
    urls = "".join(f"<url><loc>https://acme.example/j{index}</loc></url>" for index in range(50))
    http = FakeHttp({
        **_robots("acme.example"),
        "https://acme.example/sitemap.xml": _xml(f"<urlset>{urls}</urlset>"),
    })

    result = await fetch_sitemap_urls(http, ["https://acme.example/sitemap.xml"], max_urls=10)

    assert result.truncated is True
    assert result.usable is False


async def test_sitemap_fetch_respects_robots():
    """站点地图也是一次抓取，没有理由不受 robots 约束。"""
    http = FakeHttp({
        "https://acme.example/robots.txt": FetchResult(
            block=BLOCK_NONE, status_code=200, text="User-agent: *\nDisallow: /\n"
        ),
        "https://acme.example/sitemap.xml": _xml(URLSET),
    })

    result = await fetch_sitemap_urls(http, ["https://acme.example/sitemap.xml"])

    assert result.usable is False
    assert "https://acme.example/sitemap.xml" not in http.calls, "被拒绝后不该再去取"
