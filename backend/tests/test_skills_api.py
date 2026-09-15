"""技能接口测试：导入（.md / .zip）、启用切换、删除与临时文件清理。"""
import io
import zipfile

from app import database
from app.api import skills as skills_api
from app.services.data_backup import restore_directory

FRONTMATTER = """---
name: 面试模拟官
description: 用户想练面试时使用
---

你是面试官，逐题提问并追问。
"""


def _md(name: str = "面试模拟官", body: str = "你是面试官。") -> bytes:
    return f"---\nname: {name}\ndescription: 练面试时使用\n---\n\n{body}\n".encode()


def _zip_bytes(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _import(client, payload: bytes, content_type: str = "application/zip"):
    return client.post(
        "/api/assistant/skills/import", content=payload, headers={"Content-Type": content_type}
    )


def _list(client) -> list[dict]:
    response = client.get("/api/assistant/skills")
    assert response.status_code == 200
    return response.json()


def test_import_a_prompt_only_markdown_skill(client):
    response = _import(client, _md(), content_type="text/markdown")

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "面试模拟官"
    assert created["description"] == "练面试时使用"
    assert created["enabled"] is True
    assert created["files"] == []
    assert created["prompt_chars"] > 0
    assert [item["name"] for item in _list(client)] == ["面试模拟官"]


def test_import_a_zip_skill_with_knowledge_files(client):
    payload = _zip_bytes(
        {
            "SKILL.md": FRONTMATTER,
            "题库.md": "第一题：自我介绍",
            "模板.txt": "STAR",
        }
    )

    response = _import(client, payload)

    assert response.status_code == 200
    # 知识文件按路径排序返回（关系的 order_by），与压缩包里的顺序无关，
    # 这样界面上的清单不会因为打包顺序不同而变来变去。
    assert response.json()["files"] == ["模板.txt", "题库.md"]


def test_import_cleans_up_its_temporary_upload(client):
    """上传的原始文件是临时的：解析完必须删掉，否则 restore 目录会越积越大。"""
    _import(client, _zip_bytes({"SKILL.md": FRONTMATTER}))

    assert list(restore_directory(database.engine).iterdir()) == []


def test_import_rejects_an_unsupported_content_type(client):
    response = _import(client, b"{}", content_type="application/json")

    assert response.status_code == 415
    assert ".md" in response.json()["detail"] and ".zip" in response.json()["detail"]


def test_import_reports_a_broken_archive(client):
    response = _import(client, b"definitely not a zip archive")

    assert response.status_code == 400
    assert "压缩文件" in response.json()["detail"]


def test_import_reports_a_markdown_that_is_not_utf8(client):
    response = _import(client, b"\xff\xfe\x00\x00bad", content_type="text/markdown")

    assert response.status_code == 400
    assert "UTF-8" in response.json()["detail"]


def test_reimporting_the_same_name_updates_instead_of_duplicating(client):
    first = _import(client, _md(body="第一版。"), content_type="text/markdown").json()

    second = _import(client, _md(body="第二版。"), content_type="text/markdown").json()

    assert second["id"] == first["id"]
    assert [item["id"] for item in _list(client)] == [first["id"]]


def test_reimporting_replaces_the_knowledge_files(client):
    _import(client, _zip_bytes({"SKILL.md": FRONTMATTER, "旧.md": "甲"}))
    _import(client, _zip_bytes({"SKILL.md": FRONTMATTER, "新.md": "乙"}))

    assert _list(client)[0]["files"] == ["新.md"]


def test_toggle_a_skill_and_report_a_missing_one(client):
    created = _import(client, _md(), content_type="text/markdown").json()

    disabled = client.patch(f"/api/assistant/skills/{created['id']}", json={"enabled": False})

    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert client.patch("/api/assistant/skills/9999", json={"enabled": True}).status_code == 404


def test_delete_a_skill_and_report_a_missing_one(client):
    created = _import(client, _md(), content_type="text/markdown").json()

    assert client.delete(f"/api/assistant/skills/{created['id']}").status_code == 204
    assert _list(client) == []
    assert client.delete(f"/api/assistant/skills/{created['id']}").status_code == 404


def test_the_list_never_returns_the_prompt_body(client):
    """列表只回长度不回正文：技能提示词是给模型的指令，界面没有展示它的必要。"""
    _import(client, _md(body="你是面试官。"), content_type="text/markdown")

    item = _list(client)[0]

    assert "prompt" not in item
    assert "你是面试官" not in str(item)


def test_import_path_is_registered():
    """中间件按 IMPORT_PATH 放宽上限；路由改名会让豁免静默失效，这里把两者绑死。"""
    from app.application import create_app

    assert skills_api.IMPORT_PATH in set(create_app().openapi()["paths"])
