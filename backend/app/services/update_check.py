"""检查是否有新版本：只读 GitHub Releases API，不做任何自动更新。

设计取舍：
- 只发一个匿名 GET，不带任何用户数据，也不上报本地版本之外的任何信息；
- 结果缓存一段时间，避免用户反复点「检查更新」把 GitHub 的匿名限额用完；
- 任何网络/解析失败都降级为一句可读提示，不影响其它功能。
"""
from __future__ import annotations

import json
import logging
import os
import time
import httpx

from ..config import get_settings
from ..schemas.update import UpdateCheckResult

logger = logging.getLogger(__name__)

DEFAULT_REPOSITORY = "magicapple123/ResumeForge"
REPOSITORY_ENV_VAR = "RESUMEFORGE_UPDATE_REPO"
RELEASES_API = "https://api.github.com/repos/{repo}/releases/latest"
RELEASES_PAGE = "https://github.com/{repo}/releases"

_CACHE_SECONDS = 900
_MAX_RESPONSE_BYTES = 512 * 1024
_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)

_cache: dict[str, tuple[float, UpdateCheckResult]] = {}


def repository() -> str:
    return os.environ.get(REPOSITORY_ENV_VAR, "").strip() or DEFAULT_REPOSITORY


def _version_tuple(value: str) -> tuple[int, ...]:
    """把 ``v0.6.0`` / ``0.6`` 这样的标签变成可比较的元组；无法解析时返回空元组。"""
    cleaned = value.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.replace("-", ".").split("."):
        digits = "".join(char for char in chunk if char.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _is_newer(latest: str, current: str) -> bool:
    latest_tuple = _version_tuple(latest)
    current_tuple = _version_tuple(current)
    if not latest_tuple or not current_tuple:
        return False
    size = max(len(latest_tuple), len(current_tuple))
    return latest_tuple + (0,) * (size - len(latest_tuple)) > current_tuple + (0,) * (
        size - len(current_tuple)
    )


async def _fetch_latest_release(repo: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ResumeForge-update-check",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        async with client.stream("GET", RELEASES_API.format(repo=repo), headers=headers) as response:
            if response.status_code == 404:
                raise LookupError("仓库还没有发布任何 Release")
            if response.status_code != 200:
                raise RuntimeError(f"GitHub 返回了 HTTP {response.status_code}")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                    raise RuntimeError("GitHub 响应过大，已停止读取")
                body.extend(chunk)
    data = json.loads(body)
    if not isinstance(data, dict):
        raise RuntimeError("GitHub 响应格式不符合预期")
    return data


async def check_for_update(*, refresh: bool = False) -> UpdateCheckResult:
    """返回当前版本与最新版本的对比结果。"""
    current = get_settings().app_version
    repo = repository()
    cached = _cache.get(repo)
    if not refresh and cached is not None and time.time() - cached[0] < _CACHE_SECONDS:
        return cached[1]

    try:
        data = await _fetch_latest_release(repo)
    except LookupError as exc:
        result = UpdateCheckResult(
            current_version=current,
            message=f"{exc}，可以到 {RELEASES_PAGE.format(repo=repo)} 查看",
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.info("检查更新失败（网络）：%s", exc)
        result = UpdateCheckResult(
            current_version=current,
            message="无法连接 GitHub 检查更新，请确认网络后重试",
        )
    except (RuntimeError, ValueError) as exc:
        logger.info("检查更新失败：%s", exc)
        result = UpdateCheckResult(
            current_version=current,
            message=f"检查更新失败：{exc}",
        )
    else:
        tag = str(data.get("tag_name") or "").strip()
        latest = tag.lstrip("vV") or current
        available = _is_newer(tag or latest, current)
        notes = str(data.get("body") or "").strip()
        result = UpdateCheckResult(
            current_version=current,
            latest_version=latest,
            update_available=available,
            release_name=str(data.get("name") or tag)[:256],
            release_url=str(data.get("html_url") or RELEASES_PAGE.format(repo=repo))[:512],
            published_at=str(data.get("published_at") or "")[:64],
            notes=notes[:4000],
            message=(
                f"有新版本 {latest} 可用" if available else f"已是最新版本（{current}）"
            ),
        )
    _cache[repo] = (time.time(), result)
    return result


def clear_cache() -> None:
    """测试用：清掉进程内缓存。"""
    _cache.clear()


__all__ = ["check_for_update", "clear_cache", "repository"]
