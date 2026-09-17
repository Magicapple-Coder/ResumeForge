"""浏览器桥接层：CDP 客户端 + 投递专用浏览器管理器。

业务层只依赖本层暴露的抽象（``CdpClient`` / ``BrowserManager``），不直接接触
HTTP / WebSocket 细节，因此整条对外链路可以用假传输层离线测试。
"""
from .browser_manager import BrowserError, BrowserManager, BrowserStatus, default_profile_dir
from .cdp_client import CdpClient, CdpError, WebsocketCdpClient

__all__ = [
    "BrowserError",
    "BrowserManager",
    "BrowserStatus",
    "CdpClient",
    "CdpError",
    "WebsocketCdpClient",
    "default_profile_dir",
]
