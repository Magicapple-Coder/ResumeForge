"""应用内下载与安装更新。

下载只写入 ``runtime`` 临时目录，安装脚本会跳过 ``data``、``.env``、``runtime``
等用户数据路径。真正覆盖文件和重启由独立的 PowerShell 进程完成，避免当前 Python
进程一边运行一边替换自己的代码。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import httpx

from ..config import get_settings
from ..schemas.update import UpdateStatus
from .update_check import check_for_update

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DOWNLOAD_DIRECTORY = PROJECT_ROOT / "runtime" / "update-downloads"
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
DOWNLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)


@dataclass
class _MutableStatus:
    state: Literal["idle", "downloading", "ready", "installing", "failed"] = "idle"
    current_version: str = ""
    target_version: str = ""
    progress: float = 0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    background: bool = False
    installable: bool = False
    message: str = ""


_status = _MutableStatus()
_download_task: asyncio.Task[None] | None = None
_archive_path: Path | None = None


def _snapshot() -> UpdateStatus:
    return UpdateStatus(
        state=_status.state,
        current_version=_status.current_version,
        target_version=_status.target_version,
        progress=_status.progress,
        downloaded_bytes=_status.downloaded_bytes,
        total_bytes=_status.total_bytes,
        background=_status.background,
        installable=_status.installable,
        message=_status.message,
    )


def download_status() -> UpdateStatus:
    """返回当前进程内的更新任务状态。"""
    return _snapshot()


def _safe_archive_path(version: str) -> Path:
    safe_version = "".join(char for char in version if char.isalnum() or char in ".-_")[:64]
    return DOWNLOAD_DIRECTORY / f"ResumeForge-{safe_version or 'latest'}.zip"


def _validate_archive(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name.replace("\\", "/") for name in archive.namelist()]
            for name in names:
                parts = PurePosixPath(name).parts
                if PurePosixPath(name).is_absolute() or ".." in parts:
                    raise ValueError("更新包包含不安全的路径，已拒绝安装")
            if not any(name.endswith("/start.cmd") or name == "start.cmd" for name in names):
                raise ValueError("更新包缺少 start.cmd，无法确认它是 ResumeForge 安装包")
            if not any(name.endswith("/backend/app/main.py") for name in names):
                raise ValueError("更新包缺少后端入口，无法确认它是完整安装包")
            if archive.testzip() is not None:
                raise ValueError("更新包校验失败，压缩包可能已损坏")
    except zipfile.BadZipFile as exc:
        raise ValueError("下载的更新包不是有效 ZIP 文件") from exc


async def _download_archive(url: str, expected_size: int | None, target: Path) -> None:
    DOWNLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    headers = {"Accept": "application/octet-stream", "User-Agent": "ResumeForge-updater"}
    try:
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"下载服务器返回 HTTP {response.status_code}")
                header_size = response.headers.get("Content-Length")
                total = int(header_size) if header_size and header_size.isdigit() else expected_size
                _status.total_bytes = total
                with partial.open("wb") as handle:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        _status.downloaded_bytes += len(chunk)
                        if _status.downloaded_bytes > MAX_DOWNLOAD_BYTES:
                            raise RuntimeError("更新包超过 512 MB，已停止下载")
                        handle.write(chunk)
                        if total:
                            _status.progress = min(99.0, _status.downloaded_bytes * 100 / total)
        _validate_archive(partial)
        os.replace(partial, target)
    except Exception:
        logger.exception("下载更新包失败")
        raise


async def _run_download(url: str, expected_size: int | None, target: Path) -> None:
    try:
        await _download_archive(url, expected_size, target)
        _status.progress = 100
        _status.state = "ready"
        _status.installable = True
        _status.message = "更新包已下载完成，可以重启安装"
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _status.state = "failed"
        _status.installable = False
        _status.message = str(exc)[:1000]


async def start_download(*, background: bool = False) -> UpdateStatus:
    """启动一次下载；重复点击不会创建第二个下载任务。"""
    global _download_task, _archive_path
    if _status.state in {"downloading", "installing"}:
        return _snapshot()
    result = await check_for_update()
    if not result.update_available:
        raise RuntimeError(result.message or "当前没有可用更新")
    if not result.installable or not result.download_url:
        raise RuntimeError("这个版本没有可安装的完整更新包，请打开发布页面手动下载")

    target = _safe_archive_path(result.latest_version)
    _archive_path = target
    if target.is_file():
        try:
            _validate_archive(target)
        except ValueError:
            pass
        else:
            _status.state = "ready"
            _status.current_version = get_settings().app_version
            _status.target_version = result.latest_version
            _status.progress = 100
            _status.downloaded_bytes = target.stat().st_size
            _status.total_bytes = target.stat().st_size
            _status.background = background
            _status.installable = True
            _status.message = "更新包已下载完成，可以重启安装"
            return _snapshot()

    _status.state = "downloading"
    _status.current_version = get_settings().app_version
    _status.target_version = result.latest_version
    _status.progress = 0
    _status.downloaded_bytes = 0
    _status.total_bytes = result.download_size
    _status.background = background
    _status.installable = False
    _status.message = "正在下载更新包"
    _download_task = asyncio.create_task(
        _run_download(result.download_url, result.download_size, target)
    )
    return _snapshot()


def _read_frontend_pid() -> int | None:
    path = PROJECT_ROOT / "runtime" / "frontend.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        pid = int(value.get("process_id", 0))
        return pid if pid > 0 and pid != os.getpid() else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


async def _stop_current_backend() -> None:
    await asyncio.sleep(1.0)
    # The response has already left the socket. The updater waits for this PID,
    # then stops the recorded Vite tree and starts the launcher again.
    os._exit(0)


def schedule_install(*, restart: bool = True) -> UpdateStatus:
    """启动独立更新器；更新器会等当前服务退出后覆盖文件。"""
    global _status
    if _status.state != "ready" or _archive_path is None or not _archive_path.is_file():
        raise RuntimeError("更新包还没有下载完成")
    if os.name != "nt":
        raise RuntimeError("应用内覆盖安装目前只支持 Windows；其它系统请按升级文档操作")

    script = PROJECT_ROOT / "scripts" / "Update-ResumeForge.ps1"
    if not script.is_file():
        raise RuntimeError("找不到更新脚本，无法安全覆盖安装")
    arguments = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-ArchivePath",
        str(_archive_path),
        "-WaitForPids",
        str(os.getpid()),
    ]
    frontend_pid = _read_frontend_pid()
    if frontend_pid:
        arguments.extend(["-StopPids", str(frontend_pid)])
    if restart:
        arguments.append("-Restart")
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess, "DETACHED_PROCESS", 0
    )
    try:
        subprocess.Popen(
            arguments,
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
    except OSError as exc:
        raise RuntimeError(f"启动更新器失败：{exc}") from exc

    _status.state = "installing"
    _status.installable = False
    _status.message = "更新器已启动，应用即将重启"
    asyncio.create_task(_stop_current_backend())
    return _snapshot()


__all__ = ["download_status", "schedule_install", "start_download"]
