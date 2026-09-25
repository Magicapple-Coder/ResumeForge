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
from datetime import datetime, timezone
from urllib.parse import unquote

import httpx

from ..config import get_settings
from ..schemas.update import UpdateCheckResult

logger = logging.getLogger(__name__)

DEFAULT_REPOSITORY = "magicapple123/ResumeForge"
REPOSITORY_ENV_VAR = "RESUMEFORGE_UPDATE_REPO"
RELEASES_API = "https://api.github.com/repos/{repo}/releases/latest"
# 备用探测：github.com 的 `releases/latest` 会 302 到具体 tag。
# 它**不经过 api.github.com**，所以匿名限额用完、或者网络里只拦了 API 域名时照样能用
# （用户报的 "HTTP 403" 就是这一类：本机实测 API 正常、他那条网络返回 403）。
# 代价是只拿得到版本号，拿不到更新说明与附件下载地址——够用来回答"有没有新版本"。
RELEASES_REDIRECT = "https://github.com/{repo}/releases/latest"
RELEASES_PAGE = "https://github.com/{repo}/releases"
_TAG_MARKER = "/releases/tag/"

_CACHE_SECONDS = 900
_MAX_RESPONSE_BYTES = 512 * 1024
_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
_USER_AGENT = "ResumeForge-update-check"

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


def _download_asset(data: dict) -> tuple[str, str, int | None, bool]:
    """优先找维护者上传的完整包，没有时退回 GitHub 源码 zip。"""
    assets = data.get("assets")
    if isinstance(assets, list):
        candidates = [item for item in assets if isinstance(item, dict)]
        candidates.sort(key=lambda item: str(item.get("name") or ""))
        for asset in candidates:
            name = str(asset.get("name") or "")
            url = str(asset.get("browser_download_url") or "")
            if name.lower().endswith(".zip") and url.startswith("https://"):
                size = asset.get("size")
                return url, name[:256], int(size) if isinstance(size, int) and size >= 0 else None, True

    source_url = str(data.get("zipball_url") or "")
    if source_url.startswith("https://"):
        return source_url, "GitHub 源码包.zip", None, True
    return "", "", None, False


def _github_error_message(status_code: int, repo: str) -> str:
    """把 GitHub 的状态码翻译成用户能判断"该等一下还是该换网络"的一句话。

    「检查更新失败：GitHub 返回了 HTTP 403」这种原文对用户毫无用处：403 既可能是
    匿名调用限额用完（等一会儿就好），也可能是网络里有人拦了 api.github.com
    （等多久都没用，得走备用方式或手动看）。这里把它们分开说。
    """
    if status_code == 403:
        return (
            "GitHub 拒绝了这次匿名请求（HTTP 403）：常见原因是同一网络下匿名调用次数"
            "用完，或网络内有人拦了 api.github.com"
        )
    if status_code == 429:
        return "GitHub 提示请求过于频繁（HTTP 429），稍后再试即可"
    if status_code >= 500:
        return f"GitHub 服务暂时不可用（HTTP {status_code}），稍后再试"
    return f"GitHub 返回了 HTTP {status_code}"


async def _fetch_latest_release(repo: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        async with client.stream("GET", RELEASES_API.format(repo=repo), headers=headers) as response:
            if response.status_code == 404:
                raise LookupError("仓库还没有发布任何 Release")
            if response.status_code != 200:
                raise RuntimeError(_github_error_message(response.status_code, repo))
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                    raise RuntimeError("GitHub 响应过大，已停止读取")
                body.extend(chunk)
    data = json.loads(body)
    if not isinstance(data, dict):
        raise RuntimeError("GitHub 响应格式不符合预期")
    return data


async def _fetch_latest_tag_via_redirect(repo: str) -> str:
    """备用探测：跟着 github.com 的 302 拿到最新 tag，全程不碰 api.github.com。

    返回形如 ``v0.12.0``；拿不到就抛错，由调用方决定怎么措辞。
    """
    url = RELEASES_REDIRECT.format(repo=repo)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        response = await client.get(url, headers={"User-Agent": _USER_AGENT})
    if response.status_code == 404:
        raise LookupError("仓库还没有发布任何 Release")
    if response.status_code not in (301, 302, 303, 307, 308):
        raise RuntimeError(_github_error_message(response.status_code, repo))
    location = str(response.headers.get("location") or "")
    if _TAG_MARKER not in location:
        # 没有 Release 时 GitHub 会重定向到 /releases 列表页（没有 tag 段）。
        raise LookupError("仓库还没有发布任何 Release")
    return unquote(location.split(_TAG_MARKER, 1)[1]).strip("/")


async def check_for_update(*, refresh: bool = False) -> UpdateCheckResult:
    """返回当前版本与最新版本的对比结果。"""
    current = get_settings().app_version
    repo = repository()
    cached = _cache.get(repo)
    if not refresh and cached is not None and time.time() - cached[0] < _CACHE_SECONDS:
        return cached[1]

    api_failure = ""
    try:
        data = await _fetch_latest_release(repo)
    except LookupError:
        return _remember(repo, _no_release_result(current, repo))
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.info("检查更新失败（网络）：%s", exc)
        return _remember(repo, _unreachable_result(current, repo))
    except (RuntimeError, ValueError) as exc:
        # 主路径失败（限流、被拦、响应异常）不直接认输：先用不碰 API 的备用方式问一次
        # "到底有没有新版本"。用户点「检查更新」想知道的就是这一件事，
        # 而"接口不可用"不该等于"回答不了"。
        api_failure = str(exc)
        logger.info("检查更新主路径失败，改用备用探测：%s", api_failure)
        try:
            tag = await _fetch_latest_tag_via_redirect(repo)
        except LookupError:
            return _remember(repo, _no_release_result(current, repo))
        except (RuntimeError, httpx.HTTPError) as fallback_exc:
            logger.info("检查更新备用探测也失败：%s", fallback_exc)
            return _remember(
                repo,
                UpdateCheckResult(
                    current_version=current,
                    message=(
                        f"检查更新失败：{api_failure}。备用方式这次也没成功"
                        f"（{fallback_exc}），稍后再点一次通常就好了；"
                        f"也可以到 {RELEASES_PAGE.format(repo=repo)} 手动查看"
                    )[:1000],
                ),
            )
        latest = tag.lstrip("vV") or current
        available = _is_newer(tag or latest, current)
        return _remember(
            repo,
            UpdateCheckResult(
                current_version=current,
                latest_version=latest,
                update_available=available,
                release_name=tag[:256],
                release_url=RELEASES_PAGE.format(repo=repo),
                message=(
                    f"检测到新版本 {latest}（GitHub 接口这次不可用，已用备用方式确认）；"
                    f"更新说明与安装包请在 Release 页查看"
                    if available
                    else f"已是最新版本（{current}）"
                ),
            ),
        )
    else:
        tag = str(data.get("tag_name") or "").strip()
        latest = tag.lstrip("vV") or current
        available = _is_newer(tag or latest, current)
        notes = str(data.get("body") or "").strip()
        download_url, asset_name, download_size, installable = _download_asset(data)
        result = UpdateCheckResult(
            current_version=current,
            latest_version=latest,
            update_available=available,
            release_name=str(data.get("name") or tag)[:256],
            release_url=str(data.get("html_url") or RELEASES_PAGE.format(repo=repo))[:512],
            published_at=str(data.get("published_at") or "")[:64],
            notes=notes[:4000],
            download_url=download_url[:1024],
            download_size=download_size,
            asset_name=asset_name,
            installable=installable and available,
            message=(
                f"有新版本 {latest} 可用" if available else f"已是最新版本（{current}）"
            ),
        )
    return _remember(repo, result)


def _no_release_result(current: str, repo: str) -> UpdateCheckResult:
    return UpdateCheckResult(
        current_version=current,
        message=f"仓库还没有发布任何 Release，可以到 {RELEASES_PAGE.format(repo=repo)} 查看",
    )


def _unreachable_result(current: str, repo: str) -> UpdateCheckResult:
    return UpdateCheckResult(
        current_version=current,
        message="无法连接 GitHub 检查更新，请确认网络后重试",
    )


def _remember(repo: str, result: UpdateCheckResult) -> UpdateCheckResult:
    """记下这次结果（含失败）并打上时间戳。"""
    result.checked_at = datetime.now(timezone.utc)
    _cache[repo] = (time.time(), result)
    return result


def clear_cache() -> None:
    """测试用：清掉进程内缓存。"""
    _cache.clear()


__all__ = ["check_for_update", "clear_cache", "repository"]
