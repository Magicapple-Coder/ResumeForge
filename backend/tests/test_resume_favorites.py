"""简历收藏接口与筛选测试。"""
from app.models.resume import ResumeRecord


def _create_resume(db_session, *, title: str = "测试简历", favorite: bool = False) -> ResumeRecord:
    record = ResumeRecord(
        title=title,
        job_title="测试岗位",
        content={"name": "测试用户"},
        favorite=favorite,
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


def test_resume_favorite_defaults_to_false_and_can_be_toggled(client, db_session):
    record = _create_resume(db_session)

    response = client.patch(
        f"/api/resumes/{record.id}/favorite",
        json={"favorite": True},
    )

    assert response.status_code == 200
    assert response.json()["favorite"] is True
    detail = client.get(f"/api/resumes/{record.id}")
    assert detail.json()["favorite"] is True


def test_resume_list_filters_favorites_and_combines_with_keyword(client, db_session):
    favorite = _create_resume(db_session, title="后端岗位简历", favorite=True)
    _create_resume(db_session, title="前端岗位简历", favorite=False)

    response = client.get(
        "/api/resumes",
        params={"favorite": "true", "keyword": "后端"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == favorite.id


def test_update_resume_favorite_returns_404_for_missing_record(client):
    response = client.patch("/api/resumes/999/favorite", json={"favorite": True})

    assert response.status_code == 404
