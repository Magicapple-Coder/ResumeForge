"""退出接口的边界测试。

成功路径**不能真的调用**（那会把 pytest 自己关掉），所以这里用两层保护：
- 非回环请求必须被 403 拦住；
- 回环请求只会启动一个"停止线程"，测试把它替换成记录用的空函数，验证线程确实被创建。
"""
import time

from fastapi.testclient import TestClient

from app.database import SessionLocal, get_db
from app.main import app


def test_shutdown_rejects_non_loopback_clients():
    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app, client=("192.168.1.20", 50000)) as remote:
            response = remote.post("/api/system/shutdown")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert "本机" in response.json()["detail"]


def test_shutdown_from_loopback_starts_the_stopper(monkeypatch, client):
    calls: list[str] = []
    monkeypatch.setattr("app.api.system._stop_process", lambda: calls.append("stopped"))

    response = client.post("/api/system/shutdown")

    assert response.status_code == 202
    assert response.json()["status"] == "stopping"
    # 线程真的被创建并跑起来了（否则"点了退出却没反应"又会回来）。
    deadline = time.time() + 2
    while not calls and time.time() < deadline:
        time.sleep(0.05)
    assert calls == ["stopped"]
