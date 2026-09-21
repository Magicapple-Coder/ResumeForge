"""投递专用浏览器管理器离线测试：注入假 subprocess 与假 HTTP 传输层。

重点验证三条设计纪律：
- 拉起浏览器时参数是**列表**且 ``shell=False``（防注入与路径空格问题）；
- 用**独立 user-data-dir**（Chrome 136+ 的硬约束）；
- ``stop()`` 只终止**本管理器自己拉起的那个进程**（持有句柄，不按 PID 满世界找）。
"""
from pathlib import Path

import httpx
import pytest

from app.services.browser.browser_manager import (
    BROWSER_CHOICE_CHROME,
    BROWSER_CHOICE_CUSTOM,
    BROWSER_CHOICE_EDGE,
    BrowserError,
    BrowserManager,
    browser_display_name,
    default_profile_dir,
)
from app.services.browser.cdp_client import WebsocketCdpClient


class FakeProcess:
    def __init__(self, pid: int = 4321, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        self.waited = True
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class FakePopen:
    """记录调用参数的假 ``subprocess.Popen``。"""

    def __init__(self, returncode: int | None = None) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.processes: list[FakeProcess] = []
        self._returncode = returncode

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        process = FakeProcess(returncode=self._returncode)
        self.processes.append(process)
        return process


def _transport(
    popen: FakePopen | None = None, *, listening: bool | None = None
) -> httpx.MockTransport:
    """假的 ``/json/version`` 端点（也就是"调试端口上有没有人在答"）。

    ``listening`` 显式给定时按它答；不给时**按记录的进程存活推断**——真实的浏览器进程
    一退出，调试端口就跟着没了。这条忠实性很要紧：只有它才能区分"句柄丢了但浏览器还在
    跑"和"浏览器真的没了"这两种在界面上结果完全不同的状态（前者是"运行中"，后者是
    "未启动"）。用一个永远返回 200 的假端点去测，两种状态就分不开了。

    一个进程都没记录过、又没显式指定时算"端口上没人"；要模拟"浏览器由上一次运行拉起"
    （本进程没有句柄）就显式传 ``listening=True``。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/json/version":
            return httpx.Response(404)
        if listening is not None:
            answering = listening
        else:
            last = popen.processes[-1] if popen is not None and popen.processes else None
            answering = last is not None and last.returncode is None
        return httpx.Response(
            200 if answering else 503, json={"Browser": "Chrome"} if answering else {}
        )

    return httpx.MockTransport(handler)


def _browser_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "chrome.exe"
    exe.write_text("")
    return exe


def _manager(tmp_path: Path, **overrides) -> tuple[BrowserManager, FakePopen]:
    popen = overrides.pop("popen", None) or FakePopen()
    kwargs = {
        "profile_dir": tmp_path / "profile",
        "port": 9333,
        "browser_path": _browser_exe(tmp_path),
        "popen": popen,
        # 端口是否应答跟着假进程的存活走，和真实浏览器一致。
        "http_transport": _transport(popen),
        "ready_timeout": 0.3,
        "ready_poll_interval": 0.01,
    }
    kwargs.update(overrides)
    return BrowserManager(**kwargs), popen


def test_default_profile_dir_lives_under_backend_data():
    path = default_profile_dir()

    assert path.name == "browser-profile"
    assert path.parent.name == "data"


def test_locate_browser_prefers_chrome_over_edge(tmp_path):
    program_files = tmp_path / "pf"
    (program_files / "Google" / "Chrome" / "Application").mkdir(parents=True)
    chrome = program_files / "Google" / "Chrome" / "Application" / "chrome.exe"
    chrome.write_text("")
    (program_files / "Microsoft" / "Edge" / "Application").mkdir(parents=True)
    (program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe").write_text("")

    manager = BrowserManager(
        profile_dir=tmp_path / "profile",
        browser_path=None,
        env={"PROGRAMFILES": str(program_files)},
        popen=FakePopen(),
        http_transport=_transport(),
    )

    assert manager._locate_browser() == chrome


def test_locate_browser_falls_back_to_edge(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    program_files = tmp_path / "pf"
    (program_files / "Microsoft" / "Edge" / "Application").mkdir(parents=True)
    edge = program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.write_text("")

    manager = BrowserManager(
        profile_dir=tmp_path / "profile",
        browser_path=None,
        env={"PROGRAMFILES": str(program_files)},
        popen=FakePopen(),
        http_transport=_transport(),
    )

    assert manager._locate_browser() == edge


def test_locate_browser_reports_a_chinese_hint_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    manager = BrowserManager(
        profile_dir=tmp_path / "profile",
        browser_path=None,
        env={},
        popen=FakePopen(),
        http_transport=_transport(),
    )

    with pytest.raises(BrowserError, match="未找到可用的浏览器"):
        manager._locate_browser()


def test_start_launches_with_a_list_and_no_shell(tmp_path):
    manager, popen = _manager(tmp_path)

    status = manager.start()

    args, kwargs = popen.calls[0]
    assert isinstance(args, list)
    assert kwargs["shell"] is False
    assert args[0].endswith("chrome.exe")
    assert "--remote-debugging-port=9333" in args
    assert any(arg.startswith("--user-data-dir=") for arg in args)
    # 独立 user-data-dir：Chrome 136+ 的硬约束。
    assert str(tmp_path / "profile") in next(a for a in args if a.startswith("--user-data-dir="))
    assert (tmp_path / "profile").is_dir()
    assert status.state == "running"


def test_start_is_a_noop_when_already_running(tmp_path):
    manager, popen = _manager(tmp_path)
    manager.start()

    status = manager.start()

    assert len(popen.calls) == 1  # 没有重复拉起
    assert status.state == "running"


def test_start_fails_when_the_debug_port_never_opens(tmp_path):
    manager, popen = _manager(
        tmp_path, http_transport=_transport(listening=False), ready_timeout=0.1
    )

    with pytest.raises(BrowserError, match="调试端口未就绪"):
        manager.start()

    # 启动失败要把已经拉起的进程收回去，不能留一个半死的浏览器。
    assert popen.processes[0].terminated is True


def test_stop_terminates_only_the_recorded_process(tmp_path):
    manager, popen = _manager(tmp_path)
    manager.start()

    manager.stop()

    assert popen.processes[0].terminated is True
    # 端口随进程一起消失（假传输层耦合了进程存活），所以是"未启动"。
    assert manager.status().state == "stopped"
    # 再停一次不应报错（幂等）。
    manager.stop()


def test_status_reports_stopped_after_the_process_exits(tmp_path):
    manager, popen = _manager(tmp_path)
    manager.start()
    popen.processes[0].returncode = 1  # 用户手动关掉了窗口（调试端口随之消失）

    assert manager.status().state == "stopped"
    assert manager.is_running() is False


def test_status_reports_starting_when_the_port_is_not_ready_yet(tmp_path):
    manager, _popen = _manager(tmp_path)
    manager.start()
    # 进程还活着，但调试端口暂时探不通：应报告"正在启动"而不是"运行中"。
    manager._http_transport = _transport(listening=False)

    assert manager.status().state == "starting"


def test_client_distinguishes_still_booting_from_not_started(tmp_path):
    """两种"不能用"要给不同的下一步：一个只需等几秒，一个要去点"启动浏览器"。"""
    manager, _popen = _manager(tmp_path)
    manager.start()
    manager._http_transport = _transport(listening=False)

    with pytest.raises(BrowserError, match="还在启动中"):
        manager.client()


# ===== 浏览器比后端活得久：状态看端口，不看句柄 =====
# 真实踩过的坑。浏览器是独立的 OS 进程，且**有意**活得比后端久（登录态持久化在专用
# user-data-dir 里），所以后端一重启就没有它的进程句柄了。此时若按句柄判断，一个正在
# 运行的浏览器会被报成"未启动"，采集与投递全被拦住；而且点"启动浏览器"也救不回来——
# 同一个 user-data-dir 的第二次启动会被 Chromium **转交给已在运行的实例后立刻退出**，
# 句柄依然是死的，按多少次都没用。下面几条把这个不变量钉住。


def _orphan_browser(tmp_path: Path) -> tuple[BrowserManager, FakePopen]:
    """模拟"端口上跑着一个不是本进程拉起的浏览器"（后端重启后的真实处境）。"""
    popen = FakePopen()
    manager, _ = _manager(tmp_path, popen=popen, http_transport=_transport(listening=True))
    assert manager._process is None  # 前提：本进程确实没有它的句柄
    return manager, popen


def test_is_running_is_port_based_not_handle_based(tmp_path):
    manager, _popen = _orphan_browser(tmp_path)

    assert manager.is_running() is True
    status = manager.status()
    assert status.state == "running"
    # 能用，但关不掉——"归谁"是独立于"在不在跑"的另一个事实。
    assert status.owned is False


def test_status_marks_a_browser_this_process_launched_as_owned(tmp_path):
    manager, _popen = _manager(tmp_path)
    manager.start()

    assert manager.status().owned is True


def test_client_works_when_the_browser_was_launched_by_a_previous_run(tmp_path):
    """这一条直接对应报障：采集不该因为后端重启过就被拦住。"""
    manager, _popen = _orphan_browser(tmp_path)

    client = manager.client()  # 不该抛 BrowserError

    assert isinstance(client, WebsocketCdpClient)
    assert client._port == 9333


def test_start_reuses_an_already_running_browser_instead_of_launching_a_second(tmp_path):
    """端口已经在答时点"启动浏览器"，不该再拉一个进程。

    再拉一次的后果不只是多一个进程：Chromium 会把这次启动**转交给已在运行的实例**然后
    自己退出，于是句柄仍是死的、状态仍是"未启动"，用户按多少次都没用。
    """
    manager, popen = _orphan_browser(tmp_path)

    status = manager.start(url="https://www.zhipin.com/")

    assert popen.calls == []
    assert status.state == "running"


def test_start_still_guards_against_a_double_launch_while_booting(tmp_path):
    """端口还没就绪、进程已经拉起时也不能再拉一个——这是 is_active 存在的理由。"""
    manager, popen = _manager(tmp_path)
    manager.start()
    assert len(popen.calls) == 1
    # 制造"进程活着、调试端口暂时探不通"的启动中间态。
    manager._http_transport = _transport(listening=False)

    assert manager.is_running() is False
    assert manager.is_active() is True
    assert manager.status().state == "starting"

    manager.start()

    assert len(popen.calls) == 1  # 没有第二次拉起


def test_client_requires_a_running_browser(tmp_path):
    manager, _popen = _manager(tmp_path)

    with pytest.raises(BrowserError, match="请先启动投递专用浏览器"):
        manager.client()


def test_client_returns_a_cdp_client_when_running(tmp_path):
    manager, _popen = _manager(tmp_path)
    manager.start()

    client = manager.client()

    assert isinstance(client, WebsocketCdpClient)
    assert client._port == 9333


def test_client_uses_the_configured_factory(tmp_path):
    created: list[tuple] = []

    def factory(host, port, *, http_transport=None):
        created.append((host, port, http_transport))
        return "SENTINEL"

    manager, _popen = _manager(tmp_path, client_factory=factory)
    manager.start()
    client = manager.client()

    assert client == "SENTINEL"
    assert created and created[0][1] == 9333


# ===== 启动时就打开站点入口 =====
# 只拉一个 about:blank 的空白窗口是没有用的：用户面对白页既不知道去哪，
# 也没有可以扫码登录的页面。所以拉起时必须带上目标地址。


def test_start_opens_the_given_url_instead_of_a_blank_page(tmp_path):
    manager, popen = _manager(tmp_path)
    entry = "https://www.zhipin.com/"

    manager.start(url=entry)

    args, _kwargs = popen.calls[0]
    assert args[-1] == entry
    assert "about:blank" not in args


def test_start_falls_back_to_a_blank_page_when_no_url_is_known(tmp_path):
    manager, popen = _manager(tmp_path)

    manager.start()

    args, _kwargs = popen.calls[0]
    assert args[-1] == "about:blank"


def test_open_url_navigates_the_existing_tab_instead_of_opening_a_new_one(tmp_path):
    """反复点「打开招聘网站」不该越堆越多标签页，所以走 Page.navigate。"""
    calls: list[tuple[str, dict]] = []

    class FakeClient:
        def navigate(self, url, **_kwargs):
            calls.append(("navigate", {"url": url}))
            return {}

        def new_tab(self, url="about:blank"):  # pragma: no cover - 不该被调用
            raise AssertionError("open_url 不应该新开标签页")

    manager, _popen = _manager(tmp_path, client_factory=lambda *a, **k: FakeClient())
    manager.start(url="https://www.zhipin.com/")

    manager.open_url("https://www.zhipin.com/")

    assert calls == [("navigate", {"url": "https://www.zhipin.com/"})]


def test_open_url_requires_a_running_browser(tmp_path):
    manager, _popen = _manager(tmp_path)

    with pytest.raises(BrowserError, match="请先启动投递专用浏览器"):
        manager.open_url("https://www.zhipin.com/")


# ===== 功能 1：用户自选浏览器 =====
# 明确选了 Chrome 却启动 Edge 是比报错更坏的行为，所以指定了浏览器就只找那一个。


def _env_with(tmp_path: Path, *which: str) -> dict[str, str]:
    """构造一个只装了指定浏览器的假安装环境。"""
    program_files = tmp_path / "pf"
    env: dict[str, str] = {"PROGRAMFILES": str(program_files)}
    if "chrome" in which:
        (program_files / "Google" / "Chrome" / "Application").mkdir(parents=True)
        (program_files / "Google" / "Chrome" / "Application" / "chrome.exe").write_text("")
    if "edge" in which:
        (program_files / "Microsoft" / "Edge" / "Application").mkdir(parents=True)
        (program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe").write_text("")
    return env


def test_choice_chrome_finds_only_chrome(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    manager = BrowserManager(
        profile_dir=tmp_path / "profile",
        browser_path=None,
        browser_choice=BROWSER_CHOICE_CHROME,
        env=_env_with(tmp_path, "chrome", "edge"),
        popen=FakePopen(),
        http_transport=_transport(),
    )

    located = manager._locate_browser()

    assert located.name == "chrome.exe"


def test_choice_chrome_does_not_silently_fall_back_to_edge(tmp_path, monkeypatch):
    """明确选 Chrome 但只装了 Edge：必须报中文错，绝不静默启动 Edge。"""
    monkeypatch.setattr("shutil.which", lambda _name: None)
    manager = BrowserManager(
        profile_dir=tmp_path / "profile",
        browser_path=None,
        browser_choice=BROWSER_CHOICE_CHROME,
        env=_env_with(tmp_path, "edge"),
        popen=FakePopen(),
        http_transport=_transport(),
    )

    with pytest.raises(BrowserError) as excinfo:
        manager._locate_browser()

    assert "Google Chrome" in str(excinfo.value)
    assert "自定义路径" in str(excinfo.value)


def test_choice_edge_does_not_silently_fall_back_to_chrome(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    manager = BrowserManager(
        profile_dir=tmp_path / "profile",
        browser_path=None,
        browser_choice=BROWSER_CHOICE_EDGE,
        env=_env_with(tmp_path, "chrome"),
        popen=FakePopen(),
        http_transport=_transport(),
    )

    with pytest.raises(BrowserError) as excinfo:
        manager._locate_browser()

    assert "Microsoft Edge" in str(excinfo.value)


def test_choice_edge_finds_only_edge(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    manager = BrowserManager(
        profile_dir=tmp_path / "profile",
        browser_path=None,
        browser_choice=BROWSER_CHOICE_EDGE,
        env=_env_with(tmp_path, "chrome", "edge"),
        popen=FakePopen(),
        http_transport=_transport(),
    )

    assert manager._locate_browser().name == "msedge.exe"


def test_custom_path_must_exist(tmp_path):
    manager = BrowserManager(
        profile_dir=tmp_path / "profile",
        browser_path=tmp_path / "does-not-exist.exe",
        browser_choice=BROWSER_CHOICE_CUSTOM,
        popen=FakePopen(),
        http_transport=_transport(),
    )

    with pytest.raises(BrowserError, match="不存在或不是文件"):
        manager._locate_browser()


def test_custom_path_is_used_when_it_exists(tmp_path):
    exe = tmp_path / "mybrowser.exe"
    exe.write_text("")
    manager = BrowserManager(
        profile_dir=tmp_path / "profile",
        browser_path=exe,
        browser_choice=BROWSER_CHOICE_CUSTOM,
        popen=FakePopen(),
        http_transport=_transport(),
    )

    assert manager._locate_browser() == exe


def test_status_reports_a_human_readable_browser_name(tmp_path):
    manager, _popen = _manager(tmp_path)

    manager.start()

    status = manager.status()
    assert status.browser_name == "Google Chrome"
    assert status.browser_path.endswith("chrome.exe")


def test_browser_display_name_classifies_paths():
    assert browser_display_name("C:/x/msedge.exe") == "Microsoft Edge"
    assert browser_display_name("C:/x/chrome.exe") == "Google Chrome"
    assert browser_display_name("C:/x/other.exe") == "自定义浏览器"
    assert browser_display_name("") == ""
