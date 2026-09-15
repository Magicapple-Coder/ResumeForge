"""简历生成 API 集成冒烟测试。"""

import json

from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider

def test_generate_requires_profile_and_llm(client):
    # 无资料、无 LLM 配置时生成接口应给出明确的 400 提示
    client.post("/api/jobs", json={"title": "后端开发工程师", "company": "A公司"})
    response = client.post("/api/resumes/generate", json={"job_id": 1})
    assert response.status_code == 400


def test_generate_accepts_campus_experience_as_profile(client):
    client.post("/api/jobs", json={"title": "客户端开发工程师", "company": "A公司"})
    profile_response = client.put(
        "/api/profile",
        json={
            "campus_experiences": [{"organization": "学生会", "role": "部长"}],
        },
    )
    assert profile_response.status_code == 200

    response = client.post("/api/resumes/generate", json={"job_id": 1})
    assert response.status_code == 400
    assert "配置大模型" in response.json()["detail"]


def test_generate_saves_before_done_and_persists_resume(client, monkeypatch):
    job = client.post(
        "/api/jobs",
        json={
            "title": "后端开发工程师",
            "company": "示例公司",
            "requirements": "熟悉 Python 与 API 设计",
        },
    ).json()
    profile = client.put(
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
    )
    assert profile.status_code == 200
    config = LLMConfig(
        base_url="https://api.example.com/v1",
        api_key="integration-secret",
        model="integration-model",
    )
    assert client.put("/api/settings/llm", json=config.model_dump()).status_code == 200

    class SuccessfulProvider(BaseLLMProvider):
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

    monkeypatch.setattr(
        "app.api.resumes.create_provider",
        lambda resolved: SuccessfulProvider(resolved),
    )
    response = client.post("/api/resumes/generate", json={"job_id": job["id"]})

    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    event_types = [event["type"] for event in events]
    assert event_types.index("saved") < event_types.index("done")
    saved_event = next(event for event in events if event["type"] == "saved")
    done_event = next(event for event in events if event["type"] == "done")

    persisted = client.get(f"/api/resumes/{saved_event['record_id']}")
    assert persisted.status_code == 200
    assert persisted.json()["content"] == done_event["resume"]
    assert persisted.json()["job_id"] == job["id"]
    assert persisted.json()["company"] == "示例公司"
