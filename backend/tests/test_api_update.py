"""应用内更新检查、下载状态与更新包校验的离线测试。"""

import asyncio
import zipfile

import pytest

from app.schemas.update import UpdateCheckResult
from app.services import update_download
from app.services.update_check import clear_cache


def _valid_archive(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ResumeForge/start.cmd", "@echo off")
        archive.writestr("ResumeForge/backend/app/main.py", "app = None")


def test_update_check_exposes_a_downloadable_release(client, monkeypatch):
    async def fake_release(_repo: str) -> dict:
        return {
            "tag_name": "v99.0.0",
            "name": "测试更新",
            "html_url": "https://github.com/example/ResumeForge/releases/tag/v99.0.0",
            "published_at": "2026-09-24T00:00:00Z",
            "body": "修复测试",
            "assets": [
                {
                    "name": "ResumeForge-99.0.0.zip",
                    "browser_download_url": "https://example.com/ResumeForge-99.0.0.zip",
                    "size": 1234,
                }
            ],
        }

    clear_cache()
    monkeypatch.setattr("app.services.update_check._fetch_latest_release", fake_release)
    response = client.get("/api/update/check?refresh=true")

    assert response.status_code == 200
    body = response.json()
    assert body["update_available"] is True
    assert body["download_url"].endswith("ResumeForge-99.0.0.zip")
    assert body["download_size"] == 1234
    assert body["installable"] is True


def test_update_check_falls_back_to_the_redirect_probe_when_the_api_is_blocked(
    client, monkeypatch
):
    """用户报的 "HTTP 403" 走的正是这条路：API 不通，但版本号照样答得出来。

    api.github.com 被限流/被网络拦掉时，「检查更新」不该只回一句错误——用户点它
    想知道的就是"有没有新版本"。备用方式不碰 API，读 github.com 的 302 拿 tag。
    """
    clear_cache()

    async def blocked(_repo: str) -> dict:
        raise RuntimeError("GitHub 拒绝了这次匿名请求（HTTP 403）")

    async def fake_tag(_repo: str) -> str:
        return "v99.0.0"

    monkeypatch.setattr("app.services.update_check._fetch_latest_release", blocked)
    monkeypatch.setattr("app.services.update_check._fetch_latest_tag_via_redirect", fake_tag)

    body = client.get("/api/update/check?refresh=true").json()
    assert body["update_available"] is True
    assert body["latest_version"] == "99.0.0"
    assert "备用方式" in body["message"]
    # 备用方式拿不到附件，所以不能声称可以一键更新。
    assert body["installable"] is False
    assert body["release_url"].endswith("/releases")


def test_update_check_says_what_403_means_when_both_paths_fail(client, monkeypatch):
    """两条路都失败时，错误信息必须能让人判断"等一会儿"还是"换网络"。"""
    clear_cache()

    async def blocked(_repo: str) -> dict:
        raise RuntimeError("GitHub 拒绝了这次匿名请求（HTTP 403）：常见原因是同一网络下匿名调用次数用完，或网络内有人拦了 api.github.com")

    async def also_blocked(_repo: str) -> str:
        raise RuntimeError("GitHub 拒绝了这次匿名请求（HTTP 403）")

    monkeypatch.setattr("app.services.update_check._fetch_latest_release", blocked)
    monkeypatch.setattr("app.services.update_check._fetch_latest_tag_via_redirect", also_blocked)

    body = client.get("/api/update/check?refresh=true").json()
    assert body["update_available"] is False
    assert "403" in body["message"]
    assert "备用方式" in body["message"]
    # 两条路都失败时也要给出"接下来怎么办"：稍后再点一次，或手动看图。
    assert "稍后再点一次" in body["message"]


def test_update_check_treats_a_missing_release_as_no_release(client, monkeypatch):
    """仓库还没发过 Release：两条路都应给出"没有 Release"而不是"检查失败"。"""
    clear_cache()

    async def missing(_repo: str) -> dict:
        raise LookupError("仓库还没有发布任何 Release")

    monkeypatch.setattr("app.services.update_check._fetch_latest_release", missing)
    body = client.get("/api/update/check?refresh=true").json()
    assert "还没有发布任何 Release" in body["message"]


def test_update_api_reports_idle_and_rejects_install_before_download(client):
    status = client.get("/api/update/download-status")
    assert status.status_code == 200
    assert status.json()["state"] == "idle"

    response = client.post("/api/update/install", json={"restart": True})
    assert response.status_code == 409
    assert "下载完成" in response.json()["detail"]


def test_update_archive_rejects_path_traversal(tmp_path):
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "不要写出去")
        archive.writestr("ResumeForge/start.cmd", "@echo off")
        archive.writestr("ResumeForge/backend/app/main.py", "app = None")

    with pytest.raises(ValueError, match="不安全的路径"):
        update_download._validate_archive(archive_path)


@pytest.mark.asyncio
async def test_download_task_validates_archive_and_reports_ready(tmp_path, monkeypatch):
    update_download._status = update_download._MutableStatus()
    update_download._download_task = None
    update_download._archive_path = None
    monkeypatch.setattr(update_download, "DOWNLOAD_DIRECTORY", tmp_path)

    async def fake_check_for_update():
        return UpdateCheckResult(
            current_version="0.11.0",
            latest_version="99.0.0",
            update_available=True,
            download_url="https://example.com/update.zip",
            download_size=128,
            asset_name="ResumeForge-99.0.0.zip",
            installable=True,
        )

    async def fake_download(_url: str, _size: int | None, target):
        _valid_archive(target)

    monkeypatch.setattr(update_download, "check_for_update", fake_check_for_update)
    monkeypatch.setattr(update_download, "_download_archive", fake_download)

    initial = await update_download.start_download(background=True)
    assert initial.state == "downloading"
    assert initial.background is True
    assert update_download._download_task is not None
    await asyncio.wait_for(update_download._download_task, timeout=1)

    final = update_download.download_status()
    assert final.state == "ready"
    assert final.progress == 100
    assert final.installable is True
