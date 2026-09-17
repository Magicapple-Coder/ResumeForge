"""QA 独立对抗测试（第 4、5 节）：自选浏览器的"绝不静默回退" + "新增站点只需改后端"。

第 4 节：主理人 hard requirement——明确选了 Chrome 却启动 Edge 比报错更坏，所以
``chrome`` / ``edge`` 只找对应的那一个，找不到必须报中文错；``auto`` 才允许回退；
缓存键（端口/选择/路径）变化必须重建管理器并先关掉旧实例。

第 5 节：用户明确诉求"以后要加别的招聘网站"。这里**真的注册一个假站点适配器**，然后断言
``GET /api/apply/sites`` 自动出现它、``default_entry_url`` 跟着切；并扫描前端生产代码，
确认没有写死的站点名/清单/URL。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.apply import ApplyConfigIn
from app.services.apply import apply_service
from app.services.browser.browser_manager import (
    BROWSER_CHOICE_AUTO,
    BROWSER_CHOICE_CHROME,
    BROWSER_CHOICE_CUSTOM,
    BROWSER_CHOICE_EDGE,
    BrowserError,
    BrowserManager,
    browser_display_name,
)
from app.services.sites.base import ApplyOutcome, RiskProfile, SearchPage, SiteAdapter
from app.services.sites.boss import BossAdapter
from app.services.sites.registry import SiteRegistry

# ===== 第 4 节：自选浏览器 =====


def _env_with(tmp_path: Path, *which: str) -> dict[str, str]:
    """构造只装了指定浏览器的假安装环境。"""
    program_files = tmp_path / "pf"
    env: dict[str, str] = {"PROGRAMFILES": str(program_files)}
    if "chrome" in which:
        (program_files / "Google" / "Chrome" / "Application").mkdir(parents=True, exist_ok=True)
        (program_files / "Google" / "Chrome" / "Application" / "chrome.exe").write_text("")
    if "edge" in which:
        (program_files / "Microsoft" / "Edge" / "Application").mkdir(parents=True, exist_ok=True)
        (program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe").write_text("")
    return env


def _manager(tmp_path: Path, *, choice: str, env: dict[str, str]) -> BrowserManager:
    return BrowserManager(
        profile_dir=tmp_path / "profile",
        browser_path=None,
        browser_choice=choice,
        env=env,
        popen=lambda *a, **k: None,
    )


def test_chrome_choice_with_only_edge_errors_and_never_falls_back(tmp_path, monkeypatch):
    """假环境里只有 Edge、却明确选了 chrome → 必须报中文错，绝不回退到 Edge。"""
    monkeypatch.setattr("shutil.which", lambda _name: None)
    manager = _manager(tmp_path, choice=BROWSER_CHOICE_CHROME, env=_env_with(tmp_path, "edge"))

    with pytest.raises(BrowserError) as excinfo:
        manager._locate_browser()

    message = str(excinfo.value)
    assert "Google Chrome" in message
    assert "自定义路径" in message
    # 明确告知了"改用自动"这条出路。
    assert "自动" in message


def test_edge_choice_with_only_chrome_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    manager = _manager(tmp_path, choice=BROWSER_CHOICE_EDGE, env=_env_with(tmp_path, "chrome"))

    with pytest.raises(BrowserError) as excinfo:
        manager._locate_browser()

    assert "Microsoft Edge" in str(excinfo.value)


def test_chrome_choice_finds_chrome_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    manager = _manager(tmp_path, choice=BROWSER_CHOICE_CHROME, env=_env_with(tmp_path, "chrome", "edge"))

    assert manager._locate_browser().name == "chrome.exe"


def test_edge_choice_finds_edge_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    manager = _manager(tmp_path, choice=BROWSER_CHOICE_EDGE, env=_env_with(tmp_path, "chrome", "edge"))

    assert manager._locate_browser().name == "msedge.exe"


def test_auto_prefers_chrome_then_edge_then_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    # 两者都在 → 优先 Chrome。
    both = _manager(tmp_path, choice=BROWSER_CHOICE_AUTO, env=_env_with(tmp_path, "chrome", "edge"))
    assert both._locate_browser().name == "chrome.exe"
    # 只有 Edge → 回退 Edge。
    only_edge = _manager(
        tmp_path / "b", choice=BROWSER_CHOICE_AUTO, env=_env_with(tmp_path / "b", "edge")
    )
    assert only_edge._locate_browser().name == "msedge.exe"
    # 都没有 → 中文报错。
    none = _manager(tmp_path / "c", choice=BROWSER_CHOICE_AUTO, env=_env_with(tmp_path / "c"))
    with pytest.raises(BrowserError, match="未找到可用的浏览器"):
        none._locate_browser()


def test_custom_choice_with_missing_file_errors_in_chinese(tmp_path):
    manager = BrowserManager(
        profile_dir=tmp_path / "profile",
        browser_choice=BROWSER_CHOICE_CUSTOM,
        browser_path=tmp_path / "nope.exe",
        popen=lambda *a, **k: None,
    )

    with pytest.raises(BrowserError, match="不存在或不是文件"):
        manager._locate_browser()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("C:/x/msedge.exe", "Microsoft Edge"),
        ("C:/x/chrome.exe", "Google Chrome"),
        ("C:/x/other.exe", "自定义浏览器"),
        ("", ""),
    ],
)
def test_browser_display_name_is_human_readable(path, expected):
    assert browser_display_name(path) == expected


class _FakeBrowserManager:
    """记录构造参数与 stop 调用的浏览器管理器替身。"""

    instances: list["_FakeBrowserManager"] = []

    def __init__(self, *, port, browser_choice, browser_path):
        self.port = port
        self.browser_choice = browser_choice
        self.browser_path = browser_path
        self.stopped = False
        _FakeBrowserManager.instances.append(self)

    def stop(self) -> None:
        self.stopped = True

    def status(self):  # pragma: no cover - 本文件不检查状态
        raise AssertionError("不应调用 status")


@pytest.fixture(autouse=True)
def _clean_browser_singleton():
    apply_service.reset_browser_manager()
    _FakeBrowserManager.instances.clear()
    yield
    apply_service.reset_browser_manager()
    _FakeBrowserManager.instances.clear()


def test_changing_browser_choice_rebuilds_and_stops_the_old_manager(db_session, monkeypatch):
    monkeypatch.setattr(apply_service, "BrowserManager", _FakeBrowserManager)

    apply_service.save_apply_config(db_session, ApplyConfigIn(browser_choice="auto"))
    first = apply_service.get_browser_manager(db_session)
    assert len(_FakeBrowserManager.instances) == 1

    # 同配置 → 复用同一实例。
    assert apply_service.get_browser_manager(db_session) is first
    assert len(_FakeBrowserManager.instances) == 1

    # 改 choice → 必须重建，且先 stop 旧实例。
    apply_service.save_apply_config(db_session, ApplyConfigIn(browser_choice="chrome"))
    second = apply_service.get_browser_manager(db_session)
    assert second is not first
    assert len(_FakeBrowserManager.instances) == 2
    assert first.stopped is True
    assert second.browser_choice == "chrome"

    # 改路径 → 再次重建，旧实例被 stop。
    apply_service.save_apply_config(
        db_session, ApplyConfigIn(browser_choice="custom", browser_path="C:/x/y.exe")
    )
    third = apply_service.get_browser_manager(db_session)
    assert len(_FakeBrowserManager.instances) == 3
    assert second.stopped is True
    assert third.browser_path == "C:/x/y.exe"


def test_changing_browser_port_rebuilds(db_session, monkeypatch):
    monkeypatch.setattr(apply_service, "BrowserManager", _FakeBrowserManager)

    apply_service.save_apply_config(db_session, ApplyConfigIn(browser_port=9333))
    first = apply_service.get_browser_manager(db_session)
    apply_service.save_apply_config(db_session, ApplyConfigIn(browser_port=9444))
    second = apply_service.get_browser_manager(db_session)

    assert second is not first
    assert first.stopped is True
    assert second.port == 9444


# ===== 第 5 节：新增站点只需改后端 =====


class DemoAdapter(SiteAdapter):
    """演示用假站点：模拟"以后新增一个招聘网站"。"""

    key = "demo"
    display_name = "演示招聘网"
    hosts = ("demo.example.com",)
    entry_url = "https://demo.example.com/"
    supports_collect = True
    supports_apply = False

    def risk_profile(self) -> RiskProfile:
        return RiskProfile(key=self.key)

    def collect_search(self, client, query, page) -> SearchPage:  # pragma: no cover
        return SearchPage()

    def open_apply(self, client, job) -> None:  # pragma: no cover
        return None

    def fill_and_submit(self, client, data, greeting) -> ApplyOutcome:  # pragma: no cover
        raise AssertionError("演示站点不支持投递")


def _registry_with_demo() -> SiteRegistry:
    registry = SiteRegistry()
    registry.register(BossAdapter())
    registry.register(DemoAdapter())
    return registry


def test_new_site_appears_in_the_sites_endpoint_without_any_frontend_change(client, monkeypatch):
    """后端注册表里加一行，/api/apply/sites 自动多出一个站点——前端一行都不用改。"""
    monkeypatch.setattr(apply_service, "get_registry", _registry_with_demo)

    response = client.get("/api/apply/sites")

    assert response.status_code == 200
    body = response.json()
    keys = [site["key"] for site in body["sites"]]
    assert "boss" in keys and "demo" in keys
    demo = next(site for site in body["sites"] if site["key"] == "demo")
    assert demo["display_name"] == "演示招聘网"
    assert demo["entry_url"] == "https://demo.example.com/"
    assert demo["supports_apply"] is False and demo["supports_collect"] is True
    assert body["current"] == "boss"  # 默认仍是注册表第一个


def test_switching_site_key_moves_default_entry_url_and_current(client, db_session, monkeypatch):
    monkeypatch.setattr(apply_service, "get_registry", _registry_with_demo)

    apply_service.save_apply_config(db_session, ApplyConfigIn(site_key="demo"))

    assert apply_service.current_site_key(db_session) == "demo"
    assert apply_service.default_entry_url(db_session) == "https://demo.example.com/"
    assert client.get("/api/apply/sites").json()["current"] == "demo"


def test_browser_status_reports_the_current_site_entry_url(db_session, monkeypatch):
    """浏览器状态里的"站点入口"要跟着当前站点走（供启动/「打开招聘网站」使用）。"""
    monkeypatch.setattr(apply_service, "get_registry", _registry_with_demo)

    assert apply_service.browser_status(db_session).entry_url == "https://www.zhipin.com/"
    apply_service.save_apply_config(db_session, ApplyConfigIn(site_key="demo"))
    assert apply_service.browser_status(db_session).entry_url == "https://demo.example.com/"


def test_unknown_site_key_is_accepted_then_falls_back_to_the_first_site(db_session, monkeypatch):
    """不存在的 site_key 的行为要钉死：schema 接受，运行期回退到第一个可用站点（不崩）。"""
    monkeypatch.setattr(apply_service, "get_registry", _registry_with_demo)

    # schema 层不把它当非法（界面只从接口拿有效 key；后端口径是"回退"而不是"报错"）。
    assert ApplyConfigIn(site_key="does-not-exist").site_key == "does-not-exist"
    apply_service.save_apply_config(db_session, ApplyConfigIn(site_key="does-not-exist"))

    assert apply_service.current_site_key(db_session) == "boss"
    assert apply_service.default_entry_url(db_session) == "https://www.zhipin.com/"


def test_frontend_production_code_has_no_hardcoded_site_names():
    """前端生产代码（排除 *.test.*）里不得写死站点名 / 站点清单 / 站点 URL。"""
    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    if not root.exists():  # pragma: no cover - 前端不在时跳过
        pytest.skip("未找到 frontend/src")

    forbidden = ("zhipin", "boss直聘", "直聘", "lagou", "51job", "liepin")
    offenders: list[tuple[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if ".test." in name:
            continue
        if path.suffix not in {".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").casefold()
        for token in forbidden:
            if token in text:
                offenders.append((str(path.relative_to(root)), token))

    assert offenders == [], f"前端生产代码里出现了写死的站点信息：{offenders}"
