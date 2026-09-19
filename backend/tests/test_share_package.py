"""离线分享包（R-18）：脱敏快照 + 文件清单 + 本地 token + 评论回传。

分享包是生成那一刻的只读快照：文件落本地目录（测试库 → 临时目录）、token 可校验、
评论只在 ``comment`` 权限下附带并可导入回传。
"""
import json
from pathlib import Path

from app.api import share_packages as share_packages_api
from app.services.share_package import (
    share_package_or_none,
    verify_share_token,
)


def _manual_resume(client, content: dict, title: str = "测试") -> int:
    response = client.post(
        "/api/resumes/manual",
        json={"title": title, "content": content, "job_id": None},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_package(client, resume_id: int, **overrides) -> dict:
    payload = {"resume_id": resume_id, "permission": "read_only"}
    payload.update(overrides)
    response = client.post("/api/share-packages", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_share_package_redacts_snapshot_and_writes_files(client):
    resume_id = _manual_resume(
        client,
        {
            "name": "张三",
            "phone": "13800000000",
            "email": "a@example.com",
            "summary": "负责后端服务。",
            "experience": [{"company": "字节跳动", "role": "工程师", "description": ["实现检索接口"]}],
        },
    )

    body = _create_package(client, resume_id)

    assert body["share_token"]
    assert body["permission"] == "read_only"
    # 只读快照已脱敏：姓名 / 手机 / 邮箱 / 公司都不出现真实值。
    assert body["snapshot"]["name"] == "***"
    assert body["snapshot"]["phone"] == "***"
    assert body["snapshot"]["experience"][0]["company"] == "***"
    # 快照不含照片 data URL（与 export_json 同口径）。
    assert "photo" not in body["snapshot"]

    names = {item["name"] for item in body["files"]}
    assert {"resume.html", "resume.pdf", "resume_snapshot.json", "manifest.json"} <= names

    # 文件确实落在本地目录里。
    directory = Path(body["files"][0]["path"]).parent
    assert directory.is_dir()
    assert (directory / "resume.html").is_file()
    assert (directory / "resume.pdf").is_file()
    # manifest 里带本地 token，可离线校验。
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["share_token"] == body["share_token"]


def test_share_package_list_and_detail_with_download_urls(client):
    resume_id = _manual_resume(client, {"name": "张三", "summary": "关注后端。"})
    _create_package(client, resume_id)

    listing = client.get("/api/share-packages")
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert listing.json()[0]["file_count"] >= 4

    share_id = listing.json()[0]["id"]
    detail = client.get(f"/api/share-packages/{share_id}")
    assert detail.status_code == 200
    assert detail.json()["files"][0]["download_url"].startswith(f"/api/share-packages/{share_id}/files/")


def test_read_only_has_no_comments_file(client):
    resume_id = _manual_resume(client, {"name": "张三"})
    body = _create_package(client, resume_id, permission="read_only")

    assert body["comments_file"] == ""
    assert not any(item["name"].startswith("comments.") for item in body["files"])


def test_comment_permission_bundles_comments_and_imports_roundtrip(client):
    resume_id = _manual_resume(client, {"name": "张三"})
    body = _create_package(client, resume_id, permission="comment")

    assert body["comments_file"]
    assert any(item["name"] == "comments.md" for item in body["files"])

    share_id = body["id"]
    comments = client.get(f"/api/share-packages/{share_id}/comments")
    assert comments.status_code == 200
    assert body["share_token"] in comments.json()["content"]

    imported = client.post(
        f"/api/share-packages/{share_id}/comments/import",
        json={"content": "# 评论\n写得不错。", "format": "markdown"},
    )
    assert imported.status_code == 200
    assert "写得不错" in imported.json()["content"]


def test_json_comments_import_rejects_invalid_json(client):
    resume_id = _manual_resume(client, {"name": "张三"})
    body = _create_package(client, resume_id, permission="comment")

    response = client.post(
        f"/api/share-packages/{body['id']}/comments/import",
        json={"content": "这不是 JSON", "format": "json"},
    )
    assert response.status_code == 422


def test_json_comments_import_accepts_valid_json(client):
    resume_id = _manual_resume(client, {"name": "张三"})
    body = _create_package(client, resume_id, permission="comment")

    response = client.post(
        f"/api/share-packages/{body['id']}/comments/import",
        json={"content": '{"rating": 5, "note": "写得不错"}', "format": "json"},
    )

    assert response.status_code == 200
    assert response.json()["format"] == "json"
    assert "写得不错" in response.json()["content"]


def test_share_package_file_download_and_path_traversal_guard(client):
    resume_id = _manual_resume(client, {"name": "张三", "summary": "关注后端。"})
    body = _create_package(client, resume_id)
    share_id = body["id"]

    html_file = next(item for item in body["files"] if item["name"] == "resume.html")
    response = client.get(f"/api/share-packages/{share_id}/files/resume.html")
    assert response.status_code == 200
    assert "张三" not in response.text  # 已脱敏
    assert html_file["sha256"]

    # 目录穿越必须被挡下（只取 basename，且必须落在分享包目录内）。
    traversal = client.get(f"/api/share-packages/{share_id}/files/..%2Fresume_forge.db")
    assert traversal.status_code == 404


def test_create_share_package_unknown_resume_is_404(client):
    response = client.post("/api/share-packages", json={"resume_id": 999999})
    assert response.status_code == 404


def test_share_package_full_trash_cycle(client):
    """分享包走完整闭环：删除 → 进回收站 → 恢复 → 再删 → 彻底删除（防「半软删」回归）。"""
    resume_id = _manual_resume(client, {"name": "张三"})
    created = client.post("/api/share-packages", json={"resume_id": resume_id})
    assert created.status_code == 201, created.text
    share_id = created.json()["id"]

    # ① 删除 → 分享包列表消失。
    assert client.delete(f"/api/share-packages/{share_id}").status_code == 204
    assert client.get("/api/share-packages").json() == []

    # ② 出现在回收站，带「分享包」类型标签。
    summary = client.get("/api/trash").json()
    mine = [item for item in summary["items"] if item["type"] == "share_package"]
    assert [item["id"] for item in mine] == [share_id]
    assert mine[0]["type_label"] == "分享包"

    # ③ 恢复 → 分享包列表回来。
    assert client.post(f"/api/trash/share_package/{share_id}/restore").status_code == 204
    assert len(client.get("/api/share-packages").json()) == 1

    # ④ 再删 → 彻底删除（不可恢复）。
    assert client.delete(f"/api/share-packages/{share_id}").status_code == 204
    assert client.delete(f"/api/trash/share_package/{share_id}").status_code == 204
    assert client.get("/api/trash").json()["items"] == []
    assert client.get("/api/share-packages").json() == []


def test_share_token_is_locally_verifiable(client, db_session):
    resume_id = _manual_resume(client, {"name": "张三"})
    body = _create_package(client, resume_id)

    package = share_package_or_none(db_session, body["id"])
    assert package is not None
    assert verify_share_token(package, body["share_token"]) is True
    assert verify_share_token(package, "wrong-token") is False
    assert verify_share_token(package, "") is False


# ===== 「打开所在文件夹」 =====


def test_reveal_missing_package_returns_404(client):
    response = client.post("/api/share-packages/999999/reveal")
    assert response.status_code == 404


def test_reveal_opens_directory_on_windows(client, monkeypatch):
    resume_id = _manual_resume(client, {"name": "张三"})
    body = _create_package(client, resume_id)
    directory = Path(body["files"][0]["path"]).parent

    calls: list[list[str]] = []

    def fake_popen(args, **_kwargs):
        calls.append(args)
        return None

    monkeypatch.setattr(share_packages_api, "_is_windows", lambda: True)
    monkeypatch.setattr(share_packages_api.subprocess, "Popen", fake_popen)

    response = client.post(f"/api/share-packages/{body['id']}/reveal")

    assert response.status_code == 200, response.text
    assert calls == [["explorer", str(directory)]]
    assert response.json()["directory"] == str(directory)


def test_reveal_non_windows_returns_409(client, monkeypatch):
    resume_id = _manual_resume(client, {"name": "张三"})
    body = _create_package(client, resume_id)

    monkeypatch.setattr(share_packages_api, "_is_windows", lambda: False)

    response = client.post(f"/api/share-packages/{body['id']}/reveal")

    assert response.status_code == 409
    assert "不支持自动打开" in response.json()["detail"]
