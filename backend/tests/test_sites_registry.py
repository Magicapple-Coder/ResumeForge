"""站点适配器注册表覆盖：按来源 / URL 反查，未知目标给出可展示的中文失败。"""
from types import SimpleNamespace

import pytest

from app.services.sites.base import RiskProfile, SearchPage, SiteAdapter, SiteFailure
from app.services.sites.boss import BossAdapter
from app.services.sites.registry import SiteRegistry, default_registry


class _AlwaysAdapter(SiteAdapter):
    key = "always"
    display_name = "始终匹配"
    hosts = ()

    def matches(self, url_or_source: str) -> bool:
        return True

    def risk_profile(self) -> RiskProfile:
        return RiskProfile(key=self.key)

    def collect_search(self, client, query, page) -> SearchPage:
        return SearchPage()

    def open_apply(self, client, job) -> None:
        return None

    def fill_and_submit(self, client, data, greeting):
        raise AssertionError("测试不触发投递")


def test_for_job_matches_boss_by_source():
    adapter = default_registry().for_job(SimpleNamespace(source="BOSS直聘", source_url=""))

    assert adapter.key == "boss"


def test_for_job_matches_boss_by_source_url_when_source_empty():
    adapter = default_registry().for_job(
        SimpleNamespace(source="", source_url="https://www.zhipin.com/web/geek/job?query=x")
    )

    assert adapter.key == "boss"


def test_for_url_matches_boss_host():
    adapter = default_registry().for_url("https://www.zhipin.com/job/1")

    assert adapter.key == "boss"


def test_unknown_target_raises_a_chinese_failure():
    with pytest.raises(SiteFailure) as exc:
        default_registry().for_url("https://example.com/job")

    assert "暂不支持" in exc.value.detail


def test_first_registered_match_wins():
    registry = SiteRegistry()
    first = registry.register(_AlwaysAdapter())
    registry.register(BossAdapter())

    assert registry.for_url("https://www.zhipin.com/job/1").key == first.key
    assert len(registry.all()) == 2


def test_default_registry_exposes_a_site_entry_url():
    """启动投递专用浏览器时要打开这个地址，用户才有一个能扫码登录的落脚点。"""
    adapters = default_registry().all()

    assert [adapter.entry_url for adapter in adapters] == ["https://www.zhipin.com/"]
