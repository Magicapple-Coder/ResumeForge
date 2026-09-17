"""求职进度的 HTTP 面：路由顺序、两步导入的一致性、导出与错误码。

最要紧的两条：
- ``/parse`` **绝不能写库**（它是预览）；
- ``/parse`` 说会怎样、``/apply`` 就得那样——两处各判一次是这类功能最容易出的错。
"""
import json

from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider, LLMError

VALID = {
    "company": "示例科技",
    "title": "后端开发实习生",
    "status": "applied",
    "applied_at": "2026-09-18",
}


class ScriptedProvider(BaseLLMProvider):
    def __init__(self, response: str):
        super().__init__(LLMConfig(base_url="http://fake", model="fake-model"))
        self.response = response

    async def chat(self, messages):
        return self.response

    async def stream_chat(self, messages):  # pragma: no cover - 未用到
        yield ""


class FailingProvider(BaseLLMProvider):
    def __init__(self):
        super().__init__(LLMConfig(base_url="http://fake", model="fake-model"))

    async def chat(self, messages):
        raise LLMError("模型不可用")

    async def stream_chat(self, messages):  # pragma: no cover - 未用到
        yield ""


def _configure_llm(monkeypatch, provider):
    monkeypatch.setattr(
        "app.api.tracker.get_llm_config",
        lambda _db: LLMConfig(base_url="http://fake", model="fake-model"),
    )
    monkeypatch.setattr("app.api.tracker.create_provider", lambda _config: provider)


# ===== 路由与 CRUD =====


def test_fixed_paths_are_not_swallowed_by_the_id_route(client):
    """``/parse`` / ``/apply`` / ``/export`` 必须走各自的处理函数，而不是被当成 track_id。"""
    assert client.get("/api/tracker/export").status_code == 200
    assert client.post("/api/tracker/parse", json={"text": "没有公司名的一段话"}).status_code == 200
    assert client.post("/api/tracker/apply", json={"items": []}).status_code == 422


def test_create_read_update_delete(client):
    created = client.post("/api/tracker", json=VALID)
    assert created.status_code == 201
    track_id = created.json()["id"]
    assert created.json()["company"] == "示例科技"

    fetched = client.get(f"/api/tracker/{track_id}")
    assert fetched.status_code == 200

    updated = client.put(
        f"/api/tracker/{track_id}",
        json={**VALID, "status": "interview", "stage_note": "二面"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "interview"

    assert client.delete(f"/api/tracker/{track_id}").status_code == 204
    assert client.get(f"/api/tracker/{track_id}").status_code == 404
    assert client.delete(f"/api/tracker/{track_id}").status_code == 404


def test_list_returns_items_and_funnel_counts(client):
    client.post("/api/tracker", json=VALID)
    client.post("/api/tracker", json={**VALID, "title": "算法实习生", "status": "offer"})

    body = client.get("/api/tracker").json()
    assert body["total"] == 2
    assert body["offer_count"] == 1
    assert body["active_count"] == 1
    # 没有的状态也要出现在计数里，界面不用再补 0。
    assert body["status_counts"]["rejected"] == 0


def test_invalid_filters_are_rejected(client):
    assert client.get("/api/tracker", params={"status": "不存在"}).status_code == 422
    assert client.get("/api/tracker/export", params={"status": "不存在"}).status_code == 422
    assert client.get("/api/tracker/export", params={"format": "xml"}).status_code == 422


def test_a_record_needs_company_and_title(client):
    assert client.post("/api/tracker", json={"title": "后端开发"}).status_code == 422


# ===== 两步导入 =====


def test_parse_only_previews_and_never_writes(client):
    """预览写库是最隐蔽的一类 bug：用户取消之后记录却已经在了。"""
    text = "【示例科技有限公司】您投递的「后端开发实习生」岗位已进入面试环节，请于 2026-09-20 前确认。"
    response = client.post("/api/tracker/parse", json={"text": text})
    assert response.status_code == 200
    body = response.json()
    assert body["parse_engine"] == "local"
    assert len(body["items"]) == 1
    assert body["items"][0]["action"] == "created"
    assert body["items"][0]["record"]["status"] == "interview"

    assert client.get("/api/tracker").json()["total"] == 0


def test_apply_matches_what_the_preview_promised(client):
    text = "【示例科技有限公司】您投递的「后端开发实习生」岗位已进入面试环节。"
    preview = client.post("/api/tracker/parse", json={"text": text}).json()
    records = [item["record"] for item in preview["items"]]

    applied = client.post("/api/tracker/apply", json={"items": records})
    assert applied.status_code == 200
    assert applied.json()["created"] == 1

    stored = client.get("/api/tracker").json()
    assert stored["total"] == 1
    assert stored["items"][0]["status"] == "interview"
    assert stored["items"][0]["source"] == "recognized"


def test_second_import_updates_instead_of_duplicating(client):
    """同一家公司同一个岗位再导入一次，是更新而不是第二条。"""
    first = client.post(
        "/api/tracker/apply",
        json={
            "items": [
                {"company": "示例科技有限公司", "title": "后端开发实习生", "status": "applied"}
            ]
        },
    ).json()
    assert first["created"] == 1

    preview = client.post(
        "/api/tracker/parse",
        json={"text": "【示例科技有限公司】您投递的「后端开发实习生」岗位已进入面试环节。"},
    ).json()
    assert preview["items"][0]["action"] == "updated"
    assert preview["items"][0]["current_status"] == "applied"

    applied = client.post(
        "/api/tracker/apply",
        json={
            "items": [
                {"company": "示例科技有限公司", "title": "后端开发实习生", "status": "interview"}
            ]
        },
    ).json()
    assert applied["updated"] == 1
    stored = client.get("/api/tracker").json()
    assert stored["total"] == 1
    assert stored["items"][0]["status"] == "interview"


def test_a_different_company_name_is_not_merged_on_purpose(client):
    """「示例科技」和「示例科技有限公司」是两条——错误合并比留两条重复更难收拾。"""
    client.post(
        "/api/tracker/apply",
        json={"items": [{"company": "示例科技", "title": "后端开发实习生", "status": "applied"}]},
    )
    preview = client.post(
        "/api/tracker/parse",
        json={"text": "【示例科技有限公司】您投递的「后端开发实习生」岗位已进入面试环节。"},
    ).json()
    assert preview["items"][0]["action"] == "created"
    assert client.get("/api/tracker").json()["total"] == 1


def test_parse_falls_back_to_local_rules_when_the_model_fails(client, monkeypatch):
    _configure_llm(monkeypatch, FailingProvider())
    text = "【示例科技有限公司】感谢投递「后端开发实习生」，简历已收到。"
    body = client.post("/api/tracker/parse", json={"text": text}).json()
    assert body["parse_engine"] == "local"
    assert any("AI 识别失败" in note for note in body["notes"])
    # 回退后仍然不能把自动回执读成面试。
    assert body["items"][0]["record"]["status"] == "applied"


def test_parse_uses_the_model_when_configured(client, monkeypatch):
    _configure_llm(
        monkeypatch,
        ScriptedProvider(
            json.dumps(
                {
                    "records": [
                        {
                            "company": "示例科技",
                            "title": "后端开发实习生",
                            "status": "offer",
                            "evidence": "我们决定录用您",
                        }
                    ],
                    "notes": ["邮件里没有写投递日期"],
                },
                ensure_ascii=False,
            )
        ),
    )
    body = client.post("/api/tracker/parse", json={"text": "恭喜，我们决定录用您。"}).json()
    assert body["parse_engine"] == "ai"
    assert body["items"][0]["record"]["status"] == "offer"
    assert body["notes"] == ["邮件里没有写投递日期"]


def test_parse_requires_something_to_read(client):
    assert client.post("/api/tracker/parse", json={"text": ""}).status_code == 422


def test_apply_rejects_an_empty_batch(client):
    response = client.post("/api/tracker/apply", json={"items": []})
    assert response.status_code == 422
    assert "没有要保存" in response.json()["detail"]


def test_apply_rejects_an_unknown_source(client):
    response = client.post(
        "/api/tracker/apply",
        json={"items": [VALID], "source": "telepathy"},
    )
    assert response.status_code == 422


# ===== 导出 =====


def test_csv_export_downloads_with_a_filename(client):
    client.post("/api/tracker", json=VALID)
    response = client.get("/api/tracker/export", params={"format": "csv"})
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    assert "text/csv" in response.headers["content-type"]
    # BOM：没有它 Excel 打开中文列名是乱码。
    assert response.text.startswith("﻿")
    assert "示例科技" in response.text


def test_json_export_uses_readable_labels(client):
    client.post("/api/tracker", json={**VALID, "status": "offer"})
    response = client.get("/api/tracker/export", params={"format": "json"})
    body = json.loads(response.text)
    assert body["总数"] == 1
    assert body["记录"][0]["状态"] == "Offer"


def test_export_follows_the_current_filter(client):
    client.post("/api/tracker", json=VALID)
    client.post("/api/tracker", json={**VALID, "title": "算法实习生", "status": "offer"})
    response = client.get("/api/tracker/export", params={"format": "json", "status": "offer"})
    body = json.loads(response.text)
    assert body["总数"] == 1
    assert body["记录"][0]["岗位"] == "算法实习生"
