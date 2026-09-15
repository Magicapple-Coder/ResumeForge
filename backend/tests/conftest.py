"""测试夹具：独立的文件型测试数据库 + 测试客户端。

必须在导入 app 之前设置 DATABASE_URL（config 在导入时读取一次）。

测试库放在**每个进程独立的目录**里，而不是共享的系统临时目录根下：数据集功能把
指针（active.json）与 datasets/ 目录都解析成"数据库所在目录"的子项，放在共享目录
会让不同测试运行互相看到对方的数据集。
"""
import os
import shutil
from pathlib import Path
import tempfile

_TEST_DIR = Path(tempfile.gettempdir()) / f"resume_forge_test_{os.getpid()}"
_TEST_DIR.mkdir(parents=True, exist_ok=True)
_TEST_DB = _TEST_DIR / "resume_forge.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import database  # noqa: E402
from app.database import Base, SessionLocal, get_db  # noqa: E402
from app.dataset_registry import (  # noqa: E402
    MAIN_DATASET_ID,
    datasets_directory,
    write_active_dataset_id,
)
from app.main import app  # noqa: E402


def _reset_to_test_database() -> None:
    """把活动指针与引擎复位到测试库本身。

    数据集用例会切换引擎，不复位的话，一个用例切到的数据集会被后续用例继续使用。
    引擎一律用属性访问：它是可以被重绑的模块级对象，按值导入会拿到旧的那个。
    """
    write_active_dataset_id(MAIN_DATASET_ID)
    current = database.engine.url.database
    if current is None or Path(current).resolve() != _TEST_DB.resolve():
        database.rebind(_TEST_DB)


def _clear_datasets() -> None:
    """清掉用例产生的数据集文件。

    数据集目录建在测试库同级，所以同一进程里前一个用例导入的数据集会出现在后一个
    用例的列表里。这里删的是本进程独占的临时目录内容（整个目录在会话结束时统一
    删除），不是用户数据。
    """
    directory = datasets_directory()
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_db():
    """每个用例前重建表结构，保证用例之间完全隔离。"""
    _reset_to_test_database()
    _clear_datasets()
    Base.metadata.drop_all(bind=database.engine)
    Base.metadata.create_all(bind=database.engine)
    yield
    _reset_to_test_database()
    Base.metadata.drop_all(bind=database.engine)
    _clear_datasets()


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
    """测试全部结束后删除测试数据目录。"""
    yield
    # Windows 下引擎的连接池仍持有文件句柄，必须先 dispose 才能删除
    database.engine.dispose()
    shutil.rmtree(_TEST_DIR, ignore_errors=True)
