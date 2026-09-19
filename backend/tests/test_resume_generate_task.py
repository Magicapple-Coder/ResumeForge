"""简历生成后台任务：启动/轮询/取消、防重复、完成才落库。

这一组用例守的是"后台继续"改造后的三条数据一致性纪律：
- 取消标 cancelled 且**不落半成品简历**；
- 完成才落库（resume_id 回填 + resume_record 确实存在）；
- 防重复（连点两次不产生两条任务/两份简历）。
"""
import asyncio
import json
import threading
import time

import pytest

from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider
from app.services.resume_generate_runner import reset_resume_generate_runner

TERMINAL_STATUSES = {"completed", "cancelled", "failed"}


@pytest.fixture(autouse=True)
def _isolate_runner(clean_db):
    """每个用例前释放运行器单例，避免上一个用例的后台线程跨用例残留。"""
    reset_resume_generate_runner()
    yield
    reset_resume_generate_runner()


def _configure(client):
    config = LLMConfig(base_url="https://api.example.com/v1", api_key="k", model="m")
    assert client.put("/api/settings/llm", json=config.model_dump()).status_code == 200


def _seed_profile(client):
    assert (
        client.put(
            "/api/profile",
            json={
                "name": "张三",
                "projects": [
                    {
                        "name": "简历通",
                        "role": "核心开发",
                        "tech_stack": "Python, FastAPI",
                        "description": "开发简历生成接口",
                    }
                ],
            },
        ).status_code
        == 200
    )


def _job(client):
    return client.post(
        "/api/jobs", json={"title": "后端开发工程师", "company": "示例公司"}
    ).json()


def _get_task(client, task_id):
    response = client.get(f"/api/resumes/generate/tasks/{task_id}")
    assert response.status_code == 200
    return response.json()


def _wait_terminal(client, task_id, timeout=8.0):
    deadline = time.monotonic() + timeout
    task = _get_task(client, task_id)
    while task["status"] not in TERMINAL_STATUSES:
        if time.monotonic() >= deadline:
            raise AssertionError(f"任务 {task_id} 未在 {timeout}s 内到达终态：{task}")
        time.sleep(0.02)
        task = _get_task(client, task_id)
    return task


def _wait_status(client, task_id, status, timeout=8.0):
    deadline = time.monotonic() + timeout
    task = _get_task(client, task_id)
    while task["status"] != status:
        if time.monotonic() >= deadline:
            raise AssertionError(f"任务 {task_id} 未在 {timeout}s 内进入 {status}：{task}")
        time.sleep(0.02)
        task = _get_task(client, task_id)
    return task


class SuccessfulProvider(BaseLLMProvider):
    """产出合法 JSON 后立刻结束，用于验证"完成才落库"。"""

    async def chat(self, _messages):
        raise AssertionError("合法流式 JSON 不应触发修复调用")

    async def stream_chat(self, _messages):
        yield json.dumps(
            {
                "summary": "具备 Python 后端开发经验。",
                "projects": [{"name": "简历通", "role": "核心开发"}],
            },
            ensure_ascii=False,
        )


class EndlessProvider(BaseLLMProvider):
    """无限产出 chunk、永不结束，用于在"运行中"取消（否则取消竞态无法稳定复现）。"""

    async def chat(self, _messages):
        raise AssertionError("不应触发一次性对话")

    async def stream_chat(self, _messages):
        index = 0
        while True:
            yield f'{{"chunk": {index}}}'
            index += 1
            await asyncio.sleep(0.001)


def test_background_generation_completes_and_persists_resume(client, monkeypatch):
    _seed_profile(client)
    _configure(client)
    job = _job(client)
    monkeypatch.setattr(
        "app.services.resume_generate_runner.create_provider",
        lambda resolved: SuccessfulProvider(resolved),
    )

    started = client.post("/api/resumes/generate/tasks", json={"job_id": job["id"]})

    assert started.status_code == 201
    task = started.json()
    assert task["id"] > 0
    assert task["status"] in ("pending", "running")
    assert task["resume_id"] is None

    final = _wait_terminal(client, task["id"])
    assert final["status"] == "completed"
    assert final["resume_id"] is not None

    # 完成才落库：回填的 resume_id 确实能读出一份简历，而不是空指针。
    record = client.get(f"/api/resumes/{final['resume_id']}")
    assert record.status_code == 200
    assert record.json()["job_id"] == job["id"]


def test_cancel_marks_cancelled_and_writes_no_half_resume(client, monkeypatch):
    _seed_profile(client)
    _configure(client)
    job = _job(client)
    monkeypatch.setattr(
        "app.services.resume_generate_runner.create_provider",
        lambda resolved: EndlessProvider(resolved),
    )

    task = client.post("/api/resumes/generate/tasks", json={"job_id": job["id"]}).json()
    _wait_status(client, task["id"], "running")

    cancelled = client.post(f"/api/resumes/generate/tasks/{task['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    final = _wait_terminal(client, task["id"])
    assert final["status"] == "cancelled"
    assert final["resume_id"] is None

    # 取消不落半成品：简历中心一条新记录都没有。
    assert client.get("/api/resumes").json()["total"] == 0


def test_cancel_after_done_before_completed_writes_no_resume(client, monkeypatch):
    """竞态：cancel 在 done 之后、completed 认领之前到达 → 取消胜出、不落库。

    用 ``_claim_completed`` 作为同步点：worker 拿到 done、正准备原子认领 completed 前会
    停在这里，测试趁机触发 cancel（把 running→cancelled 写库），再放行。此时 worker 的
    认领 UPDATE 影响 0 行，于是放弃写简历、按 cancelled 收尾——证明"取消不落库"在最后一
    刻依然成立。

    有牙：把原子认领去掉后，这个同步点消失、worker 直接无条件落库并置 completed，
    ``reached_claim`` 永不触发（超时断言红）；若连 ``_claim_completed`` 方法一并删掉，
    monkeypatch 直接 AttributeError（也红）。
    """
    from app.services.resume_generate_runner import ResumeGenerateRunner

    _seed_profile(client)
    _configure(client)
    job = _job(client)
    monkeypatch.setattr(
        "app.services.resume_generate_runner.create_provider",
        lambda resolved: SuccessfulProvider(resolved),
    )

    reached_claim = threading.Event()
    cancel_issued = threading.Event()
    original_claim = ResumeGenerateRunner._claim_completed

    def coordinated_claim(self, session, task_id):
        reached_claim.set()
        assert cancel_issued.wait(timeout=5), "测试线程未在 5s 内发出 cancel"
        return original_claim(self, session, task_id)

    monkeypatch.setattr(ResumeGenerateRunner, "_claim_completed", coordinated_claim)

    task = client.post("/api/resumes/generate/tasks", json={"job_id": job["id"]}).json()
    assert reached_claim.wait(timeout=8), "worker 未在 8s 内到达 completed 认领点"

    cancelled = client.post(f"/api/resumes/generate/tasks/{task['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    cancel_issued.set()

    final = _wait_terminal(client, task["id"])
    assert final["status"] == "cancelled"
    assert final["resume_id"] is None
    # 取消不落半成品：简历中心一条新记录都没有。
    assert client.get("/api/resumes").json()["total"] == 0


def test_duplicate_generation_is_rejected(client, monkeypatch):
    _seed_profile(client)
    _configure(client)
    job = _job(client)
    monkeypatch.setattr(
        "app.services.resume_generate_runner.create_provider",
        lambda resolved: EndlessProvider(resolved),
    )

    first = client.post("/api/resumes/generate/tasks", json={"job_id": job["id"]})
    assert first.status_code == 201

    second = client.post("/api/resumes/generate/tasks", json={"job_id": job["id"]})
    assert second.status_code == 409
    assert "正在进行" in second.json()["detail"]


def test_start_still_validates_job_and_llm(client):
    """后台任务的前置校验与旧 SSE 接口一致，别把坏输入也塞进后台线程。"""
    _seed_profile(client)

    # 未配置 LLM：400
    assert client.post("/api/resumes/generate/tasks", json={}).status_code == 400

    _configure(client)
    # 岗位不存在：404
    assert (
        client.post("/api/resumes/generate/tasks", json={"job_id": 999}).status_code == 404
    )


def test_status_endpoint_404s_for_unknown_task(client):
    response = client.get("/api/resumes/generate/tasks/9999")
    assert response.status_code == 404


def test_completed_status_and_resume_id_commit_atomically(client, monkeypatch):
    """回归：status=completed 与 resume_id 必须同事务提交。

    旧实现把 ``_claim_completed``（running→completed）单独 commit、之后才在另一个事务里
    回填 resume_id，中间窗口会让轮询读到 completed + resume_id=None。这里给运行器的会话
    工厂包一层 commit 检查：每次提交后立刻读库，若任务已是 completed 则记录"resume_id
    是否非空"。只要"resume_id 被拆出去提交"，中间那次 commit 后就会记到 False 而变红。
    """
    from sqlalchemy import text
    from sqlalchemy.orm import Session, sessionmaker

    from app import database
    from app.services.resume_generate_runner import get_resume_generate_runner

    observations: list[bool] = []

    class InspectingSession(Session):
        def commit(self):
            super().commit()
            row = self.execute(
                text("SELECT status, resume_id FROM resume_generate_task")
            ).first()
            if row is not None and row.status == "completed":
                observations.append(row.resume_id is not None)

    runner = get_resume_generate_runner()
    runner._session_factory = sessionmaker(
        bind=database.engine,
        class_=InspectingSession,
        autoflush=False,
        expire_on_commit=False,
    )

    _seed_profile(client)
    _configure(client)
    job = _job(client)
    monkeypatch.setattr(
        "app.services.resume_generate_runner.create_provider",
        lambda resolved: SuccessfulProvider(resolved),
    )

    task = client.post("/api/resumes/generate/tasks", json={"job_id": job["id"]}).json()
    final = _wait_terminal(client, task["id"])

    assert final["status"] == "completed"
    assert final["resume_id"] is not None
    assert observations, "运行器会话未观察到任何 completed 提交，spy 未生效"
    assert all(observations), f"观察到 completed 但 resume_id 为空的中间态：{observations}"
