"""API 冒烟测试：核心链路（资料、岗位、搜索、统计、设置）走通。"""
import json

import pytest

from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider
from app.services.settings_service import API_KEY_MASK, get_llm_config


SAMPLE_JOB_TEXT = """AI应用客户端开发工程师 - 剪映CapCut
深圳、广州
正式
研发 - 客户端
2027届校园招聘
职位 ID：A134186
职位描述
团队介绍：剪映研发团队，主要支持剪映、CapCut、醒图、Hypic、即梦、Dreamina、小云雀、Pippit等多款国内外产品的研发工作，业务覆盖多元化影像创作场景，并孵化了多款AIGC明星产品，相关产品多次登顶国内外App Store 免费应用榜第一，并继续保持高速增长。加入我们，一起打造全球最受用户欢迎的影像创作和GenAI产品。

1、参与产品迭代改进，协作多部门或团队进行功能开发和联调；
2、参与剪辑场景，基础剪辑能力和智能化剪辑能力开发；
3、参与提效工具开发，结合AI工具应用，开发内部提效工具。
职位要求
1、2027届获得本科及以上学历，计算机、数学等相关专业优先；
2、有良好的编程习惯，代码结构清晰，命名规范；
3、熟练掌握数据结构与算法、计算机网络、操作系统、编译原理等课程，熟练掌握C++/C/Java/JavaScript等一种或多种语言；
4、充满技术热情，有较强的自驱力和学习能力；
5、业余爱好视频拍摄、视频编辑，有移动端、桌面端视频编辑软件使用经验者优先。"""


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_profile_roundtrip(client):
    payload = {
        "name": "张三",
        "email": "zhangsan@example.com",
        "job_intent": "后端开发工程师",
        "educations": [{"school": "天津工业大学", "major": "软件工程", "degree": "本科"}],
        "experiences": [{"company": "某科技公司", "role": "实习生", "description": "开发\n测试"}],
        "campus_experiences": [
            {
                "organization": "学生会",
                "role": "宣传部部长",
                "start_date": "2023.09",
                "end_date": "2024.06",
                "description": "策划校园活动\n管理宣传渠道",
            }
        ],
        "projects": [],
        "skills": [{"name": "Python", "level": "熟练"}],
        "awards": [],
        "section_order": ["projects", "basic_info"],
    }
    response = client.put("/api/profile", json=payload)
    assert response.status_code == 200
    saved = response.json()
    assert saved["name"] == "张三" and len(saved["educations"]) == 1
    assert saved["campus_experiences"][0]["organization"] == "学生会"
    assert saved["section_order"][:2] == ["projects", "basic_info"]

    response = client.get("/api/profile")
    assert response.json()["educations"][0]["school"] == "天津工业大学"
    assert response.json()["campus_experiences"][0]["role"] == "宣传部部长"

    # 再次 PUT 是整体替换：清空教育经历
    payload["educations"] = []
    payload["campus_experiences"] = []
    response = client.put("/api/profile", json=payload)
    assert response.json()["educations"] == []
    assert response.json()["campus_experiences"] == []


def test_profile_parse_text_returns_draft_without_saving(client):
    response = client.post(
        "/api/profile/parse-text",
        json={
            "text": "姓名：李四\n\n项目经历\n简历工具｜核心开发｜2025.01-至今\n技术栈：Python、FastAPI\n项目描述：搭建平台",
        },
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["name"] == "李四"
    assert draft["projects"][0]["name"] == "简历工具"
    assert draft["projects"][0]["tech_stack"] == "Python、FastAPI"
    assert client.get("/api/profile").json()["name"] == ""


def test_job_crud_and_keywords(client):
    payload = {
        "title": "后端开发工程师",
        "company": "示例公司",
        "location": "北京",
        "description": "熟练掌握 Python、MySQL，本科及以上学历，3年以上经验",
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 201
    job = response.json()
    keyword_names = {tag["name"] for tag in job["keywords"]}
    assert {"Python", "MySQL"} <= keyword_names

    response = client.get(f"/api/jobs/{job['id']}")
    assert response.status_code == 200

    response = client.put(f"/api/jobs/{job['id']}", json={"status": "已投递"})
    assert response.json()["status"] == "已投递"

    response = client.delete(f"/api/jobs/{job['id']}")
    assert response.status_code == 204
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404


def test_parse_job_text_does_not_create_job(client):
    response = client.post("/api/jobs/parse-text", json={"text": SAMPLE_JOB_TEXT})

    assert response.status_code == 200
    draft = response.json()
    assert draft["title"] == "AI应用客户端开发工程师"
    assert draft["company"] == "剪映CapCut"
    assert draft["location"] == "深圳、广州"
    assert draft["job_type"] == "校招"
    assert draft["description"].splitlines()[:3] == ["正式", "研发 - 客户端", "职位 ID：A134186"]
    assert draft["requirements"].startswith("1、2027届获得本科及以上学历")
    assert client.get("/api/jobs").json()["total"] == 0


def test_create_job_from_parsed_text_extracts_skill_tags(client):
    parse_response = client.post("/api/jobs/parse-text", json={"text": SAMPLE_JOB_TEXT})
    assert parse_response.status_code == 200
    draft = parse_response.json()
    draft.pop("warnings")

    create_response = client.post("/api/jobs", json=draft)

    assert create_response.status_code == 201
    job = create_response.json()
    assert job["title"] == "AI应用客户端开发工程师"
    assert job["company"] == "剪映CapCut"
    assert job["location"] == "深圳、广州"
    assert job["job_type"] == "校招"
    assert job["description"].splitlines()[:3] == ["正式", "研发 - 客户端", "职位 ID：A134186"]
    assert job["requirements"].startswith("1、2027届获得本科及以上学历")
    assert job["source_url"] == ""
    assert job["posted_at"] == ""
    assert job["source"] == "手动添加"
    keyword_names = {tag["name"] for tag in job["keywords"]}
    assert {"C++", "Java", "JavaScript"} <= keyword_names
    assert client.get("/api/jobs").json()["total"] == 1


@pytest.mark.parametrize(
    "source_url",
    [
        "javascript:alert(1)",
        "file:///C:/secret.txt",
        "/relative/apply",
        "not-a-url",
    ],
)
def test_job_rejects_unsafe_source_urls(client, source_url):
    response = client.post(
        "/api/jobs",
        json={"title": "安全测试岗位", "source_url": source_url},
    )

    assert response.status_code == 422


def test_job_accepts_and_normalizes_https_source_url(client):
    response = client.post(
        "/api/jobs",
        json={
            "title": "后端开发工程师",
            "source_url": "  https://careers.example.com/jobs/123?from=campus  ",
        },
    )

    assert response.status_code == 201
    assert response.json()["source_url"] == "https://careers.example.com/jobs/123?from=campus"


def test_representative_request_size_limits(client):
    assert client.post("/api/jobs", json={"title": "岗" * 129}).status_code == 422
    assert client.post("/api/jobs/parse-text", json={"text": "A" * 50_001}).status_code == 422
    assert client.post("/api/jobs/batch-delete", json={"job_ids": list(range(1, 502))}).status_code == 422
    assert (
        client.put(
            "/api/profile",
            json={"skills": [{"name": f"skill-{index}"} for index in range(201)]},
        ).status_code
        == 422
    )


@pytest.mark.parametrize("text", ["", "   \r\n\t"])
def test_parse_job_text_rejects_blank_input(client, text):
    response = client.post("/api/jobs/parse-text", json={"text": text})

    assert response.status_code == 422


def test_job_list_search_and_pagination(client):
    client.post("/api/jobs", json={"title": "后端开发工程师", "company": "A公司", "description": "Python"})
    client.post("/api/jobs", json={"title": "前端开发工程师", "company": "B公司", "description": "React"})
    response = client.get("/api/jobs", params={"keyword": "后端"})
    body = response.json()
    assert body["total"] == 1 and body["items"][0]["company"] == "A公司"
    response = client.get("/api/jobs", params={"page": 2, "page_size": 1})
    assert response.json()["total"] == 2 and len(response.json()["items"]) == 1


def test_search_across_jobs(client):
    client.post("/api/jobs", json={"title": "算法工程师", "company": "C公司", "description": "机器学习"})
    response = client.get("/api/search", params={"q": "机器学习"})
    body = response.json()
    assert len(body["jobs"]) == 1 and body["jobs"][0]["company"] == "C公司"


def test_stats(client):
    client.post("/api/jobs", json={"title": "算法工程师", "company": "C公司"})
    response = client.get("/api/stats")
    body = response.json()
    assert body["job_count"] == 1 and body["open_job_count"] == 1
    assert body["resume_count"] == 0


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
