"""投递专用浏览器管理器：定位、拉起、健康检查、只关闭自己拉起的那个进程。

为什么必须另起一个"专用浏览器"（而不是连用户日常浏览器）：
Chrome 自 136 起**禁止在默认用户数据目录上开启远程调试**，``--remote-debugging-port``
在默认 ``user-data-dir`` 下会被静默忽略。所以后端用**独立的** ``user-data-dir``
（``backend/data/browser-profile/``，已进 ``.gitignore``）拉起一个专用窗口：首次使用时
用户在这个窗口里扫码登录一次，之后登录态以 Chromium 自己的方式持久化在里目录里，应用
**既不读取也不解析**它。

安全与稳健约定：
- 参数一律用**列表**传递、``shell=False``，绝不拼命令行字符串（防注入与路径空格问题）。
- 浏览器由用户显式选择：``auto``（优先 Chrome、未装回退 Edge）/ ``chrome`` / ``edge`` /
  ``custom``（自定义路径）。**明确选了 Chrome 却启动 Edge 是比报错更坏的行为**，所以
  ``chrome`` / ``edge`` 只找对应的那个，找不到就给可展示的中文提示；``custom`` 要求路径真实存在。
- ``stop()`` 只终止**本管理器持有的进程句柄**，不会去按 PID 找进程，避免误杀用户自己的浏览器。
- **"在不在跑"看调试端口，不看进程句柄**（见 :meth:`BrowserManager.is_running`）；"是不是本
  进程拉起的"是另一个独立事实（``BrowserStatus.owned``），只用来决定"关闭浏览器"能不能按。
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ...config import BACKEND_DIR, DEFAULT_BROWSER_PORT
from .cdp_client import DEFAULT_HOST, WebsocketCdpClient

logger = logging.getLogger(__name__)

# 端口默认值的唯一来源是 config.DEFAULT_BROWSER_PORT；此处保留 DEFAULT_PORT 名字兼容现有引用。
DEFAULT_PORT = DEFAULT_BROWSER_PORT
READY_TIMEOUT_SECONDS = 20.0
READY_POLL_INTERVAL = 0.4
PROFILE_DIR_NAME = "browser-profile"

# 常见安装位置（按"优先 Chrome、其次 Edge"的顺序排列）。用环境变量拼，避免把某个
# 用户的绝对路径写死；Windows 之外的平台退回 PATH 查找。
_CHROME_RELATIVE = (
    ("PROGRAMFILES", r"Google\Chrome\Application\chrome.exe"),
    ("PROGRAMFILES(X86)", r"Google\Chrome\Application\chrome.exe"),
    ("LOCALAPPDATA", r"Google\Chrome\Application\chrome.exe"),
)
_EDGE_RELATIVE = (
    ("PROGRAMFILES(X86)", r"Microsoft\Edge\Application\msedge.exe"),
    ("PROGRAMFILES", r"Microsoft\Edge\Application\msedge.exe"),
    ("LOCALAPPDATA", r"Microsoft\Edge\Application\msedge.exe"),
)

_LOGIN_HINT = "首次使用请在弹出的浏览器窗口里扫码登录一次；登录态会保存在专用目录里，下次自动沿用。"

BROWSER_CHOICE_AUTO = "auto"
BROWSER_CHOICE_CHROME = "chrome"
BROWSER_CHOICE_EDGE = "edge"
BROWSER_CHOICE_CUSTOM = "custom"
BROWSER_CHOICES = (
    BROWSER_CHOICE_AUTO,
    BROWSER_CHOICE_CHROME,
    BROWSER_CHOICE_EDGE,
    BROWSER_CHOICE_CUSTOM,
)

# 中文名，供界面展示"实际用的是哪个浏览器"（别只给路径）。
_CHROME_NAME = "Google Chrome"
_EDGE_NAME = "Microsoft Edge"
_CUSTOM_NAME = "自定义浏览器"


def browser_display_name(path: str | Path | None) -> str:
    """由可执行文件路径推断人类可读的浏览器名。"""
    if not path:
        return ""
    name = Path(path).name.casefold()
    if "msedge" in name or "edge" in name:
        return _EDGE_NAME
    if "chrome" in name:
        return _CHROME_NAME
    return _CUSTOM_NAME


class BrowserError(Exception):
    """对外暴露的浏览器错误，message 为可直接展示给用户的中文提示。"""


# ``BrowserStatus.state`` 的取值之一：调试端口在答，采集/投递都能用。
# 定义成常量是因为调用方要拿它做判断（例如"浏览器在跑才去读登录态清单"），
# 而字符串字面量散在各处时，改一处就会漏一处。
BROWSER_STATE_RUNNING = "running"


@dataclass(frozen=True)
class BrowserStatus:
    """浏览器状态快照。"""

    state: str
    port: int
    profile_dir: str
    browser_path: str
    browser_name: str = ""
    logged_in_hint: str = _LOGIN_HINT
    # 这个浏览器是不是**本进程**拉起的。为 False 表示它是上一次运行时打开的窗口：
    # 状态照样是"运行中"（调试端口在答），但 ``stop()`` 关不掉它——本管理器只终止自己
    # 持有的进程句柄，绝不按 PID 去猜进程（那会误杀用户自己的浏览器）。
    owned: bool = False


def default_profile_dir() -> Path:
    """投递专用浏览器的 ``user-data-dir``（与数据库同级的数据目录下）。"""
    return BACKEND_DIR / "data" / PROFILE_DIR_NAME


class BrowserManager:
    """管理"投递专用浏览器"的进程与调试通道。"""

    def __init__(
        self,
        *,
        profile_dir: Path | None = None,
        port: int = DEFAULT_PORT,
        browser_path: str | Path | None = None,
        browser_choice: str = BROWSER_CHOICE_AUTO,
        host: str = DEFAULT_HOST,
        http_transport: httpx.BaseTransport | None = None,
        popen: Callable[..., Any] | None = None,
        env: Mapping[str, str] | None = None,
        client_factory: Callable[..., WebsocketCdpClient] | None = None,
        ready_timeout: float = READY_TIMEOUT_SECONDS,
        ready_poll_interval: float = READY_POLL_INTERVAL,
    ) -> None:
        self._profile_dir = Path(profile_dir) if profile_dir else default_profile_dir()
        self._port = port
        self._browser_path = Path(browser_path) if browser_path else None
        self._browser_choice = browser_choice if browser_choice in BROWSER_CHOICES else BROWSER_CHOICE_AUTO
        self._host = host
        self._http_transport = http_transport
        self._popen = popen or subprocess.Popen
        self._env = env if env is not None else os.environ
        self._client_factory = client_factory or WebsocketCdpClient
        self._ready_timeout = ready_timeout
        self._ready_poll_interval = ready_poll_interval
        self._process: Any | None = None
        self._pid: int | None = None
        self._started_at: float | None = None

    # ===== 浏览器可执行文件定位 =====

    @property
    def profile_dir(self) -> Path:
        return self._profile_dir

    @property
    def port(self) -> int:
        return self._port

    def _existing_env_paths(self, candidates: tuple[tuple[str, str], ...]) -> list[Path]:
        found: list[Path] = []
        for env_name, relative in candidates:
            base = self._env.get(env_name)
            if not base:
                continue
            candidate = Path(base) / relative
            if candidate.is_file():
                found.append(candidate)
        return found

    def _find_one(
        self, candidates: tuple[tuple[str, str], ...], names: tuple[str, ...]
    ) -> Path | None:
        """在给定安装位置与 PATH 里找一个浏览器；找不到返回 ``None``。"""
        import shutil

        for path in self._existing_env_paths(candidates):
            return path
        for name in names:
            located = shutil.which(name)
            if located:
                return Path(located)
        return None

    def _locate_browser(self) -> Path:
        """按用户的选择定位浏览器可执行文件。

        - ``custom``（或显式给了 ``browser_path``）：必须是真实存在的文件，否则中文提示；
        - ``chrome`` / ``edge``：只找对应的那个，找不到就报错——**绝不静默回退到另一个**；
        - ``auto``：优先 Chrome，未装回退 Edge，都找不到才报错。
        """
        # 显式给了自定义路径就一律用它（兼容旧调用：只传 browser_path、不传 choice）。
        if self._browser_choice == BROWSER_CHOICE_CUSTOM or self._browser_path is not None:
            path = self._browser_path
            if path is None or not path.is_file():
                raise BrowserError(
                    f"自定义的浏览器路径不存在或不是文件：{path or '（空）'}；"
                    "请检查路径，或在投递设置里改用「自动 / Chrome / Edge」。"
                )
            return path

        if self._browser_choice == BROWSER_CHOICE_CHROME:
            located = self._find_one(_CHROME_RELATIVE, ("chrome", "google-chrome"))
            if located is None:
                raise BrowserError(
                    "没有找到 Google Chrome：请先安装 Chrome，或在投递设置里改用「自动」"
                    "（会自动回退 Edge）或「自定义路径」。"
                )
            return located

        if self._browser_choice == BROWSER_CHOICE_EDGE:
            located = self._find_one(_EDGE_RELATIVE, ("msedge",))
            if located is None:
                raise BrowserError(
                    "没有找到 Microsoft Edge：请先安装 Edge，或在投递设置里改用「自动」或"
                    "「自定义路径」。"
                )
            return located

        located = self._find_one(_CHROME_RELATIVE, ("chrome", "google-chrome"))
        if located is None:
            located = self._find_one(_EDGE_RELATIVE, ("msedge",))
        if located is None:
            raise BrowserError(
                "未找到可用的浏览器，请先安装 Google Chrome 或 Microsoft Edge 后重试"
            )
        return located

    # ===== 健康检查 =====

    def _probe_ready(self) -> bool:
        """调试端口是否已经就绪（能拿到 /json/version 就说明可以下命令了）。"""
        try:
            with httpx.Client(transport=self._http_transport, timeout=1.0) as client:
                response = client.get(f"http://{self._host}:{self._port}/json/version")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    def _handle_alive(self) -> bool:
        """本管理器拉起的那次启动是否还没退出。

        **只说明"启动过且没退出"**，既不表示能通话，也不表示浏览器还在——句柄只属于
        拉起它的那个后端进程，而浏览器是有意活得比后端久的。
        """
        return self._process is not None and self._process.poll() is None

    def is_running(self) -> bool:
        """现在能不能给浏览器下命令——唯一判据是**调试端口**。

        判据**不能**是 ``self._process``。浏览器是独立的 OS 进程，应用退出时也**不会**去关它
        （登录态持久化在专用 user-data-dir 里，下次启动直接沿用），所以后端一重启句柄就没了；
        按句柄判断会把正在运行的浏览器报成"未启动"。更麻烦的是这时点"启动浏览器"也救不回来：
        同一个 user-data-dir 的第二次启动会被 Chromium **转交给已在运行的实例后立刻退出**，
        句柄依然是死的。端口是唯一外部可观测的真实状态。
        """
        return self._probe_ready()

    def is_active(self) -> bool:
        """是否已经有一个专用浏览器（可用的，或本进程刚拉起、还在启动中的）。

        只在启动那几秒与 :meth:`is_running` 有区别：进程已拉起但调试端口尚未就绪时，
        ``is_running()`` 已经是 False 了。``start()`` 用它防重复拉起。
        """
        return self.is_running() or self._handle_alive()

    def status(self) -> BrowserStatus:
        browser_path = str(self._browser_path) if self._browser_path else ""
        browser_name = browser_display_name(self._browser_path)
        owned = self._handle_alive()
        if not owned:
            # 句柄不可用**不代表浏览器没了**（见 is_running 的说明），这里只清掉死句柄；
            # 到底是"运行中"还是"未启动"由端口决定。
            self._reset_process()
        if self._probe_ready():
            state = BROWSER_STATE_RUNNING
        elif owned:
            state = "starting"
        else:
            state = "stopped"
        return BrowserStatus(
            state,
            self._port,
            str(self._profile_dir),
            browser_path,
            browser_name,
            owned=owned,
        )

    # ===== 启动 / 停止 =====

    def start(self, url: str | None = None) -> BrowserStatus:
        """拉起专用浏览器。

        ``url`` 是启动后要打开的页面。**一定要传**：只开一个 ``about:blank`` 的话，
        用户面对一个空白窗口既不知道该去哪里，也没有可以扫码登录的页面——启动浏览器的
        全部意义就是"打开那个要登录的网站"。
        """
        # 已经是"有浏览器"（端口在答，或本进程刚拉起还在启动）就不再拉第二个。
        if self.is_active():
            return self.status()
        browser = self._locate_browser()
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        # 参数用列表传递、shell=False：不经过 shell，路径含空格也不会被拆开。
        args = [
            str(browser),
            f"--remote-debugging-port={self._port}",
            f"--user-data-dir={self._profile_dir}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            url or "about:blank",
        ]
        try:
            self._process = self._popen(args, shell=False)
        except OSError as exc:
            self._reset_process()
            raise BrowserError(f"启动浏览器失败：{exc}") from exc
        self._pid = getattr(self._process, "pid", None)
        self._started_at = time.time()
        self._browser_path = browser
        logger.info("投递专用浏览器已拉起 pid=%s port=%s", self._pid, self._port)

        if not self._wait_until_ready():
            self.stop()
            raise BrowserError(
                "浏览器已启动但调试端口未就绪，请确认没有被安全软件拦截后重试"
            )
        return self.status()

    def _wait_until_ready(self) -> bool:
        deadline = time.monotonic() + self._ready_timeout
        while time.monotonic() < deadline:
            if self._probe_ready():
                return True
            if self._process is not None and self._process.poll() is not None:
                return False
            time.sleep(self._ready_poll_interval)
        return False

    def _reset_process(self) -> None:
        self._process = None
        self._pid = None
        self._started_at = None

    def stop(self) -> None:
        """终止**本管理器拉起的**浏览器进程；没有拉起过就什么都不做。

        没有句柄时静默返回是**故意的**：后端重启后会丢掉句柄，而浏览器仍在运行，
        此时这里是关不掉它的。绝不按 PID 去猜进程——那会误杀用户自己的浏览器。
        调用方要靠 :attr:`BrowserStatus.owned` 如实告诉用户"请自己关掉那个窗口"，
        而不是假装关成功了。
        """
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except Exception:  # noqa: BLE001 - 超时后再强杀
                    process.kill()
        except Exception as exc:  # noqa: BLE001 - 关闭失败也要复位，不能卡住进程状态
            logger.warning("关闭投递专用浏览器时出错：%s", type(exc).__name__)
        finally:
            self._reset_process()

    # ===== CDP 客户端 =====

    def _require_running(self) -> None:
        """准入检查：端口不通就别往下走，并把"还没起来"和"没启动"分开说。

        两者对用户是**不同的动作**：前者只需等几秒，后者要去点"启动浏览器"（或
        关掉那个抢占了调试端口的程序）。合成一句会把用户指向错的下一步。
        """
        if self.is_running():
            return
        if self._handle_alive():
            raise BrowserError("投递专用浏览器还在启动中，请稍候几秒再试")
        raise BrowserError("请先启动投递专用浏览器，再进行采集或投递")

    def open_url(self, url: str) -> None:
        """在已打开的专用浏览器里导航到 ``url``。

        复用当前标签页（``Page.navigate``）而不是新开一个：用户反复点"打开招聘网站"
        时不该越堆越多标签页，启动时开的那个页就是落脚点。
        """
        self._require_running()
        self.client().navigate(url)

    def client(self) -> WebsocketCdpClient:
        self._require_running()
        return self._client_factory(
            self._host,
            self._port,
            http_transport=self._http_transport,
        )


__all__ = [
    "BROWSER_CHOICE_AUTO",
    "BROWSER_CHOICE_CHROME",
    "BROWSER_CHOICE_CUSTOM",
    "BROWSER_CHOICE_EDGE",
    "BROWSER_CHOICES",
    "BROWSER_STATE_RUNNING",
    "BrowserError",
    "BrowserManager",
    "BrowserStatus",
    "DEFAULT_PORT",
    "browser_display_name",
    "default_profile_dir",
]
