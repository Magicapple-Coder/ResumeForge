"""投递台 API 冒烟测试：准入冲突、去重、错误码、显式开始、记录、配置、浏览器状态。

执行批次用**假运行器**替换单例（不真起线程、不连浏览器），只验证路由与准入逻辑。
"""
import pytest

from app.models.apply import (
    ADMISSION_BLOCK,
    TASK_KIND_COLLECT,
    ApplyTask,
    ApplyTaskItem,
    JobMatchAnalysis,
)
from app.models.job import JOB_STATUS_OPEN, Job
from app.models.profile import UserProfile, utcnow
from app.schemas.job_match import JobMatchResult, MatchCondition
from app.services.apply import apply_service, task_runner
from app.services.job_match import finalize_match_result


class FakeRunner:
    def __init__(self) -> None:
        self.running = False
        self.started: int | None = None
        self.actions: list[tuple[str, int]] = []

    def is_running(self) -> bool:
        return self.running

    def start(self, task_id: int) -> None:
        self.started = task_id

    def pause(self, task_id: int) -> None:
        self.actions.append(("pause", task_id))

    def resume(self, task_id: int) -> None:
        self.actions.append(("resume", task_id))

    def stop(self, task_id: int) -> None:
        self.actions.append(("stop", task_id))


@pytest.fixture
def fake_runner(monkeypatch) -> FakeRunner:
    fake = FakeRunner()
    monkeypatch.setattr(task_runner, "get_task_runner", lambda: fake)
    apply_service.reset_browser_manager()
    yield fake
    apply_service.reset_browser_manager()


def _job(db_session, **overrides) -> Job:
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


def _profile(db_session) -> UserProfile:
    profile = UserProfile(name="张三", job_intent="后端开发")
    db_session.add(profile)
    db_session.commit()
    return profile


def _blocked_match(db_session, job_id: int) -> None:
    result = finalize_match_result(
        JobMatchResult(
            hard_conditions=[
                MatchCondition(label="硕士及以上", status="real_gap", evidence="资料中未提供")
            ]
        )
    )
    assert result.admission == ADMISSION_BLOCK
    apply_service.persist_match(db_session, db_session.get(Job, job_id), result)


# ===== 队列准入 =====


def test_queue_add_requires_confirmation_for_unanalyzed_job(client, db_session, fake_runner):
    job = _job(db_session)

    response = client.post("/api/apply/queue", json={"items": [{"job_id": job.id}]})

    assert response.status_code == 409
    assert response.json()["detail"]["unanalyzed"] is True


def test_queue_add_with_confirmation_succeeds_then_dedupes(client, db_session, fake_runner):
    job = _job(db_session)

    first = client.post(
        "/api/apply/queue",
        json={"items": [{"job_id": job.id, "confirm_unanalyzed": True}]},
    )
    assert first.status_code == 200
    assert len(first.json()) == 1

    second = client.post(
        "/api/apply/queue",
        json={"items": [{"job_id": job.id, "confirm_unanalyzed": True}]},
    )
    assert second.status_code == 409


def test_queue_add_blocks_real_gap_until_confirmed(client, db_session, fake_runner):
    job = _job(db_session)
    _blocked_match(db_session, job.id)

    blocked = client.post("/api/apply/queue", json={"items": [{"job_id": job.id}]})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["gaps"] == ["硕士及以上"]

    confirmed = client.post(
        "/api/apply/queue",
        json={"items": [{"job_id": job.id, "confirm_real_gap": True}]},
    )
    assert confirmed.status_code == 200


def test_queue_treats_empty_match_conclusion_as_needs_confirmation(client, db_session, fake_runner):
    """纵深防御：脏的匹配结论（空结果 / hard_gate=unknown / requires_confirm=False）不得默认放行。

    正常链路 ``persist_match`` 经 ``finalize_match_result`` 必然写合法值；这里**直接落一条脏行**
    模拟回归或历史数据。准入是安全闸门，读不出可用结论时必须按「需确认」处理
    （``requires_confirm=True``），而不是被当成可自动投递的 ALLOWED。
    """
    job = _job(db_session)
    db_session.add(
        JobMatchAnalysis(job_id=job.id, result={}, hard_gate="unknown", requires_confirm=False)
    )
    db_session.commit()

    response = client.post("/api/apply/queue", json={"items": [{"job_id": job.id}]})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["requires_confirm"] is True


def test_queue_reorder_and_delete(client, db_session, fake_runner):
    job_a = _job(db_session, title="岗位A", source_url="https://www.zhipin.com/job/a")
    job_b = _job(db_session, title="岗位B", source_url="https://www.zhipin.com/job/b")
    created = client.post(
        "/api/apply/queue",
        json={
            "items": [
                {"job_id": job_a.id, "confirm_unanalyzed": True},
                {"job_id": job_b.id, "confirm_unanalyzed": True},
            ]
        },
    ).json()
    id_a, id_b = created[0]["id"], created[1]["id"]

    reordered = client.patch("/api/apply/queue/reorder", json={"order": [id_b, id_a]})
    assert reordered.status_code == 200
    assert [item["id"] for item in reordered.json()] == [id_b, id_a]

    assert client.delete(f"/api/apply/queue/{id_a}").status_code == 204
    assert len(client.get("/api/apply/queue").json()) == 1


# ===== 执行批次 =====


def test_create_task_requires_explicit_targets(client, db_session, fake_runner):
    response = client.post("/api/apply/tasks", json={})

    assert response.status_code == 400


def test_create_task_with_job_ids_starts_runner(client, db_session, fake_runner):
    job = _job(db_session)

    response = client.post("/api/apply/tasks", json={"job_ids": [job.id]})

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "apply"
    assert body["total"] == 1
    assert fake_runner.started == body["id"]

    current = client.get("/api/apply/tasks/current")
    assert current.status_code == 200
    assert current.json()["id"] == body["id"]

    detail = client.get(f"/api/apply/tasks/{body['id']}")
    assert detail.status_code == 200
    assert len(detail.json()["items"]) == 1


def test_task_control_endpoints(client, db_session, fake_runner):
    job = _job(db_session)
    task_id = client.post("/api/apply/tasks", json={"job_ids": [job.id]}).json()["id"]

    assert client.post(f"/api/apply/tasks/{task_id}/pause").status_code == 200
    assert client.post(f"/api/apply/tasks/{task_id}/resume").status_code == 200
    assert client.post(f"/api/apply/tasks/{task_id}/stop").status_code == 200
    assert ("stop", task_id) in fake_runner.actions


def test_daily_limit_blocks_new_task(client, db_session, fake_runner):
    job = _job(db_session)
    client.put("/api/apply/config", json={"daily_limit": 1})
    parent = ApplyTask(kind="apply", status="completed", total=1, config={})
    db_session.add(parent)
    db_session.flush()
    db_session.add(
        ApplyTaskItem(
            task_id=parent.id,
            job_id=job.id,
            job_title=job.title,
            status="success",
            finished_at=utcnow(),
        )
    )
    db_session.commit()

    response = client.post("/api/apply/tasks", json={"job_ids": [job.id]})

    assert response.status_code == 409


# ===== 配置 / 浏览器 / 记录 =====


def test_config_roundtrip_and_validation(client, fake_runner):
    defaults = client.get("/api/apply/config")
    assert defaults.status_code == 200
    assert defaults.json()["interval_seconds"] == 25

    saved = client.put("/api/apply/config", json={"interval_seconds": 10, "daily_limit": 30})
    assert saved.status_code == 200
    assert client.get("/api/apply/config").json()["interval_seconds"] == 10

    invalid = client.put("/api/apply/config", json={"interval_seconds": 0})
    assert invalid.status_code == 422


def test_browser_status_reports_stopped(client, fake_runner):
    response = client.get("/api/apply/browser/status")

    assert response.status_code == 200
    assert response.json()["state"] == "stopped"
    assert response.json()["port"] == 9333
    # 启动浏览器时要用这个地址打开招聘网站，界面上也用它做「打开招聘网站」。
    assert response.json()["entry_url"] == "https://www.zhipin.com/"
    # 界面要能显示"实际用的是哪个浏览器"，所以状态里带上人类可读的名字。
    assert "browser_name" in response.json()


def test_config_exposes_browser_and_site_fields(client, fake_runner):
    body = client.get("/api/apply/config").json()

    assert body["browser_choice"] == "auto"
    assert body["browser_path"] == ""
    assert body["site_key"] == "boss"
    assert body["defaults"]["browser_choice"] == "auto"
    assert body["defaults"]["site_key"] == "boss"


def test_browser_choice_roundtrip_and_validation(client, fake_runner):
    saved = client.put("/api/apply/config", json={"browser_choice": "chrome"})
    assert saved.status_code == 200
    assert saved.json()["browser_choice"] == "chrome"

    invalid = client.put("/api/apply/config", json={"browser_choice": "firefox"})
    assert invalid.status_code == 422


def test_sites_endpoint_lists_registered_sites_and_current(client, fake_runner):
    response = client.get("/api/apply/sites")

    assert response.status_code == 200
    body = response.json()
    assert body["current"] == "boss"
    assert [site["key"] for site in body["sites"]] == ["boss"]
    boss = body["sites"][0]
    assert boss["display_name"] == "BOSS直聘"
    assert boss["host"] == "zhipin.com"
    assert boss["entry_url"] == "https://www.zhipin.com/"
    assert boss["supports_collect"] is True
    assert boss["supports_apply"] is True


def test_browser_manager_is_rebuilt_when_choice_or_path_changes(db_session, fake_runner):
    """配置变更必须真正生效：选择项或路径变了就要重建浏览器管理器，而不是继续用旧的。"""
    apply_service.save_apply_config(db_session, apply_service.ApplyConfigIn(browser_choice="auto"))
    first = apply_service.get_browser_manager(db_session)

    apply_service.save_apply_config(db_session, apply_service.ApplyConfigIn(browser_choice="edge"))
    second = apply_service.get_browser_manager(db_session)

    assert second is not first
    assert second._browser_choice == "edge"

    # 同一配置重复取用应命中缓存（不重建）。
    again = apply_service.get_browser_manager(db_session)
    assert again is second

    # 自定义路径变化同样要重建。
    apply_service.save_apply_config(
        db_session,
        apply_service.ApplyConfigIn(browser_choice="custom", browser_path="C:/x/mybrowser.exe"),
    )
    third = apply_service.get_browser_manager(db_session)
    assert third is not second


def test_browser_open_needs_a_running_browser(client, fake_runner):
    """浏览器没起来时不能假装导航成功，要给出可展示的中文提示。"""
    response = client.post("/api/apply/browser/open")

    assert response.status_code == 409
    assert "请先启动投递专用浏览器" in response.json()["detail"]


def test_records_endpoint_returns_a_page(client, db_session, fake_runner):
    response = client.get("/api/apply/records")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


# ===== 采集 =====


def test_collect_config_and_task(client, db_session, fake_runner):
    assert client.put("/api/collect/config", json={"keywords": ["后端"], "city": "北京"}).status_code == 200

    created = client.post("/api/collect/tasks")
    assert created.status_code == 200
    assert created.json()["kind"] == "collect"

    detail = client.get(f"/api/collect/tasks/{created.json()['id']}")
    assert detail.status_code == 200


def test_collect_task_requires_keywords(client, db_session, fake_runner):
    response = client.post("/api/collect/tasks")

    assert response.status_code == 400


def test_collect_task_omits_the_sample_flag_by_default(client, db_session, fake_runner):
    """默认不保存站点原文：不带该字段时任务 config 里**没有**这个键（保持旧任务的形状）。"""
    client.put("/api/collect/config", json={"keywords": ["后端"], "city": "北京"})

    created = client.post("/api/collect/tasks")

    assert created.status_code == 200
    assert "save_site_samples" not in created.json()["config"]


def test_collect_task_carries_the_sample_flag_when_requested(client, db_session, fake_runner):
    """请求体里带 ``save_site_samples=true`` 才写进 task.config，运行器据此安装录制装饰器。"""
    client.put("/api/collect/config", json={"keywords": ["后端"], "city": "北京"})

    created = client.post("/api/collect/tasks", json={"save_site_samples": True})

    assert created.status_code == 200
    assert created.json()["config"]["save_site_samples"] is True


def test_sample_flag_is_not_a_persisted_collect_config_field(client, db_session, fake_runner):
    """``save_site_samples`` 是每次采集一次性的，**不进**保存的采集配置：往返后不出现该键，
    而且把它塞进配置接口会被 ``extra="forbid"`` 拒绝（免得它变成一个会被回显的持久设置）。"""
    assert (
        client.put(
            "/api/collect/config", json={"keywords": ["后端"], "save_site_samples": True}
        ).status_code
        == 422
    )

    saved = client.put("/api/collect/config", json={"keywords": ["后端"], "city": "北京"})
    assert saved.status_code == 200
    body = client.get("/api/collect/config").json()
    assert "save_site_samples" not in body


# ===== 补齐详情（按岗位点名补抓 JD，仍然是 kind=collect）=====


def test_create_backfill_task_rejects_an_empty_selection(db_session, fake_runner):
    """空选择不能在业务层被放过：前端万一送来空数组，要给出一条可操作的中文提示，
    而不是建出一个"没岗位可补"的空任务。"""
    with pytest.raises(apply_service.ApplyBadRequest) as excinfo:
        apply_service.create_backfill_task(db_session, [])

    assert "选择" in excinfo.value.detail


def test_create_backfill_task_explains_the_batch_limit(db_session, fake_runner):
    """超过单批上限（200）时，报错文案必须给出可操作的说明（含上限数字 + "分批"），
    而不是一句干巴巴的"参数错误"——用户得知道该怎么做。"""
    ids = list(range(1, 202))  # 201 条 > MAX_BACKFILL_JOBS

    with pytest.raises(apply_service.ApplyBadRequest) as excinfo:
        apply_service.create_backfill_task(db_session, ids)

    message = excinfo.value.detail
    assert "200" in message
    assert "分批" in message


def test_create_backfill_task_dedupes_and_preserves_order(db_session, fake_runner):
    """重复 id 去重、且**保序**：``total`` 用去重后的数量，config 里的目标清单也去重保序
    （前端分批提交时会出现重复 id，不去重会让同一岗位被补两次、进度也虚高）。"""
    task = apply_service.create_backfill_task(db_session, [30, 10, 30, 20, 10])

    assert task.kind == TASK_KIND_COLLECT
    assert task.total == 3
    assert task.config["backfill_job_ids"] == [30, 10, 20]
    assert fake_runner.started == task.id


def test_create_backfill_task_conflicts_with_a_running_task(db_session, fake_runner):
    """同一时刻只跑一个批次：已有任务在跑时不许再建补详情任务，否则两个任务抢同一个浏览器。"""
    fake_runner.running = True

    with pytest.raises(apply_service.ApplyConflict):
        apply_service.create_backfill_task(db_session, [1])


def test_backfill_route_rejects_an_empty_selection(client, fake_runner):
    """路由层：空数组（或空 body）→ 400，错误来自业务层那句中文提示，不是 422 的校验噪音。"""
    assert client.post("/api/collect/backfill", json={"job_ids": []}).status_code == 400
    assert client.post("/api/collect/backfill", json={}).status_code == 400


def test_backfill_route_creates_a_collect_task(client, fake_runner):
    """正常路径：返回 kind=collect 的任务（不新增任务类型），total 与目标清单都正确。"""
    response = client.post("/api/collect/backfill", json={"job_ids": [5, 6, 5]})

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "collect"
    assert body["total"] == 2
    assert body["config"]["backfill_job_ids"] == [5, 6]


def test_backfill_route_is_registered():
    """把路由名与它对外的路径绑死：改名会让前端 ``startBackfill`` 静默打到一个 404 上
    （与 datasets/skills 那两条"中间件豁免常量绑死"同一手法）。"""
    from app.application import create_app

    assert "/api/collect/backfill" in set(create_app().openapi()["paths"])


# ===== 匹配分析 =====


def test_match_analysis_requires_profile(client, db_session, fake_runner):
    job = _job(db_session)

    response = client.post(f"/api/jobs/{job.id}/match-analysis")

    assert response.status_code == 400


def test_match_analysis_local_fallback_and_lifecycle(client, db_session, fake_runner):
    job = _job(db_session)
    _profile(db_session)

    created = client.post(f"/api/jobs/{job.id}/match-analysis")
    assert created.status_code == 200
    body = created.json()
    assert body["admission"] == "needs_confirm"
    assert any("未配置大模型" in note for note in body["notes"])

    fetched = client.get(f"/api/jobs/{job.id}/match-analysis")
    assert fetched.status_code == 200
    assert fetched.json()["id"] > 0
    assert fetched.json()["result"]["admission"] == "needs_confirm"

    assert client.delete(f"/api/jobs/{job.id}/match-analysis").status_code == 204
    empty = client.get(f"/api/jobs/{job.id}/match-analysis")
    assert empty.json()["id"] == 0


def test_match_analysis_missing_job_returns_404(client, fake_runner):
    assert client.post("/api/jobs/9999/match-analysis").status_code == 404
