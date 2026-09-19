"""R-15 面经知识库：CRUD、软删除、绑定岗位快照、真实问题清单落库。

重点验证：
1. 增删改查完整可用，删除走软删除（列表与单条都不可见，但仍可恢复）；
2. 绑定岗位时回填公司/岗位快照，删岗位后面经仍在；
3. 真实问题清单落在 ``questions`` 字段（与 R-11 即时题库互补）。
"""
from app.models.interview_experience import InterviewExperience
from app.models.job import Job
from app.services import trash


def _job(db_session, title="后端开发工程师", company="示例公司") -> Job:
    job = Job(title=title, company=company, description="负责高并发服务")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def test_create_read_update_delete_round_trip(client):
    created = client.post(
        "/api/interview-experiences",
        json={
            "title": "某司一面",
            "company": "示例公司",
            "position": "后端开发",
            "content": "先问八股再深挖项目",
            "questions": ["说一个你主导的项目", "这个指标怎么算的"],
            "tags": ["后端", "一面"],
            "source": "self",
            "round_type": "一面",
            "interview_date": "2026-09-20",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["questions"] == ["说一个你主导的项目", "这个指标怎么算的"]
    assert body["source"] == "self"

    got = client.get(f"/api/interview-experiences/{body['id']}")
    assert got.status_code == 200
    assert got.json()["title"] == "某司一面"

    updated = client.put(
        f"/api/interview-experiences/{body['id']}",
        json={
            "title": "某司一面（已更新）",
            "company": "示例公司",
            "position": "后端开发",
            "content": "补充了追问",
            "questions": ["说一个你主导的项目"],
            "tags": ["后端"],
            "source": "peer",
            "round_type": "一面",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "某司一面（已更新）"
    assert updated.json()["source"] == "peer"

    assert client.delete(f"/api/interview-experiences/{body['id']}").status_code == 204
    assert client.get(f"/api/interview-experiences/{body['id']}").status_code == 404


def test_delete_is_soft_and_hides_from_list(client, db_session):
    created = client.post(
        "/api/interview-experiences",
        json={"title": "待删面经", "company": "某司", "content": "内容"},
    ).json()

    assert len(client.get("/api/interview-experiences").json()) == 1
    assert client.delete(f"/api/interview-experiences/{created['id']}").status_code == 204
    assert client.get("/api/interview-experiences").json() == []

    # 软删除：行还在，只是被标记。
    db_session.expire_all()
    row = db_session.get(InterviewExperience, created["id"])
    assert row is not None and trash.is_deleted(row)


def test_binding_job_snapshots_company_and_position(client, db_session):
    job = _job(db_session)

    created = client.post(
        "/api/interview-experiences",
        json={"title": "绑定岗位的面经", "job_id": job.id, "content": "内容"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["job_id"] == job.id
    assert body["company"] == "示例公司"
    assert body["position"] == "后端开发工程师"


def test_experience_survives_job_soft_delete(client, db_session):
    job = _job(db_session)
    created = client.post(
        "/api/interview-experiences",
        json={"title": "不连坐面经", "job_id": job.id, "content": "内容"},
    ).json()

    # 岗位软删除（回收站）不影响面经的读取与公司/岗位快照。
    assert client.delete(f"/api/jobs/{job.id}").status_code == 204
    got = client.get(f"/api/interview-experiences/{created['id']}")
    assert got.status_code == 200
    assert got.json()["company"] == "示例公司"
    assert got.json()["position"] == "后端开发工程师"


def test_job_hard_delete_sets_experience_job_id_null(db_session):
    job = _job(db_session)
    experience = InterviewExperience(
        title="外键置空", company="示例公司", position="后端开发", job_id=job.id, content="内容"
    )
    db_session.add(experience)
    db_session.commit()
    db_session.refresh(experience)

    db_session.delete(job)
    db_session.commit()

    db_session.refresh(experience)
    assert experience.job_id is None
    assert experience.company == "示例公司"
    assert experience.position == "后端开发"


def test_validation_rejects_bad_source_and_requires_content(client):
    assert client.post("/api/interview-experiences", json={"source": "未知来源"}).status_code == 422
    # 标题、公司、正文、问题清单四者至少其一。
    assert client.post("/api/interview-experiences", json={"title": ""}).status_code == 422
