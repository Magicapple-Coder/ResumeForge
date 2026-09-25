"""看清「这一页渲染出来到底长什么样」——排查"开了渲染还是读不出岗位"。

**它连网，所以不属于测试套件**，与 ``probe_official_site.py`` 同一条规则：想确认某个真实
站点的读取情况时手工跑它，而不是往测试里塞一个联网用例。

## 它和 ``probe_official_site.py`` 的分工

那个脚本**只用 HTTP**（刻意不依赖任何本地状态），所以它答不了"渲染之后呢"。而真实站点上
最费解的一种失败恰好在那之后：报告写着「没读出来」，日志里却明明有
「HTTP 取回是空壳，改用浏览器渲染成功」——**浏览器确实渲染了，可抽取层还是一个链接都没认出来**。
这时需要知道的不是"能不能连上"，而是"渲染后的 DOM 里到底有什么"：

- 渲染出来的页面有多大？还是空壳吗（``needs_rendering`` 怎么说）？
- 里面有 ``<a href>`` 吗？有多少？其中**同主机**的（抽取层只收同主机的）有几个？
- 一个都没有的话，是被 JS 点击处理器代替了（``<div onclick>`` 那种），还是链接指向了别的域名？

## 用法

它**会驱动投递台那个浏览器**（与采集时做的是同一件事：打开这个地址、读回渲染后的 DOM）。
所以投递台浏览器得先在运行——在官网采集页顶部点「启动浏览器」即可。浏览器没在跑时它不会
自己去拉起一个，只会如实说"渲染这一路验不了"。

    backend\\.venv\\Scripts\\python.exe scripts\\inspect_official_page.py https://example.com/jobs

只读：不写数据库、不改任何本地状态。取回同样过 robots 闸门与 SSRF 防护（走的是产品自己那条
传输链），请求数量个位数。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.services.sites.official.browser_http import BrowserRenderedHttp  # noqa: E402
from app.services.sites.official.generic.body import extract_page_body  # noqa: E402
from app.services.sites.official.generic.dom import parse_document  # noqa: E402
from app.services.sites.official.generic.recipe import (  # noqa: E402
    card_of,
    default_recipe,
    extract_with_recipe,
    page_base,
)
from app.services.sites.official.html_text import html_to_text  # noqa: E402
from app.services.sites.official.http import HttpxFeedHttp  # noqa: E402
from app.services.sites.official.rendering import needs_rendering  # noqa: E402
from app.services.sites.official.robots import RobotsAwareHttp  # noqa: E402
from app.services.sites.official.service import default_browser_client  # noqa: E402

# 打印前几个链接就够了：要回答的是"有没有、长的什么样"，不是把整页列出来。
SAMPLE_LINKS = 12
# 卡片文字印这么长，够看清它是岗位名还是一个"更多"按钮。
SAMPLE_TEXT = 60


def _say(text: str = "") -> None:
    print(text)


def _kb(text: str) -> str:
    return f"{len(text.encode('utf-8', errors='replace')) / 1024:.0f} KB"


def _extraction_report(markup: str, page_url: str) -> None:
    """产品自己的抽取层（**只跑免费的那一级**：默认配方）从这一页读出什么。

    这才是用户真正问的问题——"这一页能不能采"。上面那些统计是给"读不出来"时定位用的，
    这一条直接给答案。刻意**不跑模型那一级**：本脚本不该花用户的钱，也不该依赖他的模型配置。
    默认配方读不出来时，这说明这一页要靠归纳配方或模型——那是应用里才会发生的事。
    """
    jobs = extract_with_recipe(default_recipe(), markup, page_url=page_url)
    if not jobs:
        _say("  默认配方（免费那一级）：一条也没读出来")
        _say("  → 这一页要靠已存的配方或模型兜底；在应用里采集时会自动往下试。")
    else:
        _say(f"  默认配方（免费那一级）：读出 {len(jobs)} 条岗位")
        for job in jobs[:5]:
            where = f"　{job.location}" if job.location else ""
            _say(f"    · {job.title}{where}")
        if len(jobs) > 5:
            _say(f"    ……另有 {len(jobs) - 5} 条")

    # 正文单独说：它是**这一页自己**的内容（详情页才有），不属于上面列出的任何一条岗位。
    # 没有它时，采到的岗位只有标题——技能标签、岗位匹配、简历定制全都拿不到 JD 文本。
    body = extract_page_body(markup)
    if not body:
        _say("  这一页的正文：没读出来（详情页 JD 才会命中章节标题）")
        return
    _say(f"  这一页的正文：职位描述 {len(body.description)} 字符、任职要求 {len(body.requirements)} 字符")
    for label, text in (("职位描述", body.description), ("任职要求", body.requirements)):
        if text:
            _say(f"    {label}：{text[:80]}{'……' if len(text) > 80 else ''}")


def _link_report(markup: str, page_url: str) -> None:
    """按**抽取层同一份判据**统计链接，而不是另写一套。

    两边判据一旦不同，这个脚本就会给出与采集不一致的答案——那比没有脚本更坏。
    """
    document = parse_document(markup)
    base = page_base(document, page_url)
    host = (urlsplit(base).hostname or "").casefold()

    anchors = document.hrefs()
    same_host: list[tuple[int, str]] = []
    seen: set[str] = set()
    for index, href in anchors:
        try:
            url = urljoin(base, href).split("#", 1)[0]
        except ValueError:
            continue
        if not url or url in seen:
            continue
        if (urlsplit(url).hostname or "").casefold() != host:
            continue
        seen.add(url)
        same_host.append((index, url))

    # 可读文字用**阻断识别那份同一函数**：两边算法不同的话，这个脚本给出的
    # "这一页文字很少"会和产品自己的判据对不上。
    _say(f"  可读文字：{len(html_to_text(markup))} 字符")
    _say(f"  元素总数：{len(document.elements)}")

    all_anchors = [element for element in document.elements if element.tag == "a"]
    hrefless = [element for element in all_anchors if not element.attrs.get("href", "").strip()]
    _say(f"  <a> 元素：{len(all_anchors)} 个，其中没有 href 的 {len(hrefless)} 个")
    _say(f"  <a href> 总数：{len(anchors)}")
    _say(f"  去重后的同主机链接：{len(same_host)}（抽取层只收这些）")
    if not anchors:
        _say("  **一个可用的 <a href> 都没有。**")
        if hrefless:
            _say("  页面里确实有 <a>，但它们**没有 href**——列表项用的是 JS 点击处理器")
            _say("  （React/Vue 里的 onClick + role=link 那种）。抽取层按 href 找链接，")
            _say("  所以这一页对它等于空白，岗位名都读不到。")
        else:
            _say("  页面里连 <a> 元素都没有：内容挂在别的元素上，或者这一页根本没渲染出列表。")
        return

    other_hosts = {
        (urlsplit(urljoin(base, href)).hostname or "").casefold()
        for _, href in anchors
        if (urlsplit(urljoin(base, href)).hostname or "").casefold() != host
    }
    if other_hosts:
        _say(f"  非同主机链接来自：{', '.join(sorted(other_hosts)[:6])}")

    link_urls = dict(same_host)
    for order, (index, url) in enumerate(same_host[:SAMPLE_LINKS], start=1):
        anchor_text = document.text(index)[:SAMPLE_TEXT]
        card = card_of(document, index, link_urls=link_urls)
        card_text = document.text(card)[:SAMPLE_TEXT]
        _say(f"    {order}. {url}")
        _say(f"       链接文字：{anchor_text or '(空)'}")
        if card_text != anchor_text:
            _say(f"       所在条目：{card_text or '(空)'}")


async def _inspect(url: str, *, skip_render: bool, dump_path: str | None = None) -> int:
    _say(f"地址：{url}")
    _say()

    # ===== 第一段：纯 HTTP =====
    _say("[1/2] 纯 HTTP 取回")
    async with HttpxFeedHttp() as inner:
        http = RobotsAwareHttp.wrap(inner)
        result = await http.request("GET", url)
        _say(f"  状态：{result.status_code}　阻断：{result.block or '无'}")
        if result.detail:
            _say(f"  说明：{result.detail}")
        if not result.ok:
            _say("  取回失败，后面的渲染就没有意义了。")
            return 1
        _say(f"  大小：{_kb(result.text)}")
        _say(f"  需要渲染：{needs_rendering(result.text)}")
        _link_report(result.text, url)

    if skip_render:
        _say()
        _say("（--http-only：跳过渲染那一段）")
        return 0

    # ===== 第二段：真浏览器渲染 =====
    _say()
    _say("[2/2] 浏览器渲染（与采集时的渲染升级是同一段代码）")
    db = SessionLocal()
    try:
        client = default_browser_client(db)
        if client is None:
            _say("  投递台浏览器没在运行，这一路验不了。")
            _say("  在官网采集页顶部点「启动浏览器」之后重跑本脚本。")
            return 1
        rendered = await BrowserRenderedHttp(client).request("GET", url)
        if dump_path is not None and rendered.text:
            # 存**取回的那一份**（含截断），不是另取一份：要看的正是产品看到的东西。
            Path(dump_path).write_text(rendered.text, encoding="utf-8")
            _say(f"  原文已存到 {dump_path}")
    finally:
        db.close()

    _say(f"  状态：{rendered.status_code}　阻断：{rendered.block or '无'}")
    if rendered.detail:
        _say(f"  说明：{rendered.detail}")
    if not rendered.ok:
        _say("  渲染没成功——报告里读不出岗位的原因就在这一段。")
        return 1
    _say(f"  大小：{_kb(rendered.text)}")
    _say(f"  仍然是空壳：{needs_rendering(rendered.text)}")
    _link_report(rendered.text, url)
    _say()
    _say("[结论] 这一页能不能读出来")
    _extraction_report(rendered.text, url)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="看清一个招聘页渲染之后长什么样")
    parser.add_argument("url", help="要检查的地址")
    parser.add_argument(
        "--http-only",
        action="store_true",
        help="只跑纯 HTTP 那一段，不驱动浏览器",
    )
    parser.add_argument(
        "--dump",
        metavar="路径",
        help="把渲染取回的原文存到这里（含截断），用于逐字查看页面里到底有什么",
    )
    args = parser.parse_args()
    return asyncio.run(
        _inspect(args.url, skip_render=args.http_only, dump_path=args.dump)
    )


if __name__ == "__main__":
    raise SystemExit(main())
