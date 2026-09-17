"""事实台账的 HTTP 面：路由顺序、错误码、草拟接口的两条路径。

路由顺序单独有一条测试：``/baseline`` 与 ``/draft`` 是固定路径，必须排在带路径参数的
``/{claim_id}`` 之前。排错了不会 404，而是把 ``baseline`` 当成整数解析失败返回 422，
看起来像"参数写错了"，很容易查偏。
"""
import json


from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider, LLMError

VALID = {
    "title": "检索接口",
    "category": "项目经历",
    "subject": "校园知识检索平台",
    "source_fact": "负责检索接口的实现与联调。",
    "candidate_wording": "实现检索接口并联调上线",
    "responsibility_level": "参与",
    "verification_status": "待确认",
}


class ScriptedProvider(BaseLLMProvider):
    def __init__(self, response: str):
        super().__init__(LLMConfig(base_url="http://fake", model="fake-model"))
        self.response = response
        self.messages: list[dict] | None = None

    async def chat(self, messages: list[dict]) -> str:
        self.messages = messages
        return self.response

    async def stream_chat(self, messages: list[dict]):  # pragma: no cover - 未用到
        yield ""


class FailingProvider(BaseLLMProvider):
    def __init__(self):
        super().__init__(LLMConfig(base_url="http://fake", model="fake-model"))

    async def chat(self, messages: list[dict]) -> str:
        raise LLMError("模型不可用")

    async def stream_chat(self, messages: list[dict]):  # pragma: no cover - 未用到
        yield ""


def _configure_llm(monkeypatch, provider):
    monkeypatch.setattr(
        "app.services.claim_draft.get_llm_config",
        lambda _db: LLMConfig(base_url="http://fake", model="fake-model"),
    )
    monkeypatch.setattr("app.services.claim_draft.create_provider", lambda _config: provider)


# ===== 路由与基本 CRUD =====


def test_fixed_paths_are_not_swallowed_by_the_id_route(client):
    """``/baseline`` 与 ``/draft`` 必须走各自的处理函数，而不是被当成 claim_id。"""
    baseline = client.get("/api/claims/baseline")
    assert baseline.status_code == 200
    assert baseline.json()["confirmed_count"] == 0

    draft = client.post("/api/claims/draft", json={"raw_text": "做了一件事，具体做法已经记不清。"})
    assert draft.status_code == 200


def test_create_read_update_delete(client):
    created = client.post("/api/claims", json=VALID)
    assert created.status_code == 201
    body = created.json()
    claim_id = body["id"]
    assert body["title"] == "检索接口"
    assert body["warnings"]  # 待确认但没写占位符，应当有建议

    fetched = client.get(f"/api/claims/{claim_id}")
    assert fetched.status_code == 200
    assert fetched.json()["subject"] == "校园知识检索平台"

    updated = client.put(
        f"/api/claims/{claim_id}",
        json={
            **VALID,
            "verification_status": "已确认",
            "candidate_wording": "实现检索接口并联调上线",
            "boundary": "接口由本人实现，检索算法由另一位同学负责。",
            "sources": [
                {"type": "repository", "location": "https://example.com/repo", "public": True}
            ],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["verification_status"] == "已确认"
    assert updated.json()["warnings"] == []

    assert client.delete(f"/api/claims/{claim_id}").status_code == 204
    assert client.get(f"/api/claims/{claim_id}").status_code == 404
    assert client.delete(f"/api/claims/{claim_id}").status_code == 404


def test_list_endpoint_returns_items_and_summary(client):
    client.post("/api/claims", json=VALID)
    client.post("/api/claims", json={**VALID, "title": "数据清洗", "category": "其他"})

    body = client.get("/api/claims").json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert body["category_counts"]["其他"] == 1

    filtered = client.get("/api/claims", params={"category": "其他"}).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["title"] == "数据清洗"


def test_invalid_enum_filters_are_rejected(client):
    assert client.get("/api/claims", params={"category": "不存在"}).status_code == 422
    assert client.get("/api/claims", params={"status": "不存在"}).status_code == 422


def test_self_contradictory_payload_is_rejected(client):
    """已确认 + 占位符是自相矛盾，接口层必须返回 422 而不是静默存下。"""
    response = client.post(
        "/api/claims",
        json={
            **VALID,
            "verification_status": "已确认",
            "candidate_wording": "优化了检索速度【待补：具体倍数】",
        },
    )
    assert response.status_code == 422


def test_baseline_endpoint_reflects_the_ledger(client):
    client.post(
        "/api/claims",
        json={
            **VALID,
            "verification_status": "已确认",
            "candidate_wording": "实现检索接口并联调上线",
            "boundary": "接口由本人实现。",
            "sources": [{"type": "link", "location": "https://example.com", "public": True}],
        },
    )
    client.post(
        "/api/claims",
        json={
            **VALID,
            "title": "还没核实的说法",
            "verification_status": "待确认",
            "candidate_wording": "【待补：参与范围】参与导师项目",
        },
    )
    body = client.get("/api/claims/baseline").json()
    assert body["confirmed_count"] == 1
    assert "检索接口" in body["baseline_text"]
    assert any("参与导师项目" in item for item in body["blocked_wording"])


# ===== 草拟接口 =====


def test_draft_falls_back_locally_without_a_model(client):
    """没配置大模型时给可用的本地降级，而不是报错——用户至少能拿到分段结果。"""
    text = "搭建了校园知识检索平台，负责接口设计与联调。\n\n整理了实验室的文档，做了数据清洗。"
    body = client.post("/api/claims/draft", json={"raw_text": text, "category": "项目经历"}).json()
    assert len(body["drafts"]) == 2
    assert body["drafts"][0]["source_fact"].startswith("搭建了校园知识检索平台")
    assert body["drafts"][0]["verification_status"] == "待确认"
    assert any("未配置大模型" in item for item in body["notes"])


def test_draft_uses_the_model_and_forces_pending_status(client, monkeypatch):
    provider = ScriptedProvider(
        json.dumps(
            {
                "claims": [
                    {
                        "title": "检索接口",
                        "subject": "检索平台",
                        "source_fact": "负责检索接口的实现与联调。",
                        "candidate_wording": "实现检索接口并联调上线",
                        "responsibility_level": "负责模块",
                        "boundary": "接口由本人实现。",
                        "risk_notes": ["未说明检索效果指标"],
                        "interview_details": {"decisions": ["先做关键词再做语义"]},
                    },
                    # 模型给了一个不存在的承担程度：必须退回最保守的取值而不是原样落库。
                    {"title": "越权的一条", "source_fact": "写了一段代码。", "responsibility_level": "首席架构师"},
                ],
                "notes": ["原文没有量化指标"],
            },
            ensure_ascii=False,
        )
    )
    _configure_llm(monkeypatch, provider)

    body = client.post(
        "/api/claims/draft",
        json={"raw_text": "我负责检索接口。", "category": "项目经历", "subject": "检索平台"},
    ).json()

    assert len(body["drafts"]) == 2
    first = body["drafts"][0]
    assert first["responsibility_level"] == "负责模块"
    assert first["verification_status"] == "待确认"
    assert first["category"] == "项目经历"
    assert body["drafts"][1]["responsibility_level"] == "参与"
    assert body["notes"] == ["原文没有量化指标"]

    # 资料必须被当成不可信数据、放在明确的边界里。
    user_message = provider.messages[-1]["content"]
    assert "<RAW_MATERIAL>" in user_message
    assert "不可信数据" in user_message


def test_draft_reports_model_status_when_the_provider_fails(client, monkeypatch):
    _configure_llm(monkeypatch, FailingProvider())
    response = client.post("/api/claims/draft", json={"raw_text": "做了一件事。"})
    # 模型故障要变成可理解的上游错误，而不是 500。
    assert response.status_code == 502
    assert "模型" in response.json()["detail"]


def test_draft_requires_something_to_work_with(client):
    assert client.post("/api/claims/draft", json={"raw_text": ""}).status_code == 422
