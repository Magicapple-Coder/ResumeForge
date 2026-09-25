"""官网采集接口。

守一条对前端影响很大的语义：**robots 拒绝、被阻断、未识别都不是 HTTP 错误**——
它们各自是一条带可读结论的运行记录，返回 200。用 4xx/5xx 表达它们，前端就只能弹一句
"请求失败"，而这正是这个功能最不该给出的反馈。
"""
from __future__ import annotations

import json
import time

import pytest

from app.models.material import CandidateJob
from app.models.official import BLOCK_NONE, RUN_DONE, OfficialCollectRun
from app.models.profile import utcnow
from app.services.sites.official.base import FeedHttp, FetchResult

BOARD_PREFIX = "https://boards-api.greenhouse.io"
ROBOTS_URL = "https://boards.greenhouse.io/robots.txt"

ALLOW_ALL_ROBOTS = FetchResult(
    block="", status_code=200, text="User-agent: *\nDisallow:\n", headers={}
)
DISALLOW_ALL_ROBOTS = FetchResult(
    block="", status_code=200, text="User-agent: *\nDisallow: /\n", headers={}
)


class RoutingHttp(FeedHttp):
    def __init__(self, routes: dict[str, FetchResult]):
        self._routes = routes
        self.calls: list[str] = []

    async def request(self, method, url, *, params=None, json_body=None, headers=None, max_bytes=None):
        del method, params, json_body, headers, max_bytes
        self.calls.append(url)
        for prefix, result in self._routes.items():
            if url.startswith(prefix):
                return result
        return FetchResult(block="not_found", status_code=404)


def _board(jobs: list[dict], total: int | None = None) -> FetchResult:
    body: dict = {"jobs": jobs}
    if total is not None:
        body["meta"] = {"total": total}
    return FetchResult(block="", status_code=200, text=json.dumps(body), headers={})


def _job(index: int) -> dict:
    return {
        "id": index,
        "title": f"岗位 {index}",
        "company_name": "示例公司",
        "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{index}",
        "content": f"&lt;p&gt;第 {index} 个岗位的职位描述&lt;/p&gt;",
    }


@pytest.fixture
def fake_http(monkeypatch):
    """替换接口层构造的传输实现。

    接口层自己 new 传输对象（业务代码不该为了测试而接受注入），所以在这里替换掉工厂——
    换的是**边界**，被测的编排与对账逻辑一行都没打桩。
    """
    http = RoutingHttp({ROBOTS_URL: ALLOW_ALL_ROBOTS, BOARD_PREFIX: _board([_job(1)], total=1)})

    # 工厂现在返回的是**传输对象本身**（调用方自己 aclose），所以一行 lambda 就够。
    monkeypatch.setattr(
        "app.services.sites.official.service.default_http_factory", lambda db=None: http
    )
    return http


def _wait_for_run(client, run_id: int, timeout: float = 10.0) -> dict:
    """等后台采集收尾，返回最终的运行记录。

    ``/collect`` 现在**立刻返回**、实际采集在后台跑（多页站点要几十次请求加限速等待，
    同步走完会把 HTTP 请求挂住）。所以断言最终结论之前必须等——**真实前端也是这么轮询的**，
    这里用同样的方式，顺带把轮询这条路径也覆盖到。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/official/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.02)
    raise AssertionError(f"采集没有在 {timeout}s 内结束")


def _collect_and_wait(client, site_id: int) -> dict:
    started = client.post(f"/api/official/sites/{site_id}/collect").json()
    return _wait_for_run(client, started["id"])


def _add_site(client, **overrides) -> dict:
    payload = {
        "company": "示例公司",
        "careers_url": "https://boards.greenhouse.io/acme",
        **overrides,
    }
    response = client.post("/api/official/sites", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ===== 源的建立与探测 =====


def test_list_sites_is_empty_initially(client):
    response = client.get("/api/official/sites")
    assert response.status_code == 200
    assert response.json() == []


def test_create_site_probes_and_reports_the_recognised_system(client, fake_http):
    body = _add_site(client)

    assert body["state"] == "hit"
    site = body["site"]
    assert site["source_kind"] == "greenhouse"
    # 系统展示名要给出来：前端不该自己维护一份 key → 名字的映射表。
    assert site["source_label"] == "Greenhouse"
    assert site["confidence"] == "high"
    assert site["confidence_label"]
    assert site["can_collect"] is True
    assert "acme" in site["probe_evidence"]


def test_create_site_without_any_url_is_400(client, fake_http):
    response = client.post("/api/official/sites", json={"company": "示例公司"})
    assert response.status_code == 400
    assert "地址" in response.json()["detail"]


def test_create_site_duplicate_is_400(client, fake_http):
    _add_site(client)
    response = client.post(
        "/api/official/sites",
        json={"company": "示例公司", "careers_url": "https://boards.greenhouse.io/acme"},
    )
    assert response.status_code == 400
    assert "已经在列表里" in response.json()["detail"]


def test_create_site_reports_a_blocked_probe_as_a_state_not_an_error(client, monkeypatch):
    """探测被阻断时**不是** HTTP 错误：用户要看到"没看到内容"，而不是"请求失败"。"""
    http = RoutingHttp({})  # 一切皆 404，但 robots 会读到

    # 工厂现在返回的是**传输对象本身**（调用方自己 aclose），所以一行 lambda 就够。
    monkeypatch.setattr(
        "app.services.sites.official.service.default_http_factory", lambda db=None: http
    )

    body = _add_site(client)

    assert body["state"] == "not_found"
    assert body["state_label"]
    # 试过哪些端点要如实给出来——这是用户唯一能拿去反馈的东西。
    assert body["attempts"], "探测失败时必须给出尝试过哪些端点"


def test_reprobe_is_idempotent(client, fake_http):
    site_id = _add_site(client)["site"]["id"]
    response = client.post(f"/api/official/sites/{site_id}/probe")
    assert response.status_code == 200
    assert response.json()["state"] == "hit"


def test_delete_site_returns_204_and_removes_it(client, fake_http):
    site_id = _add_site(client)["site"]["id"]

    assert client.delete(f"/api/official/sites/{site_id}").status_code == 204
    assert client.get("/api/official/sites").json() == []


def test_missing_site_is_404_not_400(client, fake_http):
    """404 与 400 分开：前端据此区分"列表该刷新了"和"输入该改了"。"""
    assert client.post("/api/official/sites/9999/probe").status_code == 404
    assert client.post("/api/official/sites/9999/collect").status_code == 404
    assert client.get("/api/official/runs/9999").status_code == 404


# ===== 采集 =====


def test_collect_returns_the_run_with_a_hard_verdict(client, fake_http):
    site_id = _add_site(client)["site"]["id"]

    started = client.post(f"/api/official/sites/{site_id}/collect")
    assert started.status_code == 200, "起任务本身必须立刻成功返回"
    run = _wait_for_run(client, started.json()["id"])
    assert run["verdict"] == "complete"
    assert run["verdict_label"]
    assert run["collected"] == 1
    assert run["total_hint"] == 1
    assert run["status_label"]


def test_collect_stages_candidates(client, fake_http, db_session):
    site_id = _add_site(client)["site"]["id"]
    _collect_and_wait(client, site_id)

    # 后台任务用的是**另一个会话**，这里要让当前会话丢掉缓存的快照才看得到它的写入。
    db_session.expire_all()
    assert db_session.query(CandidateJob).count() == 1


def test_collect_reports_the_gap_when_the_site_declares_more(client, monkeypatch, fake_http):
    fake_http._routes[BOARD_PREFIX] = _board([_job(1)], total=4)  # noqa: SLF001 - 测试内部
    site_id = _add_site(client)["site"]["id"]

    run = _collect_and_wait(client, site_id)

    assert run["verdict"] == "incomplete"
    assert run["missing"] == 3


def test_robots_refusal_is_a_200_run_with_a_readable_headline(client, monkeypatch):
    """被 robots 拒绝：**200 + 一条记录**，不是错误码。"""
    http = RoutingHttp({ROBOTS_URL: DISALLOW_ALL_ROBOTS, BOARD_PREFIX: _board([_job(1)])})

    # 工厂现在返回的是**传输对象本身**（调用方自己 aclose），所以一行 lambda 就够。
    monkeypatch.setattr(
        "app.services.sites.official.service.default_http_factory", lambda db=None: http
    )

    site_id = _add_site(client)["site"]["id"]
    started = client.post(f"/api/official/sites/{site_id}/collect")
    assert started.status_code == 200, "起任务本身必须立刻成功返回"
    run = _wait_for_run(client, started.json()["id"])
    assert run["verdict"] == "unknown", "一条都没抓到，绝不能报已确认为全量"
    assert "不允许采集" in run["headline"]
    # 分类的中文一并给出，前端不需要自己维护枚举映射。
    assert run["block_labels"] and run["block_labels"][0]


def test_collect_without_a_recognised_system_is_400(client, monkeypatch):
    """没识别出系统时采集 = 用户操作有误，这才是 400。"""
    http = RoutingHttp({})  # 全部 404 → 识别不出来

    # 工厂现在返回的是**传输对象本身**（调用方自己 aclose），所以一行 lambda 就够。
    monkeypatch.setattr(
        "app.services.sites.official.service.default_http_factory", lambda db=None: http
    )
    site_id = _add_site(client)["site"]["id"]

    response = client.post(f"/api/official/sites/{site_id}/collect")

    assert response.status_code == 400
    assert "还没识别出" in response.json()["detail"]


# ===== 运行记录 =====


def test_run_detail_carries_the_layer_evidence(client, fake_http):
    site_id = _add_site(client)["site"]["id"]
    run_id = _collect_and_wait(client, site_id)["id"]

    detail = client.get(f"/api/official/runs/{run_id}").json()

    assert detail["reconcile_detail"]["termination"]["state"] == "exhausted"
    assert any(layer["layer"] == "total" for layer in detail["reconcile_detail"]["layers"])


def test_runs_can_be_filtered_by_site(client, fake_http):
    first = _add_site(client)["site"]["id"]
    second = _add_site(client, company="另一家公司")["site"]["id"]
    _collect_and_wait(client, first)
    _collect_and_wait(client, second)

    runs = client.get("/api/official/runs", params={"site_id": first}).json()

    assert len(runs) == 1
    assert runs[0]["site_id"] == first
    assert runs[0]["site_company"] == "示例公司"


# ===== 存活校验 =====


def test_verify_without_candidates_is_a_user_error(client, fake_http):
    """没有待核实地址时点核实 = 用户操作有误，这才是 400。"""
    site_id = _add_site(client)["site"]["id"]
    run_id = _collect_and_wait(client, site_id)["id"]

    response = client.post(f"/api/official/runs/{run_id}/verify")

    assert response.status_code == 400
    assert "没有待核实" in response.json()["detail"]


def test_verify_on_a_missing_run_is_404(client, fake_http):
    assert client.post("/api/official/runs/9999/verify").status_code == 404


def test_verify_upgrades_the_verdict_and_records_the_details(client, monkeypatch):
    """完整链路：站点地图里差一个 → 核实它仍在招 → 结论升级为"已确认不全"。"""
    sitemap_url = "https://boards.greenhouse.io/sitemap.xml"
    posting = {"@type": "JobPosting", "title": "仍在招的岗位", "description": "<p>职责</p>"}
    live_page = FetchResult(
        block=BLOCK_NONE,
        status_code=200,
        text=(
            "<html><head>"
            f'<script type="application/ld+json">{json.dumps(posting, ensure_ascii=False)}</script>'
            "</head><body></body></html>"
        ),
        headers={},
    )
    routes = {
        "https://boards.greenhouse.io/robots.txt": FetchResult(
            block=BLOCK_NONE,
            status_code=200,
            text=f"User-agent: *\nDisallow:\nSitemap: {sitemap_url}\n",
            headers={},
        ),
        sitemap_url: FetchResult(
            block=BLOCK_NONE,
            status_code=200,
            text=(
                "<urlset>"
                "<url><loc>https://boards.greenhouse.io/acme/jobs/1</loc></url>"
                "<url><loc>https://boards.greenhouse.io/acme/jobs/2</loc></url>"
                "</urlset>"
            ),
            headers={},
        ),
        BOARD_PREFIX: _board([_job(1)], total=1),
        "https://boards.greenhouse.io/acme/jobs/2": live_page,
    }
    http = RoutingHttp(routes)

    # 工厂现在返回的是**传输对象本身**（调用方自己 aclose），所以一行 lambda 就够。
    monkeypatch.setattr(
        "app.services.sites.official.service.default_http_factory", lambda db=None: http
    )

    site_id = _add_site(client)["site"]["id"]
    run = _collect_and_wait(client, site_id)
    assert run["verdict"] == "unknown"

    verified = client.post(f"/api/official/runs/{run['id']}/verify")

    assert verified.status_code == 200
    body = verified.json()
    assert body["verdict"] == "incomplete"
    assert body["missing"] == 1
    entries = body["reconcile_detail"]["verifications"]
    assert entries[0]["state"] == "live"
    assert entries[0]["label"]


def test_run_detail_carries_the_trend_signal(client, fake_http, db_session):
    """报告里要能看到"这次与近期相比算不算异常"——它治的是单次对账看不见的病。"""
    site_id = _add_site(client)["site"]["id"]
    # 这家公司此前稳定在 40 条左右。
    for count in (40, 42, 38):
        db_session.add(
            OfficialCollectRun(
                site_id=site_id,
                status=RUN_DONE,
                started_at=utcnow(),
                collected=count,
                blocks=[BLOCK_NONE],
            )
        )
    db_session.commit()

    run = _collect_and_wait(client, site_id)  # 这次只采到 1 条
    detail = client.get(f"/api/official/runs/{run['id']}").json()

    assert detail["trend"]["state"] == "dropped"
    assert detail["trend"]["baseline"] == 40
    assert detail["trend"]["latest"] == 1
    assert detail["trend"]["label"]
    # **它不是一条对账依据**：措辞里必须说清这不一定是漏抓。
    assert "不一定是漏抓" in detail["trend"]["detail"]


def test_run_detail_says_history_is_insufficient_for_a_new_source(client, fake_http):
    site_id = _add_site(client)["site"]["id"]
    run = _collect_and_wait(client, site_id)

    detail = client.get(f"/api/official/runs/{run['id']}").json()

    assert detail["trend"]["state"] == "insufficient"
    assert detail["trend"]["baseline"] is None


def test_verify_run_also_carries_the_trend_signal(client, fake_http, db_session):
    """两个出口都要带趋势——报告页在核实之后会重新取一次，漏了就会在那一瞬间消失。"""
    site_id = _add_site(client)["site"]["id"]
    for count in (40, 42, 38):
        db_session.add(
            OfficialCollectRun(
                site_id=site_id, status=RUN_DONE, started_at=utcnow(),
                collected=count, blocks=[BLOCK_NONE],
            )
        )
    db_session.commit()
    run_id = _collect_and_wait(client, site_id)["id"]

    detail = client.get(f"/api/official/runs/{run_id}").json()

    assert detail["trend"] is not None, "报告出口漏了趋势字段"


def test_site_list_carries_the_latest_verdict(client, fake_http):
    site_id = _add_site(client)["site"]["id"]
    _collect_and_wait(client, site_id)

    site = client.get("/api/official/sites").json()[0]

    assert site["latest_verdict"] == "complete"
    assert site["latest_verdict_label"]
    assert site["latest_headline"]


# ===== 公司发现 =====


def _stub_search(monkeypatch, results: list[dict[str, str]]) -> list[str]:
    """替换发现用的聚合搜索，返回调用记录（查询词）。

    替换的是 ``discovery.aggregate_search`` 这个**模块级接缝**，而不是更深一层的搜索引擎：
    真实聚合还会做一轮相关性过滤，用例里的假结果很容易被它整批滤掉，那样测的就变成了过滤
    规则而不是本次要测的接线。（这也是它不写在参数默认值里的原因——绑定了就替换不动。）
    """
    calls: list[str] = []

    async def search(query: str, config):
        del config
        calls.append(query)
        return list(results)

    monkeypatch.setattr("app.services.sites.official.discovery.aggregate_search", search)
    return calls


def test_discover_returns_candidates_with_the_field_to_fill(client, monkeypatch):
    """候选要连"该填进哪个字段"一起给前端。

    让前端按地址自己再判一次，就会出现"清单里认成招聘页、提交后却被当成首页"这类两边判据
    不一致的现象，而且只有用户会撞上。
    """
    _stub_search(
        monkeypatch,
        [
            {"title": "示例科技招聘", "url": "https://careers.example.com/jobs", "snippet": ""},
            {"title": "另一家公司", "url": "https://www.other.com/about", "snippet": ""},
        ],
    )

    body = client.post("/api/official/discover", json={"keywords": "算法工程师", "city": "北京"}).json()

    by_host = {item["host"]: item for item in body["candidates"]}
    assert by_host["careers.example.com"]["target_field"] == "careers_url"
    assert by_host["careers.example.com"]["company"] == "示例科技"
    assert by_host["www.other.com"]["target_field"] == "homepage_url"
    assert len(body["queries"]) == 2
    assert body["history_id"] is not None

    history = client.get("/api/official/discover/history").json()
    assert len(history) == 1
    assert history[0]["id"] == body["history_id"]
    assert history[0]["keywords"] == "算法工程师"
    assert history[0]["city"] == "北京"
    assert history[0]["candidates"] == body["candidates"]


def test_discover_history_keeps_empty_searches_and_newest_first(client, monkeypatch):
    """空关键词也要留下记录；历史顺序按创建时间与 id 稳定地新到旧。"""
    calls = _stub_search(monkeypatch, [])

    first = client.post("/api/official/discover", json={"keywords": "   "}).json()
    second = client.post("/api/official/discover", json={"keywords": "算法"}).json()

    assert calls == ["算法 招聘", "算法 加入我们 招聘"]
    history = client.get("/api/official/discover/history?limit=2").json()
    assert [item["id"] for item in history] == [second["history_id"], first["history_id"]]
    assert history[1]["candidate_count"] == 0


def test_discover_detail_says_these_are_leads(client, monkeypatch):
    """**这句话必须原样传到界面上**：用户把线索当完整名单，就会漏掉一大批公司而不自知。"""
    _stub_search(
        monkeypatch,
        [{"title": "示例科技招聘", "url": "https://careers.example.com/jobs", "snippet": ""}],
    )

    body = client.post("/api/official/discover", json={"keywords": "算法"}).json()

    assert "线索" in body["detail"]
    assert "不代表在招的公司就这些" in body["detail"]


def test_discover_honours_the_configured_search_settings(client, monkeypatch, db_session):
    """走的是用户在「联网搜索设置」里的那份配置，不另起一套。"""
    from app.schemas.setting import SearchConfig
    from app.services import settings_service

    settings_service.save_search_config(db_session, SearchConfig(fetch_pages=2, max_results=5))
    seen: list = []

    async def search(query: str, config):
        del query
        seen.append(config)
        return []

    monkeypatch.setattr("app.services.sites.official.discovery.aggregate_search", search)
    client.post("/api/official/discover", json={"keywords": "算法"})

    assert seen
    assert seen[0].fetch_pages == 2
    assert seen[0].max_results == 5


def test_discover_excludes_third_party_boards(client, monkeypatch):
    """第三方招聘平台的页面**整个剔掉**：用户看到它在清单里就会以为那是这家公司的官网。"""
    _stub_search(
        monkeypatch,
        [{"title": "算法工程师 - 拉勾网", "url": "https://www.lagou.com/wn/jobs/1.html", "snippet": ""}],
    )

    body = client.post("/api/official/discover", json={"keywords": "算法"}).json()

    assert body["candidates"] == []


def test_discover_without_keywords_does_not_search(client, monkeypatch):
    calls = _stub_search(monkeypatch, [])

    body = client.post("/api/official/discover", json={"keywords": "   "}).json()

    assert calls == []
    assert body["candidates"] == []
    assert "关键词" in body["detail"]


def test_discover_does_not_create_anything(client, monkeypatch):
    """发现只发搜索请求，**不碰候选站点**：用户可能一条都不想要，不该为搜索结果付探测成本。"""
    _stub_search(
        monkeypatch,
        [{"title": "示例科技招聘", "url": "https://careers.example.com/jobs", "snippet": ""}],
    )

    client.post("/api/official/discover", json={"keywords": "算法"})

    assert client.get("/api/official/sites").json() == []
    assert client.get("/api/official/runs").json() == []


def test_run_detail_carries_the_model_cost(client, fake_http):
    """**用户自付 key，花销必须可见**——不然他只能去翻服务商的账单。

    抽取方式单独成字段，不塞进"依据"那一栏：用了模型与"抓全了没有"毫无关系，
    混在一起会让用户以为它们有关。
    """
    site_id = _add_site(client)["site"]["id"]
    run_id = _collect_and_wait(client, site_id)["id"]

    detail = client.get(f"/api/official/runs/{run_id}").json()

    assert detail["llm_calls"] == 0
    assert detail["extraction"]["llm_calls"] == 0
    assert detail["extraction"]["recipes_learned"] == 0
    assert detail["extraction"]["methods"] == []
    assert detail["trend"] is not None, "加了字段不该挤掉原有的"


# ===== 本次的条数上限 =====
# 岗位上万条的站点一次翻不完，用户多半只想先看前几十条。上限**只对这一次生效**：
# 它回答的是"这回我只要看这么多"，不是"这家公司永远只采这么多"。


def test_the_job_limit_reaches_the_collector(client, fake_http):
    """填了上限就要真的传到采集器——**这一条守的是"界面填了、后端没收到"**。

    那种缺陷最难发现：接口照常 200、采照常采完，只是用户填的那个数被静默丢掉，
    而他看到的结果（抓了满满一屏）看起来完全正常。所以这里断言的不是"条数变少了"
    （本夹具的适配器一页就返回全部岗位，截不断，**截断语义由编排层那条用例覆盖**），
    而是"采集器确实认为自己是被这个上限叫停的、数字也传对了"。
    """
    fake_http._routes[BOARD_PREFIX] = _board(  # noqa: SLF001 - 测试内部
        [_job(index) for index in range(1, 6)], total=5
    )
    site_id = _add_site(client)["site"]["id"]

    started = client.post(f"/api/official/sites/{site_id}/collect", json={"max_jobs": 2})
    assert started.status_code == 200, started.text
    run = _wait_for_run(client, started.json()["id"])

    assert run["reconcile_detail"]["termination"]["state"] == "job_limit"
    # **说清是哪个上限、数字是多少**：用户填的就是它，对不上他会以为没生效。
    assert "2 条" in run["reconcile_detail"]["termination"]["detail"]


def test_a_job_limit_that_did_not_actually_truncate_still_reports_complete(client, fake_http):
    """上限踩到了、但东西**其实已经全拿到了**时，结论仍然是「已确认为全量」。

    这一条钉住一个容易"修"错的地方：总量那一层是硬证据（``collected == total_hint``），
    它**故意不看**终止状态。这里上限是 2、而一页就返回了全部 3 条，站点也声明 3 条——
    我们手里确实是全部。仅仅因为"用户填过一个数"就把它降级成「无法确认」，是在用一句
    更保守的话去覆盖一个已经成立的事实。
    """
    fake_http._routes[BOARD_PREFIX] = _board([_job(1), _job(2), _job(3)], total=3)  # noqa: SLF001
    site_id = _add_site(client)["site"]["id"]

    started = client.post(f"/api/official/sites/{site_id}/collect", json={"max_jobs": 2})
    run = _wait_for_run(client, started.json()["id"])

    assert run["reconcile_detail"]["termination"]["state"] == "job_limit"
    assert run["verdict"] == "complete"
    assert run["collected"] == 3


def test_collect_without_a_job_limit_is_unchanged(client, fake_http):
    """不填时一切照旧：只有那个页数纪律在管，绝不冒出"你设的上限"。"""
    fake_http._routes[BOARD_PREFIX] = _board([_job(1), _job(2), _job(3)], total=3)  # noqa: SLF001
    site_id = _add_site(client)["site"]["id"]

    run = _collect_and_wait(client, site_id)

    assert run["verdict"] == "complete"
    assert run["reconcile_detail"]["termination"]["state"] != "job_limit"


def test_collect_rejects_an_out_of_range_job_limit(client, fake_http):
    """上限就是防手滑的（多打一个零），所以边界由后端定死，不靠界面自觉。"""
    site_id = _add_site(client)["site"]["id"]

    assert client.post(
        f"/api/official/sites/{site_id}/collect", json={"max_jobs": 0}
    ).status_code == 422
    assert client.post(
        f"/api/official/sites/{site_id}/collect", json={"max_jobs": 99999}
    ).status_code == 422


def test_collect_accepts_an_empty_body_with_a_json_content_type(client, fake_http):
    """**前端不带请求体时就是这种形状**：``Content-Type: application/json`` 而 body 是空的。

    这一条不是在测接口能不能不传 body（上面那条测过了，httpx 默认不带这个头），而是在测
    **前端真实发出的那个请求**：``request()`` 无条件设置 JSON 头，于是"留空上限"这条路的请求
    是"声明了 JSON、却没有实体"。FastAPI 对这种组合的处理与"完全不带头"并不相同——
    接口只在前者上返回 422 的话，用户看到的会是"点了采集弹一句请求失败"，而所有后端用例全绿。
    """
    fake_http._routes[BOARD_PREFIX] = _board([_job(1)], total=1)  # noqa: SLF001
    site_id = _add_site(client)["site"]["id"]

    started = client.post(
        f"/api/official/sites/{site_id}/collect", headers={"Content-Type": "application/json"}
    )

    assert started.status_code == 200, started.text
