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


# ===== 导出全部数据集（含其余数据集）=====
#
# 背景：默认导出只带**当前活动**的那一份。用户可能有好几份数据集（给不同求职方向各开一套），
# 只备份活动那份的后果是"以为备份了、其实丢了几份"，而这类故障通常很久以后才发现。


def _other_dataset_with_a_job(client, name: str, title: str) -> str:
    """建一份新数据集、切过去放一个特征岗位、再切回主数据，返回它的 id。"""
    created = client.post("/api/settings/datasets", json={"name": name}).json()
    client.post(f"/api/settings/datasets/{created['id']}/activate")
    _add_job(client, title)
    client.post(f"/api/settings/datasets/{MAIN}/activate")
    return created["id"]


def test_export_all_carries_the_other_datasets(client, tmp_path):
    _add_job(client, "主数据里的岗位")
    other_id = _other_dataset_with_a_job(client, "校招线", "校招专有岗位")

    response = client.get("/api/settings/datasets/export-all")

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
    # 活动数据集仍在老位置，其余数据集放在 datasets/ 下。
    assert "resume_forge.db" in names
    assert f"datasets/{other_id}.db" in names
    assert f"datasets/{other_id}.json" in names
    # 格式号必须升到 2：老版本读不懂 datasets/ 这一段，得让它**明确拒收**而不是安静地
    # 只恢复活动数据集。
    assert manifest["format"] == 2
    assert [item["id"] for item in manifest["datasets"]] == [other_id]
    assert manifest["datasets"][0]["name"] == "校招线"


def test_exporting_one_dataset_stays_format_1(client, tmp_path):
    """只导一份时格式保持 1——老版本与旧备份的互操作不能因为这次改动受影响。"""
    _other_dataset_with_a_job(client, "校招线", "校招专有岗位")

    response = client.get(f"/api/settings/datasets/{MAIN}/export")

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
    assert names == {"resume_forge.db", "manifest.json"}
    assert manifest["format"] == 1
    assert "datasets" not in manifest


def test_import_restores_the_packaged_datasets(client, tmp_path):
    """导入一份"全部"包，包里的其余数据集要各落成一份新数据集，且内容是真的。"""
    other_id = _other_dataset_with_a_job(client, "校招线", "校招专有岗位")
    payload = client.get("/api/settings/datasets/export-all").content

    response = _import(client, payload, name="整包恢复")

    assert response.status_code == 200
    created = response.json()
    restored = created.get("restored_datasets")
    assert restored and len(restored) == 1
    assert restored[0]["name"] == "校招线"  # 名字沿用包里的，用户靠它认人
    # **新 id**：沿用包里的 id 会覆盖本机已有的那份同名 id 的数据集（不可逆）。
    assert restored[0]["id"] not in {MAIN, other_id}
    assert {item["id"] for item in _list_datasets(client)} >= {restored[0]["id"], other_id}

    # 恢复出来的那份里确实有那个特征岗位。
    client.post(f"/api/settings/datasets/{restored[0]['id']}/activate")
    assert _job_titles(client) == {"校招专有岗位"}


def test_import_rejects_a_packaged_dataset_pointing_outside_datasets(client, tmp_path):
    """**路径是可以被构造的**：改过的包能把 file 指向主库或 ../../，导入必须拒收。"""
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("resume_forge.db", b"")
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": 2,
                    "api_key_included": False,
                    "datasets": [{"id": "x", "name": "坏包", "file": "../resume_forge.db"}],
                }
            ),
        )

    response = _import(client, payload.getvalue())

    assert response.status_code == 400
    assert "路径不合法" in response.json()["detail"]
    # 整包失败：不许留下半截的数据集。
    assert {item["id"] for item in _list_datasets(client)} == {MAIN}
