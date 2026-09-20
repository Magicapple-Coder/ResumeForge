"""BOSS 城市名称到搜索参数编码的动态解析。"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.request import Request, urlopen

CITY_ENDPOINT = "https://www.zhipin.com/wapi/zpCommon/data/city.json"
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_CITY_RESPONSE_BYTES = 2 * 1024 * 1024

CityFetcher = Callable[[str, float], Any]

# 常用城市作为离线启动缓存；未知城市仍从公开接口动态加载完整清单。
_BOOTSTRAP_CODES = {
    "全国": "100010000",
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "天津": "101030100",
    "西安": "101110100",
    "苏州": "101190400",
    "武汉": "101200100",
    "厦门": "101230200",
    "长沙": "101250100",
    "成都": "101270100",
    "郑州": "101180100",
    "重庆": "101040100",
}


class CityResolutionError(ValueError):
    """城市清单不可用或输入无法映射到 BOSS 城市编码。"""


def _default_fetcher(url: str, timeout: float) -> Any:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 ResumeForge"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_CITY_RESPONSE_BYTES + 1)
    if len(raw) > MAX_CITY_RESPONSE_BYTES:
        raise CityResolutionError("BOSS 城市接口响应过大")
    return _decode_payload(raw)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalise_alias(value: Any) -> str:
    return "".join(_text(value).casefold().split())


def _short_name(name: str) -> str:
    for suffix in ("特别行政区", "壮族自治区", "回族自治区", "维吾尔自治区", "自治区", "省", "市"):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def _decode_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CityResolutionError("BOSS 城市接口返回了无法解码的内容") from exc
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_CITY_RESPONSE_BYTES:
            raise CityResolutionError("BOSS 城市接口响应过大")
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise CityResolutionError("BOSS 城市接口返回了无法解析的 JSON") from exc
    if not isinstance(value, dict):
        raise CityResolutionError("BOSS 城市接口返回了无法识别的内容")
    return value


def _city_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    code = payload.get("code")
    if code not in (None, 0, "0"):
        message = _text(payload.get("message") or payload.get("msg"))
        raise CityResolutionError(f"BOSS 城市接口返回错误 code={code}：{message or '未知错误'}")
    data = payload.get("zpData")
    if not isinstance(data, dict):
        data = payload.get("data")
    if not isinstance(data, dict):
        raise CityResolutionError("BOSS 城市接口缺少城市数据")

    result: list[dict[str, Any]] = []
    for key in ("hotCityList", "hotCities"):
        values = data.get(key)
        if isinstance(values, list):
            result.extend(item for item in values if isinstance(item, dict))
    provinces = data.get("cityList")
    if not isinstance(provinces, list):
        provinces = data.get("cities")
    if isinstance(provinces, list):
        for province in provinces:
            if not isinstance(province, dict):
                continue
            children = province.get("subLevelModelList")
            if not isinstance(children, list):
                children = province.get("children")
            if isinstance(children, list) and children:
                result.extend(item for item in children if isinstance(item, dict))
            else:
                result.append(province)
    location = data.get("locationCity")
    if isinstance(location, dict):
        result.append(location)
    return result


def parse_city_aliases(payload: Any) -> dict[str, str]:
    """从公开城市接口中建立唯一别名到 BOSS 搜索编码的映射。"""
    candidates: dict[str, set[str]] = {}
    for node in _city_nodes(_decode_payload(payload)):
        code = _text(node.get("code") or node.get("value"))
        name = _text(node.get("name") or node.get("cityName"))
        if not (code.isdigit() and len(code) == 9 and name):
            continue
        aliases = {code, name, _short_name(name), _text(node.get("pinyin"))}
        for alias in aliases:
            key = _normalise_alias(alias)
            if key:
                candidates.setdefault(key, set()).add(code)
    return {alias: next(iter(codes)) for alias, codes in candidates.items() if len(codes) == 1}


class CityResolver:
    """按需加载完整城市清单，并在实例内缓存解析结果。"""

    def __init__(
        self,
        *,
        fetcher: CityFetcher | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        seed: Mapping[str, str] | None = None,
    ) -> None:
        self._fetcher = fetcher or _default_fetcher
        self._timeout = max(float(timeout), 0.1)
        initial = _BOOTSTRAP_CODES if seed is None else seed
        self._aliases: dict[str, str] = {}
        for name, code in initial.items():
            for alias in (name, _short_name(name), code):
                self._aliases[_normalise_alias(alias)] = str(code)
        self._loaded = False

    def resolve(self, city: str) -> str:
        raw_city = _text(city)
        value = _normalise_alias(raw_city)
        if not value:
            return ""
        if value.isdigit() and len(value) == 9:
            return value
        short_value = _normalise_alias(_short_name(raw_city))
        cached = self._aliases.get(value) or self._aliases.get(short_value)
        if cached:
            return cached
        if not self._loaded:
            try:
                payload = self._fetcher(CITY_ENDPOINT, self._timeout)
                aliases = parse_city_aliases(payload)
            except CityResolutionError:
                raise
            except Exception as exc:
                raise CityResolutionError(f"无法获取 BOSS 城市清单：{exc}") from exc
            if not aliases:
                raise CityResolutionError("BOSS 城市接口没有返回可用城市")
            self._aliases.update(aliases)
            self._loaded = True
        code = self._aliases.get(value) or self._aliases.get(short_value)
        if not code:
            raise CityResolutionError(
                f"无法识别城市“{city.strip()}”，请填写 BOSS 城市名称或 9 位城市编码"
            )
        return code


__all__ = [
    "CITY_ENDPOINT",
    "MAX_CITY_RESPONSE_BYTES",
    "CityResolutionError",
    "CityResolver",
    "parse_city_aliases",
]
