"""设置 API 与 API Key 脱敏边界测试。"""

from app.schemas.setting import UNLIMITED_MAX_TOKENS, LLMConfig
from app.services.settings_service import API_KEY_MASK, get_llm_config

def test_settings_roundtrip(client, db_session):
    config = LLMConfig(base_url="https://api.example.com/v1", api_key="sk-test", model="test-model")
    response = client.put("/api/settings/llm", json=config.model_dump())
    assert response.status_code == 200
    assert response.json()["api_key"] == API_KEY_MASK
    assert "sk-test" not in response.text
    response = client.get("/api/settings/llm")
    assert response.json()["model"] == "test-model"
    assert response.json()["api_key"] == API_KEY_MASK
    assert "sk-test" not in response.text

    # 前端原样回传占位符时必须保留原密钥，不能把星号写入数据库。
    masked_config = response.json()
    masked_config["model"] = "updated-model"
    response = client.put("/api/settings/llm", json=masked_config)
    assert response.status_code == 200
    assert response.json()["api_key"] == API_KEY_MASK
    db_session.expire_all()
    assert get_llm_config(db_session).api_key == "sk-test"

    # 测试连接：未填配置或配置无效时应友好返回而非抛 500
    response = client.post("/api/settings/llm/test", json=LLMConfig().model_dump())
    assert response.status_code == 200 and response.json()["ok"] is False


def test_settings_accepts_unlimited_output_and_keeps_the_minimum_bound(client):
    config = LLMConfig(base_url="https://api.example.com/v1", model="test-model")

    unlimited = client.put(
        "/api/settings/llm", json={**config.model_dump(), "max_tokens": UNLIMITED_MAX_TOKENS}
    )
    assert unlimited.status_code == 200
    assert unlimited.json()["max_tokens"] == UNLIMITED_MAX_TOKENS

    # 放行 0 之后仍须拒绝 1..255：它们既不是“不限制”，也低于可用的下界。
    for rejected in (1, 128, 255):
        response = client.put(
            "/api/settings/llm", json={**config.model_dump(), "max_tokens": rejected}
        )
        assert response.status_code == 422, rejected


def test_settings_api_key_reveal_is_explicit_and_not_cached(client):
    config = LLMConfig(
        provider="deepseek",
        base_url="https://api.deepseek.com",
        api_key="sk-reveal-test",
        model="deepseek-chat",
    )
    saved = client.put("/api/settings/llm", json=config.model_dump())

    assert saved.status_code == 200
    assert saved.json()["api_key"] == API_KEY_MASK
    assert "sk-reveal-test" not in client.get("/api/settings/llm").text
    assert client.get("/api/settings/llm/api-key/reveal").status_code == 405

    revealed = client.post("/api/settings/llm/api-key/reveal")

    assert revealed.status_code == 200
    assert revealed.json() == {"api_key": "sk-reveal-test"}
    assert revealed.headers["cache-control"] == "no-store, private"
    assert revealed.headers["pragma"] == "no-cache"


def test_settings_api_key_reveal_handles_config_without_a_key(client):
    config = LLMConfig(
        provider="ollama",
        base_url="http://localhost:11434/v1",
        api_key="",
        model="qwen2.5:7b",
    )
    client.put("/api/settings/llm", json=config.model_dump())

    response = client.post("/api/settings/llm/api-key/reveal")

    assert response.status_code == 200
    assert response.json() == {"api_key": ""}
    assert response.headers["cache-control"] == "no-store, private"


def test_settings_api_key_reveal_rejects_non_loopback_clients(client, monkeypatch):
    monkeypatch.setattr("app.api.settings._is_loopback_request", lambda _request: False)

    response = client.post("/api/settings/llm/api-key/reveal")

    assert response.status_code == 403
    assert "只能在运行后端的本机查看" in response.json()["detail"]


def test_settings_config_records_roundtrip_and_upsert(client):
    config = LLMConfig(
        provider="deepseek",
        base_url="https://api.deepseek.com",
        api_key="sk-record",
        model="deepseek-chat",
    )
    payload = {"name": "校招 DeepSeek", **config.model_dump()}

    created = client.post("/api/settings/llm/records", json=payload)
    assert created.status_code == 200
    record = created.json()
    assert record["name"] == "校招 DeepSeek"
    assert record["model"] == "deepseek-chat"
    assert record["api_key"] == f"{API_KEY_MASK}:record:{record['id']}"
    assert "sk-record" not in created.text

    listed = client.get("/api/settings/llm/records")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [record["id"]]
    assert "sk-record" not in listed.text

    updated = client.post(
        "/api/settings/llm/records",
        json={**payload, "model": "deepseek-reasoner"},
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == record["id"]
    assert updated.json()["model"] == "deepseek-reasoner"
    assert len(client.get("/api/settings/llm/records").json()) == 1

    deleted = client.delete(f"/api/settings/llm/records/{record['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/settings/llm/records").json() == []
    assert client.delete(f"/api/settings/llm/records/{record['id']}").status_code == 404


def test_settings_record_reference_switches_the_correct_secret(client, db_session):
    """两个记录仅密钥不同时，也必须按记录 ID 选择正确密钥。"""
    common = LLMConfig(
        provider="custom",
        base_url="https://api.example.com/v1",
        model="same-model",
    ).model_dump()
    first = client.post(
        "/api/settings/llm/records",
        json={"name": "账号 A", **common, "api_key": "secret-a"},
    ).json()
    second_response = client.post(
        "/api/settings/llm/records",
        json={"name": "账号 B", **common, "api_key": "secret-b"},
    )
    second = second_response.json()

    assert "secret-a" not in str(first)
    assert "secret-b" not in second_response.text
    apply_payload = {field: second[field] for field in LLMConfig.model_fields}
    applied = client.put("/api/settings/llm", json=apply_payload)
    assert applied.status_code == 200
    assert applied.json()["api_key"] == second["api_key"]
    assert "secret-b" not in applied.text

    db_session.expire_all()
    assert get_llm_config(db_session).api_key == "secret-b"


def test_settings_test_connection_resolves_masked_secret(client, monkeypatch):
    config = LLMConfig(
        base_url="https://api.example.com/v1",
        api_key="secret-for-test",
        model="test-model",
    )
    saved = client.put("/api/settings/llm", json=config.model_dump()).json()
    captured = {}

    class FakeProvider:
        async def chat(self, _messages):
            return "正常"

    def fake_create_provider(resolved):
        captured["api_key"] = resolved.api_key
        return FakeProvider()

    monkeypatch.setattr("app.api.settings.create_provider", fake_create_provider)
    response = client.post("/api/settings/llm/test", json=saved)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured["api_key"] == "secret-for-test"
    assert "secret-for-test" not in response.text


def test_masked_api_key_cannot_be_reused_for_another_base_url(client, db_session):
    config = LLMConfig(
        base_url="https://api.example.com/v1",
        api_key="secret-for-test",
        model="test-model",
    )
    masked = client.put("/api/settings/llm", json=config.model_dump()).json()
    masked["base_url"] = "https://attacker.example/v1"

    save_response = client.put("/api/settings/llm", json=masked)
    test_response = client.post("/api/settings/llm/test", json=masked)

    assert save_response.status_code == 400
    assert "重新填写 API Key" in save_response.json()["detail"]
    assert test_response.status_code == 200
    assert test_response.json()["ok"] is False
    assert "重新填写 API Key" in test_response.json()["message"]
    assert get_llm_config(db_session).base_url == config.base_url


def test_masked_api_key_url_binding_normalizes_host_but_preserves_path_case(client):
    config = LLMConfig(
        base_url="https://api.example.com/v1",
        api_key="secret-for-test",
        model="test-model",
    )
    masked = client.put("/api/settings/llm", json=config.model_dump()).json()

    equivalent = {**masked, "base_url": "HTTPS://API.EXAMPLE.COM/v1/"}
    assert client.put("/api/settings/llm", json=equivalent).status_code == 200

    changed_path = {**masked, "base_url": "https://api.example.com/V1"}
    response = client.put("/api/settings/llm", json=changed_path)
    assert response.status_code == 400
    assert "重新填写 API Key" in response.json()["detail"]


def test_create_provider_forwards_request_overrides():
    """工厂的 request_overrides 参数必须真的生效。

    它曾经只是"文档里有"：构造函数不收这个关键字，照签名调用会直接 TypeError，
    调用方只能改成构造完再赋属性——看起来能用，实际绕过了工厂的契约。
    """
    from app.schemas.setting import LLMConfig
    from app.services.llm import create_provider

    config = LLMConfig(base_url="https://api.example.com/v1", model="m")
    provider = create_provider(config, request_overrides={"reasoning_effort": "high"})

    assert provider.request_overrides == {"reasoning_effort": "high"}

    # 白名单之外的键不会被采纳，但也不该炸。
    ignored = create_provider(config, request_overrides={"messages": "覆盖对话"})
    payload: dict = {}
    ignored._apply_request_overrides(payload)
    assert "messages" not in payload
