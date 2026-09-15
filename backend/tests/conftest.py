"""测试夹具：独立的文件型测试数据库 + 测试客户端。

必须在导入 app 之前设置 DATABASE_URL（config 在导入时读取一次）。
"""
import os
from pathlib import Path
import tempfile

_TEST_DB = Path(tempfile.gettempdir()) / f"resume_forge_test_{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine, get_db  # noqa: E402
from app.main import app  # noqa: E402

@pytest.fixture(autouse=True)
def clean_db():
    """每个用例前重建表结构，保证用例之间完全隔离。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client():
    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # 生产版只监听本机；测试客户端也使用回环地址覆盖密钥查看边界。
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    """测试全部结束后删除测试数据库文件。"""
    yield
    # Windows 下引擎的连接池仍持有文件句柄，必须先 dispose 才能删除
    engine.dispose()
    if _TEST_DB.exists():
        _TEST_DB.unlink()
