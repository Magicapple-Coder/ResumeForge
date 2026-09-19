"""R-13 内推管理：CRUD、stats 口径、converted 后置位派生。

重点验证：
1. 增删改查完整可用，删除走软删除；
2. ``converted`` 由关联 ``ApplicationTrack`` 后置位派生（进入面试及以上才算），
   写入侧不接受该字段；
3. ``/stats`` 只统计有效内推（非 closed/invalid），转化率 = converted / 有效内推总数。
"""
from pathlib import Path

from app.models.job import Job
from app.models.referral import Referral
from app.models.tracker import ApplicationTrack, normalize_key
from app.services import trash
from app.services.referral_service import referral_images_dir


def _job(db_session, title="后端开发工程师", company="示例公司") -> Job:
    job = Job(title=title, company=company, description="负责高并发服务")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _track(db_session, status="applied", company="示例公司", title="后端开发工程师") -> ApplicationTrack:
    track = ApplicationTrack(
        company=company,
        title=title,
        company_key=normalize_key(company),
        title_key=normalize_key(title),
        status=status,
    )
    db_session.add(track)
    db_session.commit()
    db_session.refresh(track)
    return track


def test_create_read_update_delete_round_trip(client):
    created = client.post(
        "/api/referrals",
        json={
            "company": "示例公司",
            "position": "后端开发",
            "referrer_name": "张三",
            "referrer_contact": "微信 zs",
            "relation": "前同事",
            "channel": "牛客",
            "status": "active",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["company"] == "示例公司"
    assert body["referrer_name"] == "张三"
    assert body["converted"] is False

    patched = client.patch(
        f"/api/referrals/{body['id']}", json={"status": "submitted", "note": "已递简历"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "submitted"
    assert patched.json()["note"] == "已递简历"

    assert client.delete(f"/api/referrals/{body['id']}").status_code == 204
    assert client.get("/api/referrals").json() == []


def test_binding_job_backfills_snapshots(client, db_session):
    job = _job(db_session)

    created = client.post(
        "/api/referrals",
        json={"job_id": job.id, "referrer_name": "李四"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["job_id"] == job.id
    assert body["company"] == "示例公司"
    assert body["job_title"] == "后端开发工程师"
    assert body["position"] == "后端开发工程师"


def test_converted_is_derived_from_associated_track(client, db_session):
    # 进入面试的漏斗 → converted=True。
    interview_track = _track(db_session, status="interview", company="示例公司", title="后端开发工程师")
    converted = client.post(
        "/api/referrals",
        json={"company": "示例公司", "position": "后端", "referrer_name": "张三", "track_id": interview_track.id},
    ).json()
    assert converted["converted"] is True

    # 仍停留在「已投递」的漏斗 → converted=False。
    applied_track = _track(db_session, status="applied", company="另一家公司", title="前端开发工程师")
    not_converted = client.post(
        "/api/referrals",
        json={"company": "另一家公司", "position": "前端", "referrer_name": "王五", "track_id": applied_track.id},
    ).json()
    assert not_converted["converted"] is False


def test_stats_only_counts_valid_referrals_and_derived_conversion(client, db_session):
    interview_track = _track(db_session, status="interview", company="示例公司", title="后端开发工程师")
    applied_track = _track(db_session, status="applied", company="另一家公司", title="前端开发工程师")

    client.post(
        "/api/referrals",
        json={"company": "示例公司", "position": "后端", "referrer_name": "张三", "track_id": interview_track.id},
    )
    client.post(
        "/api/referrals",
        json={"company": "另一家公司", "position": "前端", "referrer_name": "王五", "track_id": applied_track.id},
    )
    client.post(
        "/api/referrals",
        json={"company": "已关闭", "position": "数据", "referrer_name": "赵六", "status": "closed"},
    )

    stats = client.get("/api/referrals/stats").json()
    # 有效内推 = active/submitted 两条；converted 仅进入面试那条。
    assert stats["total"] == 2
    assert stats["converted"] == 1
    assert stats["rate"] == 0.5


def test_create_rejects_converted_field(client):
    # converted 是派生字段，写入侧不接受，防止在表里手算第二份口径。
    resp = client.post(
        "/api/referrals",
        json={"company": "示例公司", "position": "后端", "referrer_name": "张三", "converted": True},
    )
    assert resp.status_code == 422


def test_delete_is_soft(client, db_session):
    created = client.post(
        "/api/referrals",
        json={"company": "待删", "position": "后端", "referrer_name": "张三"},
    ).json()

    assert client.delete(f"/api/referrals/{created['id']}").status_code == 204
    assert client.get("/api/referrals").json() == []

    db_session.expire_all()
    row = db_session.get(Referral, created["id"])
    assert row is not None and trash.is_deleted(row)


PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _png_bytes(size: int = 16) -> bytes:
    """拼一段能通过文件头校验的 PNG 数据（内容不必是真实图片）。"""
    return PNG_HEADER + b"\x00" * max(0, size - len(PNG_HEADER))


def test_create_and_patch_echo_referral_code_and_note_images(client):
    created = client.post(
        "/api/referrals",
        json={
            "company": "示例公司",
            "referral_code": "ABC123",
            "note_images": ["referral_images/a.png", "referral_images/b.png"],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["referral_code"] == "ABC123"
    assert body["note_images"] == ["referral_images/a.png", "referral_images/b.png"]

    patched = client.patch(
        f"/api/referrals/{body['id']}",
        json={"referral_code": "XYZ9", "note_images": ["referral_images/c.png"]},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["referral_code"] == "XYZ9"
    assert patched.json()["note_images"] == ["referral_images/c.png"]


def test_upload_image_validates_type_and_size(client):
    # 非图片扩展名 → 422。
    bad = client.post(
        "/api/referrals/upload-image",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert bad.status_code == 422

    # 超过 2 MB → 422。
    too_big = client.post(
        "/api/referrals/upload-image",
        files={"file": ("note.png", _png_bytes(2 * 1024 * 1024 + 1), "image/png")},
    )
    assert too_big.status_code == 422


def test_upload_image_round_trip(client, db_session):
    resp = client.post(
        "/api/referrals/upload-image",
        files={"file": ("note.png", _png_bytes(32), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    path = resp.json()["path"]
    assert path.startswith("referral_images/")
    assert path.endswith(".png")

    # 落盘到测试库同目录（不是仓库 data 目录）。
    stored = referral_images_dir(db_session.get_bind()) / Path(path).name
    assert stored.is_file()

    # 通过接口能读回来。
    image = client.get(f"/api/referrals/images/{Path(path).name}")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
