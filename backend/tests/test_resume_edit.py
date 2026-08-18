"""简历内容手工修改的 API 测试。"""
from app.models.resume import ResumeRecord


def _create_resume(db_session) -> ResumeRecord:
    record = ResumeRecord(
        title="张三-后端开发工程师",
        job_title="后端开发工程师",
        company="示例公司",
        model="test-model",
        enhancement_enabled=True,
        enhancement_level="strong",
        content={"name": "旧名字", "summary": "旧总结"},
        warnings=["请核对学校信息"],
        parse_error="原始生成结果解析失败",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


def test_update_resume_persists_content_and_clears_stale_generation_state(client, db_session):
    record = _create_resume(db_session)
    payload = {
        "name": "新名字",
        "job_intent": "后端开发工程师",
        "summary": "手工调整后的总结",
        "skills": [{"name": "Python", "level": "熟练"}],
        "projects": [
            {
                "name": "简历生成工具",
                "role": "开发者",
                "description": ["增加预览中的手工编辑能力"],
            }
        ],
    }

    response = client.put(f"/api/resumes/{record.id}", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == record.id
    assert body["title"] == record.title
    assert body["model"] == "test-model"
    assert body["enhancement_enabled"] is True
    assert body["enhancement_level"] == "strong"
    assert "tone" not in body
    assert body["content"]["name"] == "新名字"
    assert body["content"]["projects"][0]["description"] == ["增加预览中的手工编辑能力"]
    assert body["warnings"] == []
    assert body["parse_error"] == ""

    db_session.refresh(record)
    assert record.content["summary"] == "手工调整后的总结"
    assert record.warnings == []
    assert record.parse_error == ""


def test_update_resume_rejects_invalid_content(client, db_session):
    record = _create_resume(db_session)

    response = client.put(
        f"/api/resumes/{record.id}",
        json={"name": "张三", "photo": "https://example.com/avatar.png"},
    )

    assert response.status_code == 422
    assert "base64 data URL" in response.text


def test_update_resume_returns_404_for_missing_record(client):
    response = client.put("/api/resumes/999", json={"name": "张三"})

    assert response.status_code == 404


def test_create_manual_resume_is_linked_and_marked_as_user_written(client):
    job_response = client.post(
        "/api/jobs",
        json={"title": "客户端开发工程师", "company": "示例公司"},
    )
    assert job_response.status_code == 201
    job_id = job_response.json()["id"]

    response = client.post(
        "/api/resumes/manual",
        json={
            "job_id": job_id,
            "content": {
                "name": "张三",
                "job_intent": "客户端开发工程师",
                "summary": "用户自行整理的简历内容",
                "projects": [{"name": "简历工具", "description": ["负责功能开发"]}],
            },
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "manual"
    assert body["job_id"] == job_id
    assert body["company"] == "示例公司"
    assert body["model"] == ""
    assert "张三-示例公司-客户端开发工程师-" in body["title"]

    listed = client.get("/api/resumes", params={"job_id": job_id})
    assert listed.status_code == 200
    assert listed.json()["items"][0]["source"] == "manual"


def test_create_manual_resume_without_job_uses_profile_intent(client):
    response = client.post(
        "/api/resumes/manual",
        json={"content": {"name": "李四", "job_intent": "后端开发工程师"}},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "manual"
    assert body["job_id"] is None
    assert body["job_title"] == "后端开发工程师"
    assert body["title"].startswith("李四-自定义简历-")
