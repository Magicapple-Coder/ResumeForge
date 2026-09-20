"""数据集接口测试：本机限制、类型校验、导入/切换/重命名/删除与导出。"""
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from app import database
from app.api import datasets as datasets_api
from app.services.data_backup import create_backup_archive

MAIN = "main"


def _archive_bytes(tmp_path: Path) -> bytes:
    """把当前（测试）数据库导出成一份合法备份包。"""
    return create_backup_archive(database.engine, tmp_path / "staging").read_bytes()


def _import(client, payload: bytes, name: str = "导入的数据集", content_type: str = "application/zip"):
    return client.post(
        f"/api/settings/datasets/import?name={name}",
        content=payload,
        headers={"Content-Type": content_type},
    )


def _job_titles(client) -> set[str]:
    response = client.get("/api/jobs")
    assert response.status_code == 200
    return {item["title"] for item in response.json()["items"]}


def _add_job(client, title: str) -> None:
    response = client.post(
        "/api/jobs",
        json={"title": title, "description": "职责", "requirements": "要求"},
    )
    assert response.status_code in (200, 201)


def _list_datasets(client) -> list[dict]:
    response = client.get("/api/settings/datasets")
    assert response.status_code == 200
    return response.json()


def test_list_datasets_starts_with_only_the_main_dataset(client):
    items = _list_datasets(client)

    assert [item["id"] for item in items] == [MAIN]
    assert items[0]["is_active"] is True


def test_create_dataset_makes_a_named_empty_dataset(client):
    response = client.post("/api/settings/datasets", json={"name": "校招空库"})

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "校招空库"
    assert created["source"] == "新建"
    assert created["is_active"] is False
    assert created["id"] != MAIN
    assert {item["id"] for item in _list_datasets(client)} == {MAIN, created["id"]}


def test_created_dataset_can_be_activated_and_starts_empty(client):
    """新建的空数据集激活后应为**空视图**（主数据里的内容不该漏进来）。"""
    created = client.post("/api/settings/datasets", json={"name": "空库"}).json()
    _add_job(client, "主数据里的岗位")

    assert client.post(f"/api/settings/datasets/{created['id']}/activate").status_code == 200
    assert _job_titles(client) == set()


def test_create_dataset_requires_a_loopback_client(client, monkeypatch):
    monkeypatch.setattr("app.api.settings._is_loopback_request", lambda _request: False)

    response = client.post("/api/settings/datasets", json={"name": "空库"})

    assert response.status_code == 403


def test_create_dataset_rejects_a_blank_name(client):
    # 空串：schema 层拦下。
    assert client.post("/api/settings/datasets", json={"name": ""}).status_code == 422
    # 全是空格：schema 层放行（长度 ≥1），由服务层拒绝并给出可操作的中文提示。
    response = client.post("/api/settings/datasets", json={"name": "   "})
    assert response.status_code == 400
    assert "名称不能为空" in response.json()["detail"]


def test_import_creates_a_new_dataset_without_touching_current_data(client, tmp_path):
    """导入是可撤销的：它只新增一份数据集，当前正在用的数据一点不变。"""
    _add_job(client, "导入前的岗位")
    payload = _archive_bytes(tmp_path)
    _add_job(client, "导出之后新增的岗位")

    response = _import(client, payload, name="备份 A")

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "备份 A"
    assert created["is_active"] is False
    # 当前数据没有被这次导入改动。
    assert _job_titles(client) == {"导入前的岗位", "导出之后新增的岗位"}
    assert {item["id"] for item in _list_datasets(client)} == {MAIN, created["id"]}


def test_activate_switches_the_whole_application_to_that_dataset(client, tmp_path):
    _add_job(client, "导出时的岗位")
    payload = _archive_bytes(tmp_path)
    _add_job(client, "导出之后新增的岗位")
    created = _import(client, payload).json()

    response = client.post(f"/api/settings/datasets/{created['id']}/activate")

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert _job_titles(client) == {"导出时的岗位"}


def test_writes_after_switching_do_not_leak_into_the_other_dataset(client, tmp_path):
    """切到数据集 B 之后写入的数据，切回主数据时不能出现在主数据里。

    这是最容易出的静默错误：引擎换了但某个模块仍持有旧会话工厂，数据就写进了
    上一份数据集。
    """
    _add_job(client, "主数据里的岗位")
    created = _import(client, _archive_bytes(tmp_path)).json()

    client.post(f"/api/settings/datasets/{created['id']}/activate")
    _add_job(client, "只在数据集里")
    assert _job_titles(client) == {"主数据里的岗位", "只在数据集里"}

    client.post(f"/api/settings/datasets/{MAIN}/activate")

    assert _job_titles(client) == {"主数据里的岗位"}


def test_rename_dataset(client, tmp_path):
    created = _import(client, _archive_bytes(tmp_path)).json()

    response = client.patch(f"/api/settings/datasets/{created['id']}?name=校招专用")

    assert response.status_code == 200
    assert response.json()["name"] == "校招专用"
    assert "校招专用" in {item["name"] for item in _list_datasets(client)}


def test_delete_moves_the_dataset_out_of_the_list(client, tmp_path):
    """删除只移入回收目录，不永久删除（项目约定）。"""
    created = _import(client, _archive_bytes(tmp_path)).json()

    response = client.delete(f"/api/settings/datasets/{created['id']}")

    assert response.status_code == 204
    assert {item["id"] for item in _list_datasets(client)} == {MAIN}
    from app.dataset_registry import trash_directory

    assert list(trash_directory().glob(f"{created['id']}-*.db"))


def test_delete_refuses_the_active_dataset(client, tmp_path):
    created = _import(client, _archive_bytes(tmp_path)).json()
    client.post(f"/api/settings/datasets/{created['id']}/activate")

    response = client.delete(f"/api/settings/datasets/{created['id']}")

    assert response.status_code == 400
    assert "正在使用" in response.json()["detail"]


def test_activate_rejects_an_id_that_tries_to_escape_the_directory(client):
    response = client.post("/api/settings/datasets/....../activate")

    assert response.status_code == 400
    assert "无效" in response.json()["detail"]


def test_activate_reports_a_missing_dataset(client):
    response = client.post("/api/settings/datasets/0123456789abcdef/activate")

    assert response.status_code == 404


def test_import_requires_a_loopback_client(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.settings._is_loopback_request", lambda _request: False)

    assert _import(client, _archive_bytes(tmp_path)).status_code == 403


def test_import_requires_a_zip_content_type(client, tmp_path):
    """application/zip 不在 CORS 简单请求允许的类型里，跨站页面无法直接触发导入。"""
    response = _import(client, _archive_bytes(tmp_path), content_type="application/json")

    assert response.status_code == 415


def test_import_rejects_a_payload_that_is_not_a_zip(client):
    response = _import(client, b"definitely not a zip archive")

    assert response.status_code == 400
    assert "压缩包" in response.json()["detail"]


def test_import_rejects_a_payload_over_the_configured_limit(client, tmp_path, monkeypatch):
    # 端点在函数内 import get_settings，因此替换 app.config 上的那个即可生效。
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(max_backup_upload_mb=0))

    response = _import(client, _archive_bytes(tmp_path))

    assert response.status_code == 413
    assert "过大" in response.json()["detail"]


def test_export_downloads_a_dataset_as_a_zip(client, tmp_path):
    created = _import(client, _archive_bytes(tmp_path)).json()

    response = client.get(f"/api/settings/datasets/{created['id']}/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert response.content[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["api_key_included"] is False


def test_a_round_trip_preserves_every_kind_of_content_including_the_trash(
    client, db_session, tmp_path
):
    """导出 → 导入 → 切过去：**每一类**内容都要原样还在，**包括"哪些东西在回收站里"**。

    现有测试只核对了岗位标题这一种实体。而一份备份要真的能"把数据带走"，就得覆盖简历
    （含正文与版式）、资料、台账、投递记录、助手会话与备选岗位。

    尤其是**回收站状态**：如果导出/导入把 `deleted_at` 丢了，用户导入备份后会发现自己
    **删掉的东西又回来了**——而这类差别不专门核对根本发现不了（列表里多一条少一条，
    谁也不会去数）。
    """
    from app.models.assistant import ChatConversation
    from app.models.claim import ClaimRecord
    from app.models.material import CandidateJob, Material
    from app.models.resume import ResumeRecord
    from app.models.tracker import ApplicationTrack

    # ① 每一类都放一条"有辨识度"的数据（用哨兵串，方便导入后核对）。
    _add_job(client, "要留下的岗位")
    trashed = client.post(
        "/api/jobs", json={"title": "要删掉的岗位", "description": "职责", "requirements": "要求"}
    ).json()

    db_session.add_all(
        [
            ResumeRecord(
                title="哨兵简历",
                content={"name": "张三", "summary": "SUMMARY_SENTINEL"},
                template="technical",
                page_limit=2,
                format_config={"accent": "#0f766e"},
            ),
            Material(title="哨兵资料", category="项目", content="MATERIAL_SENTINEL"),
            ClaimRecord(title="哨兵台账", source_fact="CLAIM_SENTINEL"),
            ApplicationTrack(title="哨兵投递", company="某公司", status="applied"),
            ChatConversation(title="哨兵会话"),
            CandidateJob(title="哨兵候选岗位", status="pending"),
        ]
    )
    db_session.commit()

    # ② 删掉一条岗位：它的"已删除"状态也必须一起被带走。
    assert client.delete(f"/api/jobs/{trashed['id']}").status_code == 204

    # ③ 导出当前数据 → 导入成新数据集 → 切过去。
    payload = _archive_bytes(tmp_path)
    created = _import(client, payload, name="闭环备份").json()
    assert client.post(f"/api/settings/datasets/{created['id']}/activate").status_code == 200

    # ④ 逐类核对：活着的还在，删掉的不在列表里、但在回收站里。
    assert _job_titles(client) == {"要留下的岗位"}
    assert "哨兵简历" in {item["title"] for item in client.get("/api/resumes").json()["items"]}
    resume_id = next(
        item["id"]
        for item in client.get("/api/resumes").json()["items"]
        if item["title"] == "哨兵简历"
    )
    rendered = client.get(f"/api/resumes/{resume_id}").json()
    # 正文与版式都要原样带过来（版式丢了的话，导入回来的简历会长得不一样）。
    assert rendered["content"]["summary"] == "SUMMARY_SENTINEL"
    assert rendered["template"] == "technical"
    assert rendered["page_limit"] == 2
    assert rendered["format_config"] == {"accent": "#0f766e"}

    assert "哨兵资料" in {item["title"] for item in client.get("/api/materials").json()}
    assert "哨兵投递" in {item["title"] for item in client.get("/api/tracker").json()["items"]}
    assert "哨兵会话" in {item["title"] for item in client.get("/api/assistant/conversations").json()}
    assert "哨兵候选岗位" in {
        item["title"] for item in client.get("/api/candidate-jobs").json()
    }
    claim_titles = {
        item["title"] for item in client.get("/api/claims").json().get("items", [])
    }
    assert "哨兵台账" in claim_titles

    # ⑤ **回收站状态一起被带走**：删掉的那条不该复活，且仍列在回收站里。
    trashed_now = client.get("/api/trash").json()
    assert [
        item["title"] for item in trashed_now["items"] if item["type"] == "job"
    ] == ["要删掉的岗位"]

    # ⑥ 备份里不含明文 API Key（导入的那份同样是"导出产物"，这条顺带再确认一次）。
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["api_key_included"] is False


def test_import_path_is_registered():
    """中间件按 IMPORT_PATH 放宽上限；路由改名会让豁免静默失效，这里把两者绑死。"""
    from app.application import create_app

    assert datasets_api.IMPORT_PATH in set(create_app().openapi()["paths"])
