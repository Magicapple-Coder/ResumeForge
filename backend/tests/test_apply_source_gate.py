"""投递来源闸门：只有来源能落到已注册招聘网站上的岗位才允许走投递链路。

背景（用户反馈）：手动录入、来源指不到任何招聘网站的岗位以前也能加进投递队列，强行开始投递
只会得到一条「未知失败」的记录。这里把闸门钉在三处——入队、开始投递、单条执行兜底——并顺带
守住前后端共用的失败分类镜像。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models.apply import (
    FAILURE_CATEGORIES,
    FAILURE_CATEGORY_LABELS,
    FAILURE_SITE_UNSUPPORTED,
    ITEM_STATUS_PENDING,
    QUEUE_STATUS_PENDING,
    TASK_KIND_APPLY,
    TASK_STATUS_PENDING,
    ApplyQueueItem,
    ApplyTask,
    ApplyTaskItem,
)
from app.models.job import JOB_STATUS_OPEN, Job
from app.services.apply import apply_service, task_apply, task_runner
from app.services.sites.registry import get_registry

FRONTEND_TYPES = Path(__file__).resolve().parents[2] / "frontend/src/types/apply.ts"


class FakeRunner:
    """替掉单例运行器：不真起线程、不连浏览器，只记录"谁被启动了"。"""

    def __init__(self) -> None:
        self.running = False
        self.started: int | None = None

    def is_running(self) -> bool:
        return self.running

    def start(self, task_id: int) -> None:
        self.started = task_id


@pytest.fixture
def fake_runner(monkeypatch) -> FakeRunner:
    fake = FakeRunner()
    monkeypatch.setattr(task_runner, "get_task_runner", lambda: fake)
    return fake


def _job(db_session, **overrides) -> Job:
    """默认是"采集进来的 BOSS 岗位"（投递台支持的那种）。"""
    data = {
        "title": "后端开发",
        "company": "A公司",
        "source": "BOSS直聘",
        "source_url": "https://www.zhipin.com/job/1",
        "status": JOB_STATUS_OPEN,
    }
    data.update(overrides)
    job = Job(**data)
    db_session.add(job)
    db_session.commit()
    return job


def _manual_job(db_session, **overrides) -> Job:
    """纯手动录入：来源与投递链接都指不到任何招聘网站。"""
    return _job(
        db_session,
        title="朋友介绍的岗位",
        source="手动添加",
        source_url="",
        **overrides,
    )


def _enqueue_directly(db_session, job: Job, order: int = 1) -> ApplyQueueItem:
    """绕过入队校验直接写一条队列条目——用来模拟"闸门上线之前就已经在队列里的历史条目"。"""
    item = ApplyQueueItem(
        job_id=job.id,
        job_title=job.title,
        company=job.company,
        sort_order=order,
        status=QUEUE_STATUS_PENDING,
    )
    db_session.add(item)
    db_session.commit()
    return item


# ===== ① 入队闸门 =====


def test_queue_add_rejects_job_without_supported_site(client, db_session):
    job = _manual_job(db_session)

    response = client.post(
        "/api/apply/queue",
        json={"items": [{"job_id": job.id, "confirm_unanalyzed": True}]},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["site_unsupported"] is True
    assert job.title in detail["message"]
    # 消息里必须说清"支持哪些站点"，否则用户不知道该去哪儿投。
    assert "BOSS直聘" in detail["message"]
    # 而且**没有**被写进队列（不是"先加进去再拦"）。
    assert client.get("/api/apply/queue").json() == []


def test_queue_add_accepts_manual_entry_that_points_at_a_supported_site(client, db_session):
    """判据是"来源/投递链接能否归属到站点"，不是"是不是手输的"。

    手动录入但贴了 BOSS 的投递链接，投递时能定位到站点，就应当允许——否则这条规则会变成
    "必须用采集"，比用户要的"必须是 BOSS 岗位"更严，反而挡住合理用法。
    """
    job = _job(
        db_session,
        title="手动补录的岗位",
        source="手动添加",
        source_url="https://www.zhipin.com/job/detail/99",
    )

    response = client.post(
        "/api/apply/queue",
        json={"items": [{"job_id": job.id, "confirm_unanalyzed": True}]},
    )

    assert response.status_code == 200
    assert response.json()[0]["apply_supported"] is True


# ===== ② 队列列表上的标记 =====


def test_queue_list_marks_supported_and_unsupported_items(client, db_session):
    supported = _job(db_session)
    manual = _manual_job(db_session)
    client.post(
        "/api/apply/queue",
        json={"items": [{"job_id": supported.id, "confirm_unanalyzed": True}]},
    )
    # 历史遗留条目：闸门上线前就躺在队列里，只能绕过校验写进去。
    _enqueue_directly(db_session, manual, order=2)

    items = client.get("/api/apply/queue").json()
    flags = {item["job_title"]: item["apply_supported"] for item in items}

    assert flags[supported.title] is True
    assert flags[manual.title] is False


def test_deleted_job_in_queue_is_marked_unsupported(client, db_session):
    """岗位被删掉之后，队列条目只剩快照，同样不可能投递。"""
    job = _job(db_session)
    item = _enqueue_directly(db_session, job)
    db_session.delete(job)
    db_session.commit()

    items = client.get("/api/apply/queue").json()

    assert [entry["id"] for entry in items] == [item.id]
    assert items[0]["apply_supported"] is False


# ===== ③ 开始投递闸门 =====


def test_start_apply_blocks_unsupported_items_in_queue(client, db_session, fake_runner):
    good = _job(db_session)
    manual = _manual_job(db_session)
    _enqueue_directly(db_session, good, order=1)
    _enqueue_directly(db_session, manual, order=2)

    response = client.post("/api/apply/tasks", json={"use_queue": True})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["site_unsupported"] is True
    assert manual.title in detail["message"]
    # 要点名是哪几个岗位，并把"怎么处理"写进文案里。
    assert "移出投递队列" in detail["message"]
    assert detail["job_ids"] == [manual.id]
    # 一个批次都不该被建出来——否则会留下一堆注定失败的条目。
    assert db_session.query(ApplyTask).count() == 0
    assert fake_runner.started is None


def test_start_apply_blocks_explicitly_selected_unsupported_job(client, db_session, fake_runner):
    manual = _manual_job(db_session)

    response = client.post("/api/apply/tasks", json={"job_ids": [manual.id], "use_queue": False})

    assert response.status_code == 409
    assert response.json()["detail"]["site_unsupported"] is True
    assert db_session.query(ApplyTask).count() == 0


def test_start_apply_accepts_queue_with_only_supported_jobs(client, db_session, fake_runner):
    """闸门不能误伤：全是支持来源的队列照常能开始投递。"""
    job = _job(db_session)
    _enqueue_directly(db_session, job)

    response = client.post("/api/apply/tasks", json={"use_queue": True})

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert fake_runner.started is not None


# ===== ④ 单条执行兜底：失败分类要诚实 =====


def test_execute_item_reports_site_unsupported_instead_of_unknown(db_session):
    """真漏到执行层时，记录里写的是「来源不支持」，不是含糊的「未知失败」。"""
    session = db_session
    manual = _manual_job(session)
    task = ApplyTask(kind=TASK_KIND_APPLY, status=TASK_STATUS_PENDING, total=1, config={})
    session.add(task)
    session.flush()
    item = ApplyTaskItem(
        task_id=task.id,
        job_id=manual.id,
        job_title=manual.title,
        status=ITEM_STATUS_PENDING,
    )
    session.add(item)
    session.commit()

    config = apply_service.get_apply_config(session)

    with pytest.raises(Exception) as excinfo:
        task_apply.execute_item(
            session,
            task,
            item,
            config,
            client=None,
            registry=get_registry(),
            apply_service=apply_service,
        )

    assert getattr(excinfo.value, "category", None) == FAILURE_SITE_UNSUPPORTED
    assert "BOSS直聘" in str(excinfo.value)


# ===== ⑤ 岗位读取模型上的 apply_supported =====


def test_job_out_exposes_apply_supported(client, db_session):
    collected = _job(db_session)
    manual = _manual_job(db_session)

    listed = client.get("/api/jobs").json()["items"]
    flags = {job["id"]: job["apply_supported"] for job in listed}

    assert flags[collected.id] is True
    assert flags[manual.id] is False

    single = client.get(f"/api/jobs/{manual.id}").json()
    assert single["apply_supported"] is False


# ===== ⑥ 前后端共用的失败分类镜像 =====


def test_failure_categories_mirror_the_frontend():
    """`FAILURE_CATEGORIES` / `FAILURE_CATEGORY_LABELS` 与前端镜像必须逐字一致。

    这份分类是**前后端共用**的：后端写进投递记录，前端按它做筛选与展示。两处一旦漂移，
    症状是"记录里的分类在前端的筛选下拉里找不到"——不报错，只是静静地少一类。
    """
    source = FRONTEND_TYPES.read_text(encoding="utf-8")

    categories_block = re.search(r"FAILURE_CATEGORIES\s*=\s*\[(.*?)\]\s*as const", source, re.S)
    labels_block = re.search(r"FAILURE_CATEGORY_LABELS[^=]*=\s*\{(.*?)\}", source, re.S)
    assert categories_block is not None, "前端没有 FAILURE_CATEGORIES"
    assert labels_block is not None, "前端没有 FAILURE_CATEGORY_LABELS"

    frontend_categories = re.findall(r'"([^"]+)"', categories_block.group(1))
    frontend_labels = dict(re.findall(r'(\w+):\s*"([^"]*)"', labels_block.group(1)))

    assert frontend_categories == list(FAILURE_CATEGORIES)
    assert frontend_labels == FAILURE_CATEGORY_LABELS
