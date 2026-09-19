"""知识库（E4）接口测试：CRUD、软删过滤、检索筛选与校验。

重点钉住两件事：删除走软删（列表消失、单条 404、回收站可见），以及列表检索只在
「未删除」的条目上按标题/正文命中关键词、按分类精确筛选。
"""

VALID = {
    "title": "STAR 法则",
    "category": "简历技巧",
    "tags": ["简历", "STAR", "量化"],
    "content": "# STAR 法则\n\n用 **情境-任务-行动-结果** 组织经历，尽量给出**量化结果**。",
    "source": "手动录入",
}


def test_create_read_update_delete_round_trip(client):
    created = client.post("/api/knowledge", json=VALID)
    assert created.status_code == 201
    body = created.json()
    entry_id = body["id"]
    assert body["title"] == "STAR 法则"
    assert body["category"] == "简历技巧"
    assert body["tags"] == ["简历", "STAR", "量化"]
    assert body["content"].startswith("# STAR 法则")

    fetched = client.get(f"/api/knowledge/{entry_id}")
    assert fetched.status_code == 200
    assert fetched.json()["source"] == "手动录入"

    updated = client.put(
        f"/api/knowledge/{entry_id}",
        json={**VALID, "title": "STAR 法则（修订）", "category": "求职策略", "tags": ["STAR"]},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "STAR 法则（修订）"
    assert updated.json()["category"] == "求职策略"
    assert updated.json()["tags"] == ["STAR"]

    assert client.delete(f"/api/knowledge/{entry_id}").status_code == 204
    assert client.get(f"/api/knowledge/{entry_id}").status_code == 404
    assert client.delete(f"/api/knowledge/{entry_id}").status_code == 404


def test_delete_is_soft_and_list_filters_it_out(client):
    first = client.post("/api/knowledge", json=VALID).json()
    second = client.post(
        "/api/knowledge", json={**VALID, "title": "自我介绍模板", "category": "面试问答"}
    ).json()

    listing = client.get("/api/knowledge").json()
    assert sorted(item["id"] for item in listing) == sorted([first["id"], second["id"]])

    assert client.delete(f"/api/knowledge/{first['id']}").status_code == 204

    # 列表里消失、单条 404，但回收站里可见（type=knowledge_entry）。
    listing = client.get("/api/knowledge").json()
    assert [item["id"] for item in listing] == [second["id"]]
    assert client.get(f"/api/knowledge/{first['id']}").status_code == 404

    trash = client.get("/api/trash", params={"type": "knowledge_entry"}).json()
    assert trash["counts"]["knowledge_entry"] == 1
    assert any(item["id"] == first["id"] for item in trash["items"])

    # 恢复后重新出现在列表里。
    assert client.post(f"/api/trash/knowledge_entry/{first['id']}/restore").status_code == 204
    listing = client.get("/api/knowledge").json()
    assert sorted(item["id"] for item in listing) == sorted([first["id"], second["id"]])


def test_list_filters_by_q_and_category(client):
    client.post("/api/knowledge", json=VALID)
    client.post(
        "/api/knowledge",
        json={
            **VALID,
            "title": "自我介绍模板",
            "category": "面试问答",
            "content": "面试开场先讲一段 1 分钟自我介绍。",
        },
    )
    client.post(
        "/api/knowledge",
        json={**VALID, "title": "谈薪话术", "category": "求职策略", "content": "先问区间再报期望。"},
    )

    # 关键词只在标题/正文命中，不会命中无关条目。
    hits = client.get("/api/knowledge", params={"q": "自我介绍"}).json()
    assert [item["title"] for item in hits] == ["自我介绍模板"]

    # 关键词可以命中正文。
    hits = client.get("/api/knowledge", params={"q": "量化"}).json()
    assert {item["title"] for item in hits} == {"STAR 法则"}

    # 分类精确筛选。
    hits = client.get("/api/knowledge", params={"category": "面试问答"}).json()
    assert [item["title"] for item in hits] == ["自我介绍模板"]


def test_list_is_ordered_by_updated_at_desc(client):
    first = client.post("/api/knowledge", json=VALID).json()
    second = client.post("/api/knowledge", json={**VALID, "title": "自我介绍模板"}).json()

    listing = client.get("/api/knowledge").json()
    # 同一次提交里时间可能相同，但 id 降序兜底，最新创建的在前。
    assert listing[0]["id"] == second["id"]
    assert listing[1]["id"] == first["id"]


def test_empty_title_is_rejected(client):
    assert client.post("/api/knowledge", json={**VALID, "title": ""}).status_code == 422
    assert client.post("/api/knowledge", json={**VALID, "title": "   "}).status_code == 422


def test_tags_are_cleaned_and_deduplicated(client):
    created = client.post(
        "/api/knowledge",
        json={**VALID, "tags": ["简历", "", "  ", "简历", "STAR"]},
    )
    assert created.status_code == 201
    assert created.json()["tags"] == ["简历", "STAR"]


def test_categories_endpoint_prepends_builtin_categories(client):
    client.post("/api/knowledge", json={**VALID, "category": "自定义分类A"})
    categories = client.get("/api/knowledge/categories").json()
    assert "自定义分类A" in categories
    assert categories[0] == "面经"  # 内置分类在前
