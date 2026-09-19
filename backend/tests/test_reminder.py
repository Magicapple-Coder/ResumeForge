"""R-12 日历提醒：CRUD、upcoming 升序、绑定对象 SET NULL、软删除。

重点验证：
1. 增删改查完整可用，删除走软删除（列表不可见、行仍在）；
2. ``upcoming`` 只返回 pending 且按 ``remind_at`` 升序；
3. 绑定漏斗/岗位/简历后，被绑对象删除不连坐（外键 SET NULL）。
"""
from datetime import timedelta

from app.models.job import Job
from app.models.profile import utcnow
from app.models.reminder import Reminder
from app.models.resume import ResumeRecord
from app.models.tracker import ApplicationTrack
from app.services import trash
from app.services.reminder_service import reminder_urgency


def _job(db_session, title="后端开发工程师", company="示例公司") -> Job:
    job = Job(title=title, company=company, description="负责高并发服务")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _track(db_session, status="applied") -> ApplicationTrack:
    track = ApplicationTrack(company="示例公司", title="后端开发工程师", status=status)
    db_session.add(track)
    db_session.commit()
    db_session.refresh(track)
    return track


def _resume(db_session) -> ResumeRecord:
    resume = ResumeRecord(title="我的简历", content={})
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(resume)
    return resume


def test_create_list_patch_delete_round_trip(client):
    created = client.post(
        "/api/reminders",
        json={
            "title": "参加某司面试",
            "remind_at": "2026-09-21T10:00:00",
            "kind": "interview",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "参加某司面试"
    assert body["kind"] == "interview"
    assert body["status"] == "pending"

    assert len(client.get("/api/reminders").json()) == 1

    patched = client.patch(
        f"/api/reminders/{body['id']}", json={"status": "done", "note": "已面完"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "done"
    assert patched.json()["note"] == "已面完"

    assert client.delete(f"/api/reminders/{body['id']}").status_code == 204
    assert client.get("/api/reminders").json() == []


def test_upcoming_only_pending_and_ascending(client):
    client.post(
        "/api/reminders",
        json={"title": "晚一点的提醒", "remind_at": "2026-10-02T09:00:00", "kind": "other"},
    )
    client.post(
        "/api/reminders",
        json={"title": "早一点的提醒", "remind_at": "2026-09-25T09:00:00", "kind": "hr_reply"},
    )
    done = client.post(
        "/api/reminders",
        json={"title": "已完成", "remind_at": "2026-09-20T09:00:00", "kind": "other"},
    ).json()
    client.patch(f"/api/reminders/{done['id']}", json={"status": "done"})

    upcoming = client.get("/api/reminders/upcoming").json()
    assert [item["title"] for item in upcoming] == ["早一点的提醒", "晚一点的提醒"]


def test_binding_job_hard_delete_sets_null(client, db_session):
    job = _job(db_session)
    track = _track(db_session)
    resume = _resume(db_session)

    created = client.post(
        "/api/reminders",
        json={
            "title": "绑定三个对象",
            "remind_at": "2026-09-22T10:00:00",
            "kind": "interview",
            "track_id": track.id,
            "job_id": job.id,
            "resume_id": resume.id,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["job_id"] == job.id
    assert created.json()["track_id"] == track.id
    assert created.json()["resume_id"] == resume.id

    # 硬删除岗位：外键 SET NULL，提醒仍在、只是失去岗位关联。
    db_session.delete(job)
    db_session.commit()
    got = client.get("/api/reminders")
    assert got.status_code == 200
    item = [row for row in got.json() if row["id"] == created.json()["id"]][0]
    assert item["job_id"] is None
    assert item["track_id"] == track.id
    assert item["resume_id"] == resume.id


def test_delete_is_soft_and_hides_from_list(client, db_session):
    created = client.post(
        "/api/reminders",
        json={"title": "待删提醒", "remind_at": "2026-09-23T10:00:00"},
    ).json()

    assert client.delete(f"/api/reminders/{created['id']}").status_code == 204
    assert client.get("/api/reminders").json() == []

    db_session.expire_all()
    row = db_session.get(Reminder, created["id"])
    assert row is not None and trash.is_deleted(row)


def test_validation_rejects_blank_title_and_bad_kind(client):
    assert client.post("/api/reminders", json={"title": "  ", "remind_at": "2026-09-21T10:00:00"}).status_code == 422
    assert client.post(
        "/api/reminders",
        json={"title": "x", "remind_at": "2026-09-21T10:00:00", "kind": "unknown_kind"},
    ).status_code == 422


def test_reminder_urgency_mapping_and_labels():
    now = utcnow().replace(hour=12, minute=0, second=0, microsecond=0)

    assert reminder_urgency(now - timedelta(days=2, hours=1), now) == ("overdue", "已逾期 2 天")
    assert reminder_urgency(now + timedelta(hours=2), now) == ("soon", "今天")
    assert reminder_urgency(now + timedelta(days=1), now) == ("soon", "明天")
    assert reminder_urgency(now + timedelta(hours=25), now) == ("upcoming", "明天")
    assert reminder_urgency(now + timedelta(days=3), now) == ("upcoming", "3 天后")
    assert reminder_urgency(now + timedelta(days=4), now) == ("later", "4 天后")


def test_upcoming_enriches_urgency_and_sorts(client):
    now = utcnow()

    client.post("/api/reminders", json={"title": "later", "remind_at": (now + timedelta(days=5)).isoformat()})
    client.post("/api/reminders", json={"title": "soon", "remind_at": (now + timedelta(hours=3)).isoformat()})
    client.post("/api/reminders", json={"title": "overdue", "remind_at": (now - timedelta(days=2)).isoformat()})
    client.post("/api/reminders", json={"title": "upcoming", "remind_at": (now + timedelta(days=2)).isoformat()})

    data = client.get("/api/reminders/upcoming").json()
    assert [item["title"] for item in data] == ["overdue", "soon", "upcoming", "later"]

    by_title = {item["title"]: item for item in data}
    assert by_title["overdue"]["urgency"] == "overdue"
    assert by_title["overdue"]["due_label"] == "已逾期 2 天"
    assert by_title["soon"]["urgency"] == "soon"
    assert by_title["soon"]["due_label"] in {"今天", "明天"}
    assert by_title["upcoming"]["urgency"] == "upcoming"
    assert by_title["upcoming"]["due_label"] == "2 天后"
    assert by_title["later"]["urgency"] == "later"
    assert by_title["later"]["due_label"] == "5 天后"


def test_reminder_popup_setting_default_and_toggle(client):
    # 缺失时默认开启。
    assert client.get("/api/settings/reminder-popup").json() == {"enabled": True}

    # 关闭后持久化。
    assert client.put("/api/settings/reminder-popup", json={"enabled": False}).json() == {"enabled": False}
    assert client.get("/api/settings/reminder-popup").json() == {"enabled": False}

    # 重新开启。
    assert client.put("/api/settings/reminder-popup", json={"enabled": True}).json() == {"enabled": True}
    assert client.get("/api/settings/reminder-popup").json() == {"enabled": True}
