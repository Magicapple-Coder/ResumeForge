"""岗位 AI 解读接口测试。"""
import json

from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider


class JobAnalysisProvider(BaseLLMProvider):
    def __init__(self):
        super().__init__(
            LLMConfig(base_url="http://localhost:9999", api_key="test", model="test-model")
        )
        self.messages: list[list[dict]] = []

    async def chat(self, messages: list[dict]) -> str:
        self.messages.append(messages)
        return json.dumps(
            {
                "summary": "该岗位重点考察门店运营、人员管理和食品安全。",
                "requirements": [
                    {
                        "priority": "high",
                        "category": "职业资格",
                        "requirement": "持有食品安全相关证书",
                        "evidence": "需要食品安全管理员证",
                    }
                ],
                "advice": [
                    {
                        "title": "准备经营案例",
                        "action": "整理一段提升门店转化率的真实案例",
                        "rationale": "岗位职责强调门店经营结果",
                    }
                ],
            },
            ensure_ascii=False,
        )

    async def stream_chat(self, messages: list[dict]):
        yield ""


def test_job_analysis_uses_saved_job_without_profile(monkeypatch, client):
    job = client.post(
        "/api/jobs",
        json={
            "title": "门店店长",
            "company": "示例连锁",
            "description": "负责门店经营和人员管理",
            "requirements": "三年零售经验",
            "additional_info": "需要食品安全管理员证",
        },
    ).json()
    provider = JobAnalysisProvider()
    monkeypatch.setattr("app.api.jobs.get_llm_config", lambda _db: provider.config)
    monkeypatch.setattr("app.api.jobs.create_provider", lambda _config: provider)

    response = client.post(f"/api/jobs/{job['id']}/analysis")

    assert response.status_code == 200
    assert response.json()["requirements"][0]["category"] == "职业资格"
    prompt = provider.messages[0][1]["content"]
    assert "门店店长" in prompt
    assert "食品安全管理员证" in prompt
    assert "个人资料" not in prompt


def test_job_analysis_requires_existing_job_and_model_config(client):
    missing = client.post("/api/jobs/999/analysis")
    assert missing.status_code == 404

    job = client.post("/api/jobs", json={"title": "教师"}).json()
    unconfigured = client.post(f"/api/jobs/{job['id']}/analysis")
    assert unconfigured.status_code == 400
    assert "配置大模型" in unconfigured.json()["detail"]
