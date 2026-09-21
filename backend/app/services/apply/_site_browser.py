"""当前站点与投递专用浏览器（进程内单例），以及站点筛选栏可选项。"""
from __future__ import annotations

import logging
import threading
from typing import Any

from sqlalchemy.orm import Session

from ...config import DEFAULT_BROWSER_PORT
from ...schemas.apply import (
    ApplyConfigIn,
    BrowserStatusOut,
    CollectFilterGroupOut,
    CollectFilterOptionOut,
    CollectFilterOptionsOut,
    SiteListOut,
    SiteOptionOut,
)
from ..browser.browser_manager import (
    BROWSER_STATE_RUNNING,
    BrowserError,
    BrowserManager,
    BrowserStatus,
)
from ..browser.cdp_client import CdpError
from ..sites.base import SOURCE_SESSION, SiteAdapter
from ..sites.registry import get_registry
from ._base import ApplyConflict
from ._config import get_apply_config

logger = logging.getLogger(__name__)
def collect_filter_options(db: Session) -> CollectFilterOptionsOut:
    """当前站点筛选栏的可选项（界面据此渲染下拉框）。

    **浏览器在跑就在用户自己的页面上读**：只有那条路能拿到"这个账号真实可见"的清单——
    「求职类型」的选项因人而异（实测：登录账号能看到「实习」，未登录看不到），写死一份等于
    替所有用户决定了他们能选什么。浏览器没启动就退回免登录的公开清单，并把来源如实标出来。

    这里**只读，不导航**：读的是用户当前那个标签页上已有的东西（一次页面内 fetch + 一次 DOM
    读取），所以不会把用户正在看的页面顶掉。读失败一律降级，绝不让配置界面打不开。
    """
    adapter = current_site(db)
    if adapter is None:
        return CollectFilterOptionsOut()

    client = None
    try:
        manager = get_browser_manager(db)
        if manager.status().state == BROWSER_STATE_RUNNING:
            client = manager.client()
    except (BrowserError, CdpError):
        # 浏览器状态探测失败与"没启动"等价：退回公开清单即可，不值得打扰用户。
        logger.debug("读取浏览器状态失败，将使用公开筛选清单", exc_info=True)
        client = None

    try:
        groups = adapter.fetch_filter_options(client)
    except Exception:  # noqa: BLE001 - 清单读不到是降级路径，不能让整个配置界面失败
        logger.warning("读取站点筛选选项失败，界面将不显示筛选项", exc_info=True)
        groups = ()
    finally:
        if client is not None:
            client.close()

    return CollectFilterOptionsOut(
        site_key=adapter.key,
        display_name=adapter.display_name,
        groups=[_filter_group_out(group) for group in groups],
        session_read=any(getattr(group, "source", "") == SOURCE_SESSION for group in groups),
    )


def _filter_group_out(group: Any) -> CollectFilterGroupOut:
    return CollectFilterGroupOut(
        key=group.key,
        param=group.param,
        label=group.label,
        options=[
            CollectFilterOptionOut(code=item.code, label=item.label, group=item.group)
            for item in group.options
        ],
        source=group.source,
        note=group.note,
    )

def current_site(db: Session) -> SiteAdapter | None:
    """当前选中的站点适配器。

    先按配置里的 ``site_key`` 精确取；取不到（配置为空 / 站点被移除）就回退到注册表里的
    第一个站点，保证界面与入口地址永远有一个可用值。
    """
    registry = get_registry()
    config = get_apply_config(db)
    adapter = registry.resolve(config.site_key)
    if adapter is not None:
        return adapter
    adapters = registry.all()
    return adapters[0] if adapters else None


def current_site_key(db: Session) -> str:
    adapter = current_site(db)
    return adapter.key if adapter is not None else ""


def _site_option_out(adapter: SiteAdapter) -> SiteOptionOut:
    return SiteOptionOut(
        key=adapter.key,
        display_name=adapter.display_name,
        host=adapter.hosts[0] if adapter.hosts else "",
        entry_url=adapter.entry_url,
        supports_collect=adapter.supports_collect,
        supports_apply=adapter.supports_apply,
    )


def list_sites(db: Session) -> SiteListOut:
    """已注册站点列表 + 当前选中项。

    前端据此展示"当前招聘网站"，**不把站点名写死在组件里**；将来后端注册表里多加一行，
    界面自动多出一个站点可选。
    """
    registry = get_registry()
    return SiteListOut(
        current=current_site_key(db),
        sites=[_site_option_out(adapter) for adapter in registry.all()],
    )


# ===== 投递专用浏览器（进程内单例，端口 / 浏览器选择 / 自定义路径共同决定是否重建）=====

_browser_lock = threading.Lock()
_browser_manager: BrowserManager | None = None
_browser_manager_key: tuple[Any, ...] | None = None


def _browser_cache_key(config: ApplyConfigIn) -> tuple[Any, ...]:
    """浏览器单例的缓存键：端口、浏览器选择、自定义路径任一变化都要重建。"""
    return (
        config.browser_port or DEFAULT_BROWSER_PORT,
        config.browser_choice,
        config.browser_path.strip(),
    )


def get_browser_manager(db: Session) -> BrowserManager:
    """按当前配置返回浏览器管理器单例；配置（端口 / 选择 / 路径）变更时先关旧实例再重建。"""
    global _browser_manager, _browser_manager_key
    config = get_apply_config(db)
    key = _browser_cache_key(config)
    port = key[0]
    with _browser_lock:
        if _browser_manager is None or _browser_manager_key != key:
            if _browser_manager is not None:
                _browser_manager.stop()
            _browser_manager = BrowserManager(
                port=port,
                browser_choice=config.browser_choice,
                browser_path=config.browser_path.strip() or None,
            )
            _browser_manager_key = key
        return _browser_manager


def default_entry_url(db: Session) -> str:
    """投递专用浏览器启动时要打开的**当前站点**入口地址。

    取当前站点的 ``entry_url``；当前站点没有入口地址时退化到"第一个有入口的站点"。
    取不到就返回空串，调用方会让窗口停在 about:blank，界面上仍可用「打开招聘网站」手动导航。
    """
    adapter = current_site(db)
    if adapter is not None and adapter.entry_url:
        return adapter.entry_url
    for candidate in get_registry().all():
        if candidate.entry_url:
            return candidate.entry_url
    return ""


def _browser_status_out(status: BrowserStatus, db: Session) -> BrowserStatusOut:
    """把浏览器状态快照转成对外 schema。字段只在这一处列，避免多个出口漏字段。"""
    return BrowserStatusOut(
        state=status.state,
        port=status.port,
        profile_dir=status.profile_dir,
        browser_path=status.browser_path,
        browser_name=status.browser_name,
        entry_url=default_entry_url(db),
        logged_in_hint=status.logged_in_hint,
        owned=status.owned,
    )


def browser_status(db: Session) -> BrowserStatusOut:
    manager = get_browser_manager(db)
    return _browser_status_out(manager.status(), db)


def start_browser(db: Session) -> BrowserStatusOut:
    """启动投递专用浏览器（带上站点入口地址）并返回状态；启动失败转 ApplyConflict。"""
    manager = get_browser_manager(db)
    try:
        # 带上站点入口地址：只开 about:blank 的话用户面对空白窗口无从登录。
        status = manager.start(url=default_entry_url(db) or None)
    except BrowserError as exc:
        raise ApplyConflict(str(exc)) from exc
    return _browser_status_out(status, db)


def open_browser_url(db: Session) -> BrowserStatusOut:
    """在已启动的专用浏览器里打开站点入口地址。

    用户可能自己把标签页关掉或跳到了别处，这时不必重启浏览器，导航回去即可。
    """
    manager = get_browser_manager(db)
    url = default_entry_url(db)
    if not url:
        raise ApplyConflict("暂时没有可打开的招聘网站入口地址")
    try:
        manager.open_url(url)
    except (BrowserError, CdpError) as exc:
        raise ApplyConflict(str(exc)) from exc
    return _browser_status_out(manager.status(), db)


def stop_browser(db: Session) -> None:
    """关闭投递专用浏览器。

    只关得了**本次运行**启动的那个。后端重启后浏览器仍在跑、句柄已经丢了，这时
    ``manager.stop()`` 是静默 no-op——接口必须自己把它变成一条明确的中文提示，
    否则界面会弹"已关闭"，而窗口还开在那里。
    """
    manager = get_browser_manager(db)
    if not manager.status().owned and manager.is_running():
        raise ApplyConflict(
            "这个浏览器窗口不是本次运行启动的（应用重启时会丢掉它的进程句柄），"
            "应用不会去猜进程来关它——请直接关闭那个窗口。"
        )
    manager.stop()


def reset_browser_manager() -> None:
    """测试用：清掉进程内浏览器单例，避免用例之间互相影响。"""
    global _browser_manager, _browser_manager_key
    with _browser_lock:
        if _browser_manager is not None:
            _browser_manager.stop()
        _browser_manager = None
        _browser_manager_key = None
