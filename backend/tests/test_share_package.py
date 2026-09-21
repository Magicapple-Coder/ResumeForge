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


# ===== 产物文件是缓存，不是数据源（2026-09-21）=====
#
# 分享包的**内容**在数据库里（`snapshot` 列），渲染出来的 HTML/PDF/JSON 落在磁盘上。
# 磁盘目录不随备份包走，所以换数据集、或从备份恢复到另一台机器之后目录是空的：列表和
# 详情都正常（走数据库），偏偏点「下载」会 404——看起来像功能坏了。


def _package_dir(client) -> Path:
    """当前（测试）数据库的分享包根目录。"""
    from app import database
    from app.services.share_package import share_root

    return share_root(database.engine)


def test_download_regenerates_missing_artifacts_from_the_snapshot(client):
    """把目录整个删掉（模拟"换数据集 / 从备份恢复"），下载仍应拿到内容。"""
    resume_id = _manual_resume(client, {"name": "张三", "summary": "负责后端服务。"})
    body = _create_package(client, resume_id)
    share_id = body["id"]
    directory = _package_dir(client) / str(share_id)
    assert directory.is_dir()

    import shutil

    shutil.rmtree(directory)
    assert not directory.exists()

    for name in ("resume.html", "resume.pdf", "resume_snapshot.json", "manifest.json"):
        response = client.get(f"/api/share-packages/{share_id}/files/{name}")
        assert response.status_code == 200, f"{name} 没有按快照补回来：{response.text}"
        assert response.content, f"{name} 补出来是空的"

    # 补出来的内容确实来自那份快照，而不是一个空壳。
    html = client.get(f"/api/share-packages/{share_id}/files/resume.html").text
    assert "负责后端服务。" in html
    snapshot = json.loads(
        client.get(f"/api/share-packages/{share_id}/files/resume_snapshot.json").text
    )
    assert snapshot["summary"] == "负责后端服务。"
    # 脱敏过的快照不会把姓名带回来——重新生成不能成为绕过脱敏的口子。
    assert "张三" not in html


def test_regeneration_keeps_the_original_token_and_permission(client):
    """清单是按库里的字段重建的，不能凭空造一个新的 token（收件人手上那份就对不上了）。"""
    resume_id = _manual_resume(client, {"name": "张三", "summary": "后端。"})
    body = _create_package(client, resume_id, permission="comment")
    share_id = body["id"]

    directory = _package_dir(client) / str(share_id)
    for name in ("manifest.json", "resume.html"):
        (directory / name).unlink()

    client.get(f"/api/share-packages/{share_id}/files/manifest.json")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["share_token"] == body["share_token"]
    assert manifest["permission"] == "comment"


def test_comments_file_is_never_fabricated(client):
    """``comments.md`` 是收件人写进来的内容，数据库里没有第二份。

    补一个空白模板会在界面上假装"评论还在"，而它其实随着文件一起没了——那比 404 更糟。
    """
    resume_id = _manual_resume(client, {"name": "张三", "summary": "后端。"})
    body = _create_package(client, resume_id, permission="comment")
    share_id = body["id"]

    directory = _package_dir(client) / str(share_id)
    (directory / "comments.md").unlink()

    response = client.get(f"/api/share-packages/{share_id}/files/comments.md")

    assert response.status_code == 404
    assert not (directory / "comments.md").exists()


def test_non_main_datasets_get_their_own_share_root(client, tmp_path):
    """**非主数据集的分享包目录要隔开。**

    多个数据集共用 `data/datasets/` 一个目录，而分享包 id 是每个库各自自增的——不隔离的话，
    数据集 A 的第 1 份会把数据集 B 的第 1 份覆盖掉。主数据保持原路径（那里已有用户的分享包）。
    """
    from app import database
    from app.dataset_registry import dataset_database_file
    from app.services.datasets import create_dataset
    from app.services.share_package import share_root

    main_root = share_root(database.engine)
    created = create_dataset("第二份", database.engine)
    dataset_path = Path(dataset_database_file(created["id"]))
    other_engine = database.build_engine(database.database_url_for(dataset_path))
    try:
        other_root = share_root(other_engine)
        assert other_root != main_root
        # 落到以库文件名命名的那一层里，两个数据集不会撞在一起。
        assert other_root.name == dataset_path.stem
    finally:
        other_engine.dispose()
