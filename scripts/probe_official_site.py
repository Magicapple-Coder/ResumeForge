"""拿一个真实地址跑一遍官网采集的探测与取回，把结果如实打出来。

**它连网，所以不属于测试套件。** 项目规则是"测试默认不许真的联网"（离线用例才能
在 CI 上稳定、也只有那样才能证明链路不依赖外部状态）。这个脚本是那条规则之外的**人工
验证入口**：想确认"某个真实站点现在能不能采、读到些什么"时用它，而不是往测试里塞一个
联网用例。

它走的是**产品自己那条链路**——真实的 robots 闸门、真实的 SSRF 防护、真实的适配器与
抽取层。所以它打出来的东西就是用户点「采集」时会得到的东西，只是多了一层诊断输出。
用途有三个：

1. **验证适配器**：新写了一家招聘系统的适配器，拿它的真实地址跑一次，看解析对不对；
2. **取样本**：要给一套新系统写适配器时，先用它确认端点长什么样（见下面「取样本」）；
3. **排查"这家公司采不到"**：把输出贴出来，比"点了没反应"信息量大得多。

用法（在仓库根目录执行，**会发起真实网络请求**）：

    backend\\.venv\\Scripts\\python.exe scripts\\probe_official_site.py https://boards.greenhouse.io/某公司

只读，不写数据库、不改任何本地状态；请求数量个位数，且尊重站点的 ``robots.txt``。

**它只用 HTTP，不启用渲染升级**（那一级要投递台的浏览器在运行，而本脚本刻意不依赖任何本地
状态）。所以"页面能读但一条岗位也没有"是它常见的结果——那多半意味着岗位列表是前端框架渲染
出来的，HTML 里根本没有。这类页面有两条路：在应用里开着投递台浏览器采一次（渲染升级会接管），
或者为该站写一个适配器。本脚本能帮你分辨是哪一种，但验不了渲染那条路。

## 取样本

给一套**还没有适配器**的招聘系统写适配器时，需要它的真实请求形状（参数名、编码、响应字段
名）。两种做法，优先第一种：

1. **让这个脚本先跑一遍**。有些系统的列表就在页面里（结构化数据或可读的链接），脚本直接
   就读出来了，根本不需要写适配器；
2. 读不出来时，用浏览器的开发者工具抓一次：
   `F12` → **Network** → 筛 `Fetch/XHR` → 刷新页面 → 找到返回 JSON 的那个请求 →
   看它的**请求地址、请求体、以及响应里的字段名**（JSON 的键）。
   **不要贴 Cookie 或任何登录凭据**——只要形状，不要凭据。

拿到形状之后，适配器写在 ``backend/app/services/sites/official/feeds/`` 下，
照 ``greenhouse.py`` 的样子实现 ``JobFeed`` 接口并在 ``registry.py`` 注册即可。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# 单页最多打印多少条岗位。全打出来只会把有用的部分挤出屏幕。
MAX_PRINTED_JOBS = 10


async def probe(url: str) -> int:
    """跑一遍探测与取回，返回进程退出码（0 = 读出了东西）。"""
    from app.services.sites.official.http import HttpxFeedHttp
    from app.services.sites.official.base import ProbeContext
    from app.services.sites.official.probe import probe_site
    from app.services.sites.official.registry import get_feed_registry
    from app.services.sites.official.robots import RobotsAwareHttp

    http = RobotsAwareHttp.wrap(HttpxFeedHttp())
    try:
        registry = get_feed_registry()
        print(f"已注册的适配器：{registry.supported_names()}")

        print(f"\n=== 探测 {url} ===")
        outcome = await probe_site(http, ProbeContext(careers_url=url), registry=registry)
        print(f"状态：{outcome.state}")
        print(f"说明：{outcome.detail}")
        print(f"读到的岗位数：{outcome.job_count}")
        if outcome.untried:
            # 试到上限就停了，与"这家公司不用这套系统"是两件事——脚本里也要说清楚。
            print(f"没来得及试的候选：{outcome.untried}")
        for attempt in outcome.attempts:
            print(f"   · {attempt.endpoint} → block={attempt.block!r} 岗位={attempt.job_count}")

        if outcome.hit is None:
            print("\n（没有命中，没有可取的页面。）")
            return 1

        feed = registry.resolve(outcome.hit.target.feed_key)
        print(f"\n=== 用「{feed.display_name}」取一页 ===")
        page = await feed.fetch_page(http, outcome.hit.target)
        print(f"阻断分类：{page.block or '（正常）'}")
        print(f"站点声明的总数：{page.total_hint}")
        print(f"本页岗位数：{len(page.jobs)}")
        print(f"派发出去的地址数：{len(page.next_targets)}")
        if page.detail:
            print(f"诊断：{page.detail}")
        for job in page.jobs[:MAX_PRINTED_JOBS]:
            print(
                f"   · {job.title} | {job.location or '（无地点）'} | "
                f"{job.posted_at or '（无时间）'} | 正文 {len(job.description)} 字"
            )
        if len(page.jobs) > MAX_PRINTED_JOBS:
            print(f"   …… 另有 {len(page.jobs) - MAX_PRINTED_JOBS} 条未打印")
        for target in page.next_targets[:MAX_PRINTED_JOBS]:
            print(f"   → 下一步会取：{target.endpoint}（第 {target.depth} 层）")

        return 0 if (page.jobs or page.next_targets) else 1
    finally:
        await http.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="对真实站点跑一遍官网采集的探测与取回（会联网，只读）",
    )
    parser.add_argument(
        "url",
        help="公司招聘页地址，例如 https://boards.greenhouse.io/某公司",
    )
    args = parser.parse_args()

    try:
        return asyncio.run(probe(args.url))
    except KeyboardInterrupt:  # pragma: no cover - 手工运行时才可能
        print("\n已中断。")
        return 130
    except Exception as exc:  # noqa: BLE001 - 这是一次性诊断脚本，出错要说清楚而不是抛栈
        print(f"\n出错了：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
