"""「当前批次」必须看得见**采集**批次（2026-09-21 修的回归）。

以前的 ``GET /api/apply/tasks/current`` 写死 ``kind=apply``，采集批次在它眼里永远是
"没有任务"。后果不是少显示一行进度，而是两条用户能直接感知的能力直接失效：

- 开始采集后切走再回投递台，进度面板是空的，看不到采集在跑；
- 全局完成通知靠它判断"这个批次刚才在跑"，采集批次从不出现 → **采集跑完永远不弹通知**。

两种批次本来就是互斥的（运行器同一时刻只跑一个），所以"任意类型"就是"那一个"。
"""
from __future__ import annotations

import pytest

from app.models.apply import TASK_STATUS_PENDING, TASK_STATUS_RUNNING, ApplyTask
from app.services.apply import apply_service, task_runner


class _FakeRunner:
    """只回答"在不在跑"并记下启动请求——本文件只关心**可见性**，不真的执行批次。"""

    def __init__(self) -> None:
        self.started: list[int] = []
        self.running = False

    def is_running(self) -> bool:
        return self.running

    def start(self, task_id: int) -> None:
        self.started.append(task_id)
        self.running = True


@pytest.fixture
def fake_runner(monkeypatch) -> _FakeRunner:
    fake = _FakeRunner()
    monkeypatch.setattr(task_runner, "get_task_runner", lambda: fake)
    return fake


def _start_collect(client) -> int:
    client.put(
        "/api/collect/config",
        json={"keywords": ["python"], "city": "成都"},
    )
    response = client.post("/api/collect/tasks", json={})
    assert response.status_code == 200
    return response.json()["id"]


def test_current_task_reports_a_running_collect_batch(client, fake_runner):
    task_id = _start_collect(client)

    current = client.get("/api/apply/tasks/current")
    assert current.status_code == 200
    assert current.json() is not None, "采集批次在「当前批次」里不可见，进度面板与完成通知都会失效"
    assert current.json()["id"] == task_id
    assert current.json()["kind"] == "collect"


def test_current_task_still_reports_an_apply_batch(client, db_session, fake_runner):
    """放宽类型不能把投递那条路弄丢。"""
    from app.models.job import JOB_STATUS_OPEN, Job

    job = Job(
        title="后端开发",
        company="A公司",
        source="BOSS直聘",
        source_url="https://www.zhipin.com/job/1",
        status=JOB_STATUS_OPEN,
    )
    db_session.add(job)
    db_session.commit()

    response = client.post(
        "/api/apply/tasks", json={"job_ids": [job.id], "use_queue": False}
    )
    assert response.status_code == 200

    current = client.get("/api/apply/tasks/current")
    assert current.status_code == 200
    assert current.json()["kind"] == "apply"


def test_current_task_can_still_be_narrowed_to_one_kind(client, fake_runner):
    """需要限定类型的调用方传 ``kind`` 即可，行为与改动前一致。"""
    task_id = _start_collect(client)

    assert client.get("/api/apply/tasks/current?kind=collect").json()["id"] == task_id
    assert client.get("/api/apply/tasks/current?kind=apply").json() is None


def test_current_task_returns_null_when_everything_is_terminal(client, db_session, fake_runner):
    task_id = _start_collect(client)
    task = db_session.get(ApplyTask, task_id)
    task.status = TASK_STATUS_RUNNING
    db_session.commit()

    assert client.get("/api/apply/tasks/current").json()["id"] == task_id

    task.status = "completed"
    db_session.commit()
    assert client.get("/api/apply/tasks/current").json() is None


def test_current_task_rejects_an_unknown_kind(client, fake_runner):
    assert client.get("/api/apply/tasks/current?kind=bogus").status_code == 422


def test_service_level_default_is_unfiltered(db_session):
    """服务层的默认值也必须是"不限类型"——否则别的调用方会再踩一次同一个坑。"""
    task = ApplyTask(kind="collect", status=TASK_STATUS_PENDING, total=1, config={})
    db_session.add(task)
    db_session.commit()

    assert apply_service.current_task(db_session).id == task.id
    assert apply_service.current_task(db_session, kind="apply") is None
