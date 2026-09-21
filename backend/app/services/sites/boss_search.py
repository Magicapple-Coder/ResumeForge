"""BOSS 搜索列表、岗位详情与网络/DOM 双通道采集。"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote

from ...models.apply import FAILURE_NETWORK_TIMEOUT, FAILURE_SELECTOR_INVALID
from ..browser.cdp_client import CdpClient, CdpError
from .base import CollectQuery, FilterResolution, SearchPage, SearchResult, SiteFailure
from .boss_city import CityResolutionError
from .boss_filters import (
    CONDITIONS_ENDPOINT,
    FILTER_BAR_SCRIPT,
    fetch_catalogue,
    parse_filter_bar,
    resolve_codes,
)
from .boss_network import DETAIL_MARKERS, SEARCH_MARKERS, api_error
from .boss_page import (
    BOSS_DISPLAY_NAME,
    SELECTOR_JOB_LINK,
    SELECTOR_SEARCH_READY,
    _SELECTORS,
    _as_payload,
    _current_url,
    _js,
    blocker_failure,
    detect_blocker,
    selector_diagnostic,
)
from .boss_text import looks_like_salary, normalize_text, split_job_fields, split_title_salary

logger = logging.getLogger(__name__)

NETWORK_RESPONSE_EVENT = "Network.responseReceived"

# 站点官方「求职类型」筛选参数（`jobType`）的编码。2026-09-20 用真实登录会话从站点自己的
# 筛选条件接口（`/wapi/zpgeek/pc/all/filter/conditions.json`）拿到，并逐档实测：三个编码各
# 跑一次搜索，返回 15 条全部为对应类型（响应 `jobType` 字段 1902→全 4、1901→全 0、
# 1903→全 6）。**官方没有「校招」档**（校招是独立专区），校招走采集后本地筛选
# （见 ``collect_filters.JOB_TYPE_EXPECTED_CODES``）。
JOB_TYPE_QUERY_CODES = {"实习": "1902", "社招": "1901"}

# 在用户当前页面上读筛选项的超时。比默认命令超时短：这只是配置界面的一次"顺手读"，
# 读不到就退回公开清单，不该让用户对着一个转圈的弹窗等半分钟。
SESSION_FETCH_TIMEOUT = 12.0
# 轮询那次 fetch 结果的间隔，以及总预算。它是页面内的一次网络请求，正常几百毫秒就回来；
# 拿不到就迅速收手——**它的失败方式是"永远不回来"，等下去没有任何意义**。
SESSION_FETCH_POLL_SECONDS = 0.4
CONDITIONS_FETCH_WAIT_SECONDS = 4.0

# 读筛选栏用的落地页。**不带任何条件**：不触发一次真实搜索，只把筛选栏渲染出来。
FILTER_BAR_URL = "https://www.zhipin.com/web/geek/jobs"
# 等筛选栏渲染出来的上限与轮询间隔。渲染是本地行为，几秒足够；等太久不如直接退回公开清单。
FILTER_BAR_WAIT_SECONDS = 8.0
FILTER_BAR_POLL_SECONDS = 0.6


def _bar_present(client: CdpClient) -> bool:
    """当前页面是不是已经有筛选栏了（有就不必再开一次页面）。读不出来按"没有"处理。"""
    try:
        return bool(parse_filter_bar(client.evaluate(FILTER_BAR_SCRIPT, timeout=5.0)))
    except Exception:  # noqa: BLE001 - 页面不在搜索页 / 读不到，都当作没有
        return False


def _session_conditions_script() -> str:
    """在**已登录**的页面上请求筛选条件接口。

    ``credentials: 'include'`` 是关键：同一个 URL，带上登录态才会返回"这个账号可见"的完整
    清单（实测差异见 ``boss_filters`` 模块说明）。

    **刻意不返回 Promise**：CDP 那边支持 ``awaitPromise``，但实测（2026-09-20）在 BOSS 的
    geek 页面（搜索结果页、岗位详情页）上这个 fetch **永远不 resolve**——await 它会把每一次
    读取都拖成一次完整超时，而失败方式看起来像"浏览器卡住了"。所以这里改成"发出去、
    把结果写进全局变量"，由调用方轮询取值：读不到就当作没读到，代价是一次短等待，
    不会挂住任何东西。落到首页之类 fetch 正常的页面上照样能用。
    """
    return "".join(
        [
            "(() => { /* rf:filter-conditions */\n",
            "  try { window.__rfFilterConditions = null; } catch (error) { return 1; }\n",
            f"  fetch({json.dumps(CONDITIONS_ENDPOINT)}, {{credentials: 'include'}})\n",
            "    .then((response) => (response.ok ? response.text() : ''))\n",
            "    .then((text) => { window.__rfFilterConditions = text || ''; })\n",
            "    .catch(() => { window.__rfFilterConditions = ''; });\n",
            "  return 1;\n",
            "})()",
        ]
    )


def _session_conditions_result_script() -> str:
    """取上面那次 fetch 的结果；还没回来时返回 ``null``。"""
    return "(() => { try { return window.__rfFilterConditions ?? null; } catch (error) { return null; } })()"


def _collect_script() -> str:
    return "".join(
        [
            "(() => { /* rf:collect */\n",
            f"  const CARD = {_js(_SELECTORS['search_card'])};\n",
            f"  const TITLE = {_js(_SELECTORS['search_title'])};\n",
            f"  const COMPANY = {_js(_SELECTORS['search_company'])};\n",
            f"  const SALARY = {_js(_SELECTORS['search_salary'])};\n",
            f"  const LOCATION = {_js(_SELECTORS['search_location'])};\n",
            f"  const LINK = {_js(_SELECTORS['search_link'])};\n",
            "  const visible = (n) => !!(n && n.getClientRects().length);\n",
            "  const pick = (root, sel) => { const n = root.querySelector(sel);\n",
            "    return n ? (n.textContent || '').trim() : ''; };\n",
            "  const items = [...document.querySelectorAll(CARD)].filter(visible).map((card) => {\n",
            "    const a = card.querySelector(LINK);\n",
            "    return {\n",
            "      title: pick(card, TITLE),\n",
            "      company: pick(card, COMPANY),\n",
            "      salary: pick(card, SALARY),\n",
            "      location: pick(card, LOCATION),\n",
            "      url: a ? a.href : '',\n",
            "    };\n",
            "  }).filter((item) => item.title && (!item.url || item.url.includes('/job_detail/')));\n",
            "  const next = document.querySelector(" + _js(_SELECTORS["search_next"]) + ");\n",
            "  return JSON.stringify({\n",
            "    url: location.href,\n",
            "    title: document.title || '',\n",
            "    items,\n",
            "    has_next: !!(next && !next.classList.contains('disabled')),\n",
            "  });\n",
            "})()",
        ]
    )


def _collect_links_script() -> str:
    return "".join(
        [
            "(() => { /* rf:collect-links */\n",
            f"  const LINK = {_js(SELECTOR_JOB_LINK)};\n",
            "  const scope = document.querySelector('.job-list-container, .search-job-result, main') || document;\n",
            "  const seen = new Set();\n",
            "  const items = [];\n",
            "  for (const a of scope.querySelectorAll(LINK)) {\n",
            "    const href = a.href || '';\n",
            "    const excluded = a.closest('.recommend-job-list, .recommend-list, aside, [class*=recommend]');\n",
            "    if (!href || seen.has(href) || excluded || !a.getClientRects().length) continue;\n",
            "    seen.add(href);\n",
            "    const title = (a.getAttribute('aria-label') || a.getAttribute('title') || a.textContent || '').trim();\n",
            "    if (!title) continue;\n",
            "    items.push({ title, company: '',\n",
            "      salary: '', location: '', url: href });\n",
            "  }\n",
            "  const next = document.querySelector(" + _js(_SELECTORS["search_next"]) + ");\n",
            "  return JSON.stringify({\n",
            "    url: location.href,\n",
            "    title: document.title || '',\n",
            "    items,\n",
            "    has_next: !!(next && !next.classList.contains('disabled')),\n",
            "  });\n",
            "})()",
        ]
    )


def _detail_script() -> str:
    return "".join(
        [
            "(() => { /* rf:detail */\n",
            f"  const TITLE = {_js(_SELECTORS['search_title'])};\n",
            f"  const COMPANY = {_js(_SELECTORS['search_company'])};\n",
            f"  const DESC = {_js(_SELECTORS['job_description'])};\n",
            f"  const REQ = {_js(_SELECTORS['job_requirements'])};\n",
            "  const root = document.querySelector('.job-detail-box, .job-detail-body, main') || document;\n",
            "  const pick = (sel) => { const n = root.querySelector(sel);\n",
            "    return n ? (n.textContent || '').trim() : ''; };\n",
            "  const byHeading = (words) => {\n",
            "    for (const section of root.querySelectorAll('section, .job-detail-section, .job-sec')) {\n",
            "      const heading = section.querySelector('h1,h2,h3,h4,.title,.section-title');\n",
            "      const label = heading ? (heading.textContent || '').trim() : '';\n",
            "      if (words.some((word) => label.includes(word))) return (section.innerText || '').trim();\n",
            "    } return ''; };\n",
            "  return JSON.stringify({\n",
            "    url: location.href,\n",
            "    title: document.title || '',\n",
            "    job_title: pick(TITLE),\n",
            "    company: pick(COMPANY),\n",
            "    description: pick(DESC) || byHeading(['职位描述', '岗位职责', '工作内容']),\n",
            "    requirements: pick(REQ) || byHeading(['任职要求', '职位要求', '岗位要求']),\n",
            "  });\n",
            "})()",
        ]
    )


def parse_search_payload(
    payload: dict[str, Any], page: int, unmapped_conditions: list[str] | None = None
) -> SearchPage:
    if not isinstance(payload, dict):
        raise SiteFailure(FAILURE_SELECTOR_INVALID, "搜索结果返回了无法解析的内容")
    results: list[SearchResult] = []
    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            title, title_salary = split_title_salary(item.get("title", ""))
            if not title:
                continue
            salary = normalize_text(item.get("salary", ""))
            if not looks_like_salary(salary):
                salary = title_salary
            results.append(
                SearchResult(
                    title=title,
                    company=normalize_text(item.get("company", "")),
                    location=normalize_text(item.get("location", "")),
                    salary=salary,
                    url=str(item.get("url", "")),
                    source=BOSS_DISPLAY_NAME,
                )
            )
    return SearchPage(
        results=results,
        page=page,
        has_next=bool(payload.get("has_next")),
        unmapped_conditions=list(unmapped_conditions or []),
    )


def parse_job_detail(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SiteFailure(FAILURE_SELECTOR_INVALID, "岗位详情返回了无法解析的内容")
    dom_requirements = normalize_text(payload.get("requirements", ""))
    sections = split_job_fields(payload.get("description", ""))
    return {
        "job_title": normalize_text(payload.get("job_title", "")),
        "company": normalize_text(payload.get("company", "")),
        "description": sections.description,
        "requirements": dom_requirements or sections.requirements,
        # 福利待遇 / 公司介绍这类第三段（对应 ``Job.additional_info``）。
        "additional_info": sections.additional,
        "url": str(payload.get("url", "")),
    }


def _with_response_bodies(client: CdpClient, events: list[dict[str, Any]]) -> list[Any]:
    from ..browser.network_capture import MAX_PARSED_RESPONSES, collect_bodies, response_urls

    wanted = {
        url
        for markers in (SEARCH_MARKERS, DETAIL_MARKERS)
        for url in response_urls(events, markers=markers)
    }
    body_events: list[dict[str, Any]] = []
    fetched: set[str] = set()
    for event in events:
        if len(body_events) >= MAX_PARSED_RESPONSES:
            break
        if event.get("method") != NETWORK_RESPONSE_EVENT:
            continue
        params = event.get("params")
        if not isinstance(params, dict):
            continue
        request_id = str(params.get("requestId") or "")
        if not request_id or request_id in fetched:
            continue
        response = params.get("response")
        url = str(response.get("url") or "") if isinstance(response, dict) else ""
        if url not in wanted:
            continue
        try:
            result = client.send("Network.getResponseBody", {"requestId": request_id})
        except CdpError:
            logger.debug("取响应体失败（可能已被回收）：%s", url)
            continue
        fetched.add(request_id)
        body_events.append(
            {"method": "Network.getResponseBody", "requestId": request_id, "result": result}
        )
    if not body_events:
        return []
    return collect_bodies([*events, *body_events])


def _raise_api_error(responses: list[Any], markers: tuple[str, ...], operation: str) -> None:
    for response in responses:
        url = str(getattr(response, "url", "") or "")
        if not any(marker and marker in url for marker in markers):
            continue
        error = api_error(getattr(response, "body", None))
        if error is None:
            continue
        code, message = error
        suffix = f"：{message}" if message else ""
        raise SiteFailure(
            FAILURE_SELECTOR_INVALID,
            f"BOSS {operation}接口返回错误 code={code}{suffix}。请检查筛选条件后重试",
            url=url,
        )


class BossSearchMixin:
    """BOSS 搜索与详情采集实现。"""

    def build_search_url(self, query: CollectQuery, page: int) -> str:
        keyword = quote((query.keywords[0] if query.keywords else "").strip(), safe="")
        try:
            city = self._city_resolver.resolve(query.city or "")
        except CityResolutionError as exc:
            category = (
                FAILURE_NETWORK_TIMEOUT
                if str(exc).startswith("无法获取 BOSS 城市清单")
                else FAILURE_SELECTOR_INVALID
            )
            raise SiteFailure(category, f"城市筛选无法生效：{exc}") from exc
        base = f"https://www.zhipin.com/web/geek/job?query={keyword}&city={city}"
        # 岗位类型里**能映射到站点筛选**的（实习/社招）直接带上官方编码，让站点在
        # 接口侧就筛掉，省翻页；校招没有官方参数，由采集后的本地筛选负责（如实记账）。
        job_type_param = JOB_TYPE_QUERY_CODES.get((query.job_type or "").strip())
        # 用户在「站点筛选」里明确选了求职类型时，**以他选的那一项为准**：否则同一个
        # ``jobType`` 参数会在地址里出现两次（一个来自下面的旧映射、一个来自他刚选的），
        # 站点取哪一个不确定——那正是"我明明选了实习却混进全职"的成因。
        if job_type_param and "jobType" not in query.filters:
            base = f"{base}&jobType={job_type_param}"
        # 站点筛选栏选中的条件。**编码已经过校验**（见 prepare_collect_filters），这里只负责
        # 拼进去；参数名一律转义，免得站点改个键名就把查询串拼坏。
        for name, code in sorted(query.filters.items()):
            if name and code:
                base = f"{base}&{quote(str(name), safe='')}={quote(str(code), safe='')}"
        return f"{base}&page={max(page, 1)}"

    # ===== 站点侧筛选项 =====
    #
    # 两条读取路径，优先"用户自己看到的那份"：
    # - **页面上直接读**（``FILTER_BAR_SCRIPT``）：筛选栏是站点渲染出来的，正是用户看到的选项；
    # - **带登录态的接口请求**（``_session_conditions_script``）：在已登录页面上发一次 fetch，
    #   拿到**这个账号可见**的清单。这一条是必需的——「求职类型」的选项因人而异
    #   （2026-09-20 实测：登录账号能看到「实习」，未登录看不到），写死一份就等于替所有
    #   用户决定了他们能选什么。
    # 浏览器没启动时退回免登录的公开清单（``boss_filters.fetch_catalogue`` 自己会退）。

    def _read_session_filters(self, client: CdpClient) -> tuple[dict[str, Any], Any]:
        """在用户当前的页面上读筛选项。**三条路各读各的**，谁成功用谁，互不牵连。

        - 页面筛选栏（``FILTER_BAR_SCRIPT``）：搜索页上一定有，且是"这个账号能看到"的那份；
        - 带登录态的接口请求（``_session_conditions_script``）：任何 zhipin 页面上都能发，
          但结果要靠轮询取（见那个脚本的说明——它的 Promise 在 geek 页面上不 resolve）。
        """
        bar: Any = None
        try:
            bar = client.evaluate(FILTER_BAR_SCRIPT, timeout=SESSION_FETCH_TIMEOUT)
        except Exception:  # noqa: BLE001 - 页面不在搜索结果页时本来就读不到筛选栏
            logger.debug("读取 BOSS 页面筛选栏失败（页面可能不在搜索结果页）", exc_info=True)
        if parse_filter_bar(bar):
            # **页面上已经有清单了，就不再发那次接口请求。** 筛选栏是更完整、更直接的那一份
            # （它连接口不给的三级行业都有），而且**那次 fetch 在 geek 页面上根本不 resolve**
            # ——继续等它只会白等满一个轮询预算。
            return {}, bar

        values: dict[str, Any] = {}
        try:
            client.evaluate(_session_conditions_script(), timeout=SESSION_FETCH_TIMEOUT)
            body = self._await_conditions(client)
            if isinstance(body, str) and body.strip():
                values[CONDITIONS_ENDPOINT] = body
        except Exception:  # noqa: BLE001 - 读不到就走公开清单，不打断界面
            logger.debug("带登录态读取 BOSS 筛选条件失败，将退回公开清单", exc_info=True)
        return values, bar

    def _await_conditions(self, client: CdpClient) -> Any:
        """短轮询取那次 fetch 的结果；超时就放弃（**不等满一个命令超时**）。"""
        deadline = time.monotonic() + CONDITIONS_FETCH_WAIT_SECONDS
        while time.monotonic() < deadline:
            try:
                result = client.evaluate(_session_conditions_result_script(), timeout=5.0)
            except Exception:  # noqa: BLE001 - 取不到就是"没读到"
                return None
            if result is not None:
                return result
            time.sleep(SESSION_FETCH_POLL_SECONDS)
        return None

    def fetch_filter_options(self, client: CdpClient | None = None) -> tuple[Any, ...]:
        """当前筛选清单。**有浏览器就优先读页面上的那份**（含账号可见的完整选项）。"""
        fetcher = getattr(self, "_filter_fetcher", None)
        timeout = getattr(self, "_filter_timeout", 6.0)
        if client is not None:
            values, bar = self._read_session_filters(client)
            if values or bar:
                return fetch_catalogue(
                    fetcher=fetcher, timeout=timeout, session_values=values, bar_payload=bar
                )
        return fetch_catalogue(fetcher=fetcher, timeout=timeout)

    def prepare_collect_filters(
        self, selected: Mapping[str, str] | None, client: CdpClient | None = None
    ) -> FilterResolution:
        """解析站点筛选条件。**只在必要时才多走一次页面**。

        采集开始那一刻，浏览器通常停在上一轮留下的岗位上（岗位详情页）——那上面没有筛选栏。
        免登录的公开清单里又没有「求职类型：实习」这类**只对某些账号可见**的选项，于是用户
        明明选了、却会被判成"没能生效"。

        所以：先用手头能读到的清单校验一遍；**只有确实有没校验过的项、且浏览器在的时候**，
        才去搜索页读一次筛选栏再校验一遍。没配站点筛选、或者选的项公开清单就能确认时，
        一次多余的页面都不会开。
        """
        if not selected:
            return FilterResolution()
        resolved = resolve_codes(selected, self.fetch_filter_options(client))
        # 还有没校验过的项、当前页面又没有筛选栏 → 去搜索页读一次再校验。
        if resolved.unapplied and client is not None and not _bar_present(client):
            if self._load_filter_bar(client):
                resolved = resolve_codes(selected, self.fetch_filter_options(client))
        if resolved.unapplied:
            logger.warning(
                "这些筛选条件本次没能生效（编码不在站点当前清单里）：%s", resolved.unapplied
            )
        return FilterResolution(
            params=resolved.params, applied=resolved.applied, unapplied=resolved.unapplied
        )

    def _load_filter_bar(self, client: CdpClient) -> bool:
        """去搜索页把筛选栏读出来。**这是唯一一次为读选项而开的页面**，读不到就作罢。"""
        try:
            client.navigate(FILTER_BAR_URL)
        except Exception:  # noqa: BLE001 - 开不了就当没读到，后面照样能采
            logger.debug("为读取筛选栏打开搜索页失败", exc_info=True)
            return False
        deadline = time.monotonic() + FILTER_BAR_WAIT_SECONDS
        while time.monotonic() < deadline:
            time.sleep(FILTER_BAR_POLL_SECONDS)
            try:
                payload = client.evaluate(FILTER_BAR_SCRIPT, timeout=5.0)
            except Exception:  # noqa: BLE001 - 页面还在加载
                continue
            if parse_filter_bar(payload):
                return True
        logger.info("搜索页上没能读到筛选栏，本次按公开清单校验筛选条件")
        return False

    def unmapped_conditions(self, query: CollectQuery) -> list[str]:
        return []

    def _capture_network(
        self, client: CdpClient, action: Callable[[], Any]
    ) -> tuple[list[Any], Any]:
        starter = getattr(client, "start_event_capture", None)
        drain = getattr(client, "drain_events", None)
        if starter is None or drain is None:
            return [], action()
        stop = getattr(client, "stop_event_capture", None)
        starter([NETWORK_RESPONSE_EVENT])
        try:
            result = action()
            events = list(drain())
        finally:
            if stop is not None:
                stop()
        try:
            return _with_response_bodies(client, events), result
        except Exception:  # noqa: BLE001 - 网络快路失败不影响 DOM 兜底
            logger.debug("解析网络响应时出错，将退回 DOM 解析", exc_info=True)
            return [], result

    def collect_search(self, client: CdpClient, query: CollectQuery, page: int) -> SearchPage:
        target = self.build_search_url(query, page)
        previous = _current_url(client)
        outcome: dict[str, Any] = {"state": {}, "failure": None}

        def _load() -> dict[str, Any]:
            client.navigate(target)
            try:
                outcome["state"] = self._await_ready(
                    client,
                    selector=SELECTOR_SEARCH_READY,
                    expected="岗位卡片（如 li.job-card-box / .job-card-wrapper，或岗位详情链接）",
                    allow_empty=True,
                    target_url=target,
                    previous_url=previous,
                )
            except SiteFailure as exc:
                outcome["failure"] = exc
            return outcome["state"]

        responses, state = self._capture_network(client, _load)
        from ..browser.network_capture import first_json_with
        from .boss_network import looks_like_search, parse_search_response, search_has_more

        network_items = first_json_with(responses, looks_like_search)
        parsed = parse_search_response(network_items) if network_items is not None else None
        if parsed:
            has_more = search_has_more(network_items)
            return SearchPage(
                results=[
                    SearchResult(
                        title=item["title"],
                        company=item["company"],
                        location=item["location"],
                        salary=item["salary"],
                        url=item["url"],
                        source=BOSS_DISPLAY_NAME,
                        extra=item.get("extra") or {},
                    )
                    for item in parsed
                ],
                page=page,
                has_next=has_more if has_more is not None else bool(state.get("has_next")),
                unmapped_conditions=self.unmapped_conditions(query),
            )
        _raise_api_error(responses, SEARCH_MARKERS, "岗位搜索")
        failure = outcome["failure"]
        if failure is not None:
            raise failure
        if int(state.get("matched", 0) or 0) <= 0:
            return SearchPage(
                results=[],
                page=page,
                has_next=False,
                unmapped_conditions=self.unmapped_conditions(query),
            )
        payload = _as_payload(client.evaluate(_collect_script()))
        payload = payload if isinstance(payload, dict) else {}
        blocker = detect_blocker(payload)
        if blocker is not None:
            raise blocker_failure(blocker, payload)
        dom_page = parse_search_payload(payload, page, self.unmapped_conditions(query))
        if dom_page.results:
            return dom_page
        link_payload = _as_payload(client.evaluate(_collect_links_script()))
        link_payload = link_payload if isinstance(link_payload, dict) else {}
        link_items = link_payload.get("items")
        if isinstance(link_items, list) and link_items:
            return parse_search_payload(link_payload, page, self.unmapped_conditions(query))
        raise SiteFailure(
            FAILURE_SELECTOR_INVALID,
            selector_diagnostic(payload, "岗位卡片（如 li.job-card-box / .job-card-wrapper）"),
            url=str(payload.get("url") or ""),
            title=str(payload.get("title") or ""),
        )

    def fetch_job_detail(self, client: CdpClient, url: str) -> dict[str, Any]:
        previous = _current_url(client)
        outcome: dict[str, Any] = {"state": {}, "failure": None}

        def _load() -> dict[str, Any]:
            client.navigate(url)
            try:
                outcome["state"] = self._await_ready(
                    client,
                    selector=_SELECTORS["detail_ready"],
                    expected="岗位详情内容（如 .job-sec-text）",
                    allow_empty=False,
                    target_url=url,
                    previous_url=previous,
                )
            except SiteFailure as exc:
                outcome["failure"] = exc
            return outcome["state"]

        responses, _ = self._capture_network(client, _load)
        from ..browser.network_capture import first_json_with
        from .boss_network import looks_like_detail, parse_detail_response

        network_detail = first_json_with(responses, looks_like_detail)
        if network_detail is not None:
            parsed = parse_detail_response(network_detail)
            if parsed is not None:
                parsed["url"] = parsed.get("url") or url
                return parsed
        _raise_api_error(responses, DETAIL_MARKERS, "岗位详情")
        if outcome["failure"] is not None:
            raise outcome["failure"]
        payload = _as_payload(client.evaluate(_detail_script()))
        parsed = parse_job_detail(payload if isinstance(payload, dict) else {})
        if parsed.get("description") or parsed.get("requirements"):
            return parsed
        state = payload if isinstance(payload, dict) else {}
        raise SiteFailure(
            FAILURE_SELECTOR_INVALID,
            selector_diagnostic(state, "岗位详情正文（职位描述 / 任职要求）"),
            url=str(state.get("url") or url),
            title=str(state.get("title") or ""),
        )


__all__ = [
    "BossSearchMixin",
    "NETWORK_RESPONSE_EVENT",
    "SESSION_FETCH_TIMEOUT",
    "_session_conditions_script",
    "parse_job_detail",
    "parse_search_payload",
]
