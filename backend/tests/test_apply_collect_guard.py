"""采集"抓不到必须失败 / 真的没有才是空"的守护测试（对应"采集恒为 0"缺陷的修复）。

覆盖三件事：
- 采集过程中适配器抛出 ``SiteFailure``（页面没 load 好 / 选择器失效 / 需登录）→ 任务**失败**
  且 message 带上可操作诊断，而不是"采集完成，共新增 0 个岗位"；
- 页面明确呈现"无结果"→ 任务**完成**，且 message 说清"没搜到"，与失败区分开；
- 采集遵循"当前站点"：配置里选了哪个站点，就用哪个适配器。
"""
from __future__ import annotations

import time

from app.models.apply import ApplyTask
from app.schemas.apply import ApplyConfigIn, CollectConfigIn
from app.services.apply import apply_service
from app.services.apply.task_runner import TaskRunner
from app.services.browser.cdp_client import CdpClient
from app.services.sites.base import (
    ApplyOutcome,
    CollectQuery,
    RiskProfile,
    SearchPage,
    SiteAdapter,
    SiteFailure,
)
from app.services.sites.registry import SiteRegistry


class _FakeClock:
    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        self._t += 100.0
        return self._t


class FakeCdp(CdpClient):
    def list_targets(self):
        return []

    def new_tab(self, url: str = "about:blank") -> str:
        return "t"

    def send(self, method, params=None, *, timeout=None):
        return {}

    def evaluate(self, expression, *, timeout=None):
        return None

    def set_file_input(self, selector, files, *, timeout=None):
        return None

    def navigate(self, url, *, timeout=None):
        return {}

    def close(self):
        return None


class CollectAdapter(SiteAdapter):
    """采集适配器：要么抛 ``SiteFailure``，要么返回给定的 ``SearchPage``。"""

    key = "boss"
    display_name = "示例采集站"
    hosts = ("zhipin.com",)

    def __init__(self, page: SearchPage | None = None, failure: SiteFailure | None = None) -> None:
        self._page = page or SearchPage()
        self._failure = failure
        self.calls = 0

    def matches(self, url_or_source: str) -> bool:
        return True

    def risk_profile(self) -> RiskProfile:
        return RiskProfile(key=self.key)

    def collect_search(self, client, query: CollectQuery, page: int) -> SearchPage:
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        return self._page

    def open_apply(self, client, job):  # pragma: no cover - 采集不用
        raise AssertionError("采集不应触发投递")

    def fill_and_submit(self, client, data, greeting) -> ApplyOutcome:  # pragma: no cover
        raise AssertionError("采集不应触发投递")


def _registry(*adapters: SiteAdapter) -> SiteRegistry:
    registry = SiteRegistry()
    for adapter in adapters:
        registry.register(adapter)
    return registry


def _collect_task(db_session) -> ApplyTask:
    task = ApplyTask(
        kind="collect",
        status="pending",
        total=20,
        config=CollectConfigIn(keywords=["后端"], per_task_limit=20).model_dump(),
    )
    db_session.add(task)
    db_session.commit()
    return task


def _runner(registry: SiteRegistry) -> TaskRunner:
    return TaskRunner(
        registry=registry,
        client_factory=lambda _config: FakeCdp(),
        sleeper=lambda _seconds: None,
        clock=_FakeClock(),
        poll_interval=0.01,
    )


def _wait(runner: TaskRunner, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while runner.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)


def test_collect_failure_marks_the_task_failed_with_actionable_message(db_session):
    failure = SiteFailure(
        "selector_invalid",
        "页面结构可能已变化：未找到「岗位卡片」。当前地址：https://www.zhipin.com/web/geek/job",
    )
    adapter = CollectAdapter(failure=failure)
    task = _collect_task(db_session)
    runner = _runner(_registry(adapter))

    runner.start(task.id)
    _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "failed"
    assert stored.stop_reason == "error"
    # 关键：把可操作诊断带给用户，而不是伪装成"完成"。
    assert "采集失败" in stored.message
    assert "页面结构可能已变化" in stored.message


def test_genuinely_empty_collect_completes_with_a_clear_no_result_message(db_session):
    adapter = CollectAdapter(page=SearchPage(results=[], page=1, has_next=False))
    task = _collect_task(db_session)
    runner = _runner(_registry(adapter))

    runner.start(task.id)
    _wait(runner)

    db_session.expire_all()
    stored = db_session.get(ApplyTask, task.id)
    assert stored.status == "completed"
    assert stored.stop_reason == "done"
    assert stored.succeeded == 0
    # 真正的 0（关键词没搜到）与失败（抓不到）必须区分开。
    assert "没有找到匹配的岗位" in stored.message


def test_collect_uses_the_current_site_from_configuration(db_session):
    """注册了多个站点时，采集用配置里选中的那个，而不是永远用第一个。"""
    other = CollectAdapter(page=SearchPage(results=[], has_next=False))
    other.key = "other"
    registry = _registry(CollectAdapter(), other)

    apply_service.save_apply_config(db_session, ApplyConfigIn(site_key="other"))
    db_session.commit()

    runner = _runner(registry)
    chosen = runner._collect_adapter(db_session, registry)

    assert chosen is other
