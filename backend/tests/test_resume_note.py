"""简历备注：列表可见、详情可编辑（B5）。"""
from app.models.resume import ResumeRecord


def _create_resume(db_session, *, title: str = "测试简历", note: str = "") -> ResumeRecord:
    record = ResumeRecord(title=title, job_title="测试岗位", content={"name": "测试用户"}, note=note)
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


def test_resume_note_defaults_to_empty_and_is_listed(client, db_session):
    record = _create_resume(db_session)

    listed = client.get("/api/resumes").json()
    assert listed["items"][0]["id"] == record.id
    assert listed["items"][0]["note"] == ""
    assert client.get(f"/api/resumes/{record.id}").json()["note"] == ""


def test_update_resume_note_persists_and_does_not_touch_content(client, db_session):
    record = _create_resume(db_session)

    response = client.patch(f"/api/resumes/{record.id}/note", json={"note": "重点突出量化成果"})

    assert response.status_code == 200
    assert response.json()["note"] == "重点突出量化成果"
    detail = client.get(f"/api/resumes/{record.id}").json()
    assert detail["note"] == "重点突出量化成果"
    # 备注只改备注，不覆盖正文/名称。
    assert detail["content"]["name"] == "测试用户"
    assert detail["title"] == "测试简历"
    assert client.get("/api/resumes").json()["items"][0]["note"] == "重点突出量化成果"


def test_update_resume_note_returns_404_for_missing_record(client):
    response = client.patch("/api/resumes/999/note", json={"note": "x"})

    assert response.status_code == 404


def test_update_resume_note_rejects_an_overlong_note(client, db_session):
    record = _create_resume(db_session)

    response = client.patch(f"/api/resumes/{record.id}/note", json={"note": "长" * 2001})

    assert response.status_code == 422
