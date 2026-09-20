"""BOSS 城市编码解析：动态清单、缓存、别名与错误反馈。"""
from __future__ import annotations

import pytest

from app.models.apply import FAILURE_SELECTOR_INVALID
from app.services.sites.base import CollectQuery, SiteFailure
from app.services.sites.boss import BossAdapter
from app.services.sites.boss_city import (
    CITY_ENDPOINT,
    CityResolutionError,
    CityResolver,
    parse_city_aliases,
)


def _payload():
    return {
        "code": 0,
        "zpData": {
            "hotCityList": [{"code": 101010100, "name": "北京"}],
            "cityList": [
                {
                    "code": 101280000,
                    "name": "广东",
                    "subLevelModelList": [
                        {"code": 101280100, "name": "广州市", "pinyin": "guangzhou"},
                        {"code": 101280600, "name": "深圳", "pinyin": "shenzhen"},
                    ],
                }
            ],
        },
    }


def test_city_aliases_accept_name_suffix_pinyin_and_numeric_code():
    aliases = parse_city_aliases(_payload())
    assert aliases["广州市"] == "101280100"
    assert aliases["广州"] == "101280100"
    assert aliases["guangzhou"] == "101280100"
    assert aliases["101280100"] == "101280100"


def test_resolver_fetches_unknown_city_once_and_caches_the_result():
    calls = []

    def fetch(url, timeout):
        calls.append((url, timeout))
        return _payload()

    resolver = CityResolver(fetcher=fetch, timeout=1.25, seed={})
    assert resolver.resolve("广州") == "101280100"
    assert resolver.resolve("深圳") == "101280600"
    assert calls == [(CITY_ENDPOINT, 1.25)]


def test_resolver_uses_bootstrap_for_common_city_without_network():
    resolver = CityResolver(fetcher=lambda *_args: pytest.fail("不应请求网络"))
    assert resolver.resolve("北京市") == "101010100"
    assert resolver.resolve("101280600") == "101280600"


def test_unknown_city_is_an_explicit_failure_not_a_raw_query_parameter():
    resolver = CityResolver(fetcher=lambda *_args: _payload(), seed={})
    with pytest.raises(CityResolutionError, match="无法识别城市"):
        resolver.resolve("火星城")


def test_nonzero_city_api_response_is_reported():
    resolver = CityResolver(
        fetcher=lambda *_args: {"code": 19, "message": "参数值错误"}, seed={}
    )
    with pytest.raises(CityResolutionError, match="code=19.*参数值错误"):
        resolver.resolve("广州")


def test_malformed_city_payload_is_reported_as_a_city_error():
    resolver = CityResolver(fetcher=lambda *_args: "not-json", seed={})

    with pytest.raises(CityResolutionError, match="无法解析"):
        resolver.resolve("广州")


def test_adapter_never_puts_an_unknown_city_name_into_the_search_url():
    resolver = CityResolver(fetcher=lambda *_args: _payload(), seed={})
    adapter = BossAdapter(city_resolver=resolver)

    with pytest.raises(SiteFailure, match="城市筛选无法生效") as excinfo:
        adapter.build_search_url(CollectQuery(keywords=["后端"], city="火星城"), 1)

    assert excinfo.value.category == FAILURE_SELECTOR_INVALID
