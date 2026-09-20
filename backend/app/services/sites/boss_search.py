"""BOSS 搜索列表、岗位详情与网络/DOM 双通道采集。"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from ...models.apply import FAILURE_NETWORK_TIMEOUT, FAILURE_SELECTOR_INVALID
from ..browser.cdp_client import CdpClient, CdpError
from .base import CollectQuery, SearchPage, SearchResult, SiteFailure
from .boss_city import CityResolutionError
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
        return f"{base}&page={max(page, 1)}"

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
    "parse_job_detail",
    "parse_search_payload",
]
