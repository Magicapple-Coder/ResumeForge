"""数据备份接口测试：本机限制、类型校验、token 校验与预览。"""
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.api import backup as backup_api
from app.database import engine
from app.services.data_backup import create_backup_archive


def _archive_bytes(tmp_path: Path) -> bytes:
    return create_backup_archive(engine, tmp_path / "staging").read_bytes()


def _upload(client, payload: bytes, content_type: str = "application/zip"):
    return client.post(
        "/api/settings/backup/upload",
        content=payload,
        headers={"Content-Type": content_type},
    )


def test_export_returns_a_zip_with_no_store(client, tmp_path):
    response = client.get("/api/settings/backup/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    assert response.content[:2] == b"PK"


def test_export_requires_a_loopback_client(client, monkeypatch):
    monkeypatch.setattr("app.api.settings._is_loopback_request", lambda _request: False)

    assert client.get("/api/settings/backup/export").status_code == 403


def test_upload_requires_a_loopback_client(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.settings._is_loopback_request", lambda _request: False)

    assert _upload(client, _archive_bytes(tmp_path)).status_code == 403


def test_upload_requires_a_zip_content_type(client, tmp_path):
    """application/zip 不在 CORS 简单请求允许的类型里，跨站页面无法直接触发恢复。"""
    response = _upload(client, _archive_bytes(tmp_path), content_type="application/json")

    assert response.status_code == 415


def test_upload_returns_a_preview_without_touching_the_data(client, tmp_path):
    response = _upload(client, _archive_bytes(tmp_path))

    assert response.status_code == 200
    body = response.json()
    assert len(body["token"]) == 32
    assert body["manifest"]["format"] == 1
    assert body["manifest"]["api_key_included"] is False
    assert body["current_tables"]["job"] == 0
    assert body["database"]["tables"]["job"] == 0


def test_upload_rejects_a_payload_that_is_not_a_zip(client):
    response = _upload(client, b"definitely not a zip archive")

    assert response.status_code == 400
    assert "压缩包" in response.json()["detail"]


def test_upload_rejects_a_payload_over_the_configured_limit(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.api.backup.get_settings", lambda: SimpleNamespace(max_backup_upload_mb=0)
    )

    response = _upload(client, _archive_bytes(tmp_path))

    assert response.status_code == 413
    assert "过大" in response.json()["detail"]


def test_apply_rejects_an_unknown_token(client):
    response = client.post("/api/settings/backup/apply", json={"token": "0" * 32})

    assert response.status_code == 400
    assert "失效" in response.json()["detail"]


def test_apply_rejects_a_token_that_tries_to_escape_the_directory(client):
    """token 会被拼进文件路径，必须只接受本模块生成的十六进制标识。"""
    # 恰好 32 字符，绕过 schema 的长度校验，专门验证路径拼接前的前缀检查。
    response = client.post("/api/settings/backup/apply", json={"token": "../" * 10 + "ab"})

    assert response.status_code == 400
    assert "无效" in response.json()["detail"]


def test_apply_restores_the_uploaded_backup(client, tmp_path, db_session):
    from app.models.job import Job

    db_session.add(Job(title="备份中的岗位", description="职责", requirements="要求"))
    db_session.commit()
    payload = _archive_bytes(tmp_path)

    db_session.add(Job(title="备份后新增的岗位", description="职责", requirements="要求"))
    db_session.commit()
    db_session.close()

    upload = _upload(client, payload)
    assert upload.status_code == 200

    applied = client.post("/api/settings/backup/apply", json={"token": upload.json()["token"]})

    assert applied.status_code == 200
    assert applied.json()["previous_backup"] is not None
    with engine.connect() as connection:
        titles = {row[0] for row in connection.exec_driver_sql("SELECT title FROM job")}
    assert titles == {"备份中的岗位"}


def test_uploaded_archive_is_removed_after_applying(client, tmp_path, db_session):
    from app.services.data_backup import restore_directory

    db_session.close()
    upload = _upload(client, _archive_bytes(tmp_path))
    token = upload.json()["token"]
    staged = restore_directory(engine) / f"{token}.zip"
    assert staged.exists()

    client.post("/api/settings/backup/apply", json={"token": token})

    assert not staged.exists()


def test_manifest_round_trips_through_the_upload_preview(client, tmp_path):
    payload = _archive_bytes(tmp_path)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        manifest = json.loads(archive.read("manifest.json"))

    assert _upload(client, payload).json()["manifest"] == manifest


def test_backup_upload_path_is_registered():
    """中间件按 UPLOAD_PATH 放宽上限；路由改名会让豁免静默失效，这里把两者绑死。"""
    from app.application import create_app

    assert backup_api.UPLOAD_PATH in set(create_app().openapi()["paths"])
