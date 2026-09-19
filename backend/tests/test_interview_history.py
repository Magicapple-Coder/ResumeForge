"""D5 题库历史 / 面试复盘历史：保存、列表、单条、软删除进回收站。"""


def _bank_payload(**overrides):
    payload = {
        "job_title": "后端开发工程师",
        "company": "示例公司",
        "resume_title": "后端简历",
        "groups": [
            {
                "type": "基础题",
                "questions": [
                    {"question": "请自我介绍", "purpose": "考察表达", "answer_hint": "按 STAR"}
                ],
            }
        ],
        "model": "test-model",
    }
    payload.update(overrides)
    return payload


def _review_payload(**overrides):
    payload = {
        "job_title": "后端开发工程师",
        "company": "示例公司",
        "resume_title": "后端简历",
        "questions": ["这个项目难点怎么解决？"],
        "analysis": {
            "question": "这个项目难点怎么解决？",
            "framework": "先讲背景再讲取舍",
            "key_points": ["说明约束"],
            "follow_up": ["指标怎么算"],
            "pitfalls": ["只讲过程"],
        },
        "suggestions": [
            {"priority": "high", "section": "项目经历", "issue": "不够量化", "suggestion": "补充指标"}
        ],
        "model": "test-model",
    }
    payload.update(overrides)
    return payload


# ===== 题库历史 =====


def test_question_bank_history_round_trip(client):
    created = client.post("/api/interview/question-banks", json=_bank_payload())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["id"]
    assert body["job_title"] == "后端开发工程师"
    assert body["groups"][0]["type"] == "基础题"
    assert body["groups"][0]["questions"][0]["question"] == "请自我介绍"

    listing = client.get("/api/interview/question-banks").json()
    assert [item["id"] for item in listing] == [body["id"]]

    assert client.get(f"/api/interview/question-banks/{body['id']}").status_code == 200


def test_question_bank_delete_soft_deletes_into_trash(client):
    created = client.post("/api/interview/question-banks", json=_bank_payload()).json()

    assert client.delete(f"/api/interview/question-banks/{created['id']}").status_code == 204
    assert client.get("/api/interview/question-banks").json() == []
    assert client.get(f"/api/interview/question-banks/{created['id']}").status_code == 404

    summary = client.get("/api/trash").json()
    mine = [item for item in summary["items"] if item["type"] == "question_bank_record"]
    assert [item["id"] for item in mine] == [created["id"]]
    assert mine[0]["type_label"] == "题库历史"
    assert mine[0]["title"] == "后端简历"


def test_question_bank_missing_returns_404(client):
    assert client.get("/api/interview/question-banks/999").status_code == 404
    assert client.delete("/api/interview/question-banks/999").status_code == 404


def test_question_bank_rejects_invalid_groups(client):
    assert (
        client.post("/api/interview/question-banks", json=_bank_payload(groups=[{"type": 1}]))
        .status_code
        == 422
    )


# ===== 复盘历史 =====


def test_review_history_round_trip(client):
    created = client.post("/api/interview/reviews", json=_review_payload())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["id"]
    assert body["questions"] == ["这个项目难点怎么解决？"]
    assert body["analysis"]["framework"] == "先讲背景再讲取舍"
    assert body["suggestions"][0]["suggestion"] == "补充指标"

    listing = client.get("/api/interview/reviews").json()
    assert [item["id"] for item in listing] == [body["id"]]

    assert client.get(f"/api/interview/reviews/{body['id']}").status_code == 200


def test_review_delete_soft_deletes_into_trash(client):
    created = client.post("/api/interview/reviews", json=_review_payload()).json()

    assert client.delete(f"/api/interview/reviews/{created['id']}").status_code == 204
    assert client.get("/api/interview/reviews").json() == []
    assert client.get(f"/api/interview/reviews/{created['id']}").status_code == 404

    summary = client.get("/api/trash").json()
    mine = [item for item in summary["items"] if item["type"] == "interview_review_record"]
    assert [item["id"] for item in mine] == [created["id"]]
    assert mine[0]["type_label"] == "复盘历史"


def test_review_missing_returns_404(client):
    assert client.get("/api/interview/reviews/999").status_code == 404
    assert client.delete("/api/interview/reviews/999").status_code == 404


def test_review_soft_delete_keeps_it_out_of_live_list(client):
    created = client.post("/api/interview/reviews", json=_review_payload()).json()
    client.delete(f"/api/interview/reviews/{created['id']}")

    # 已软删的记录不能再被"再删一次"。
    assert client.delete(f"/api/interview/reviews/{created['id']}").status_code == 404
    # 恢复后回到列表。
    assert (
        client.post(f"/api/trash/interview_review_record/{created['id']}/restore").status_code
        == 204
    )
    assert [item["id"] for item in client.get("/api/interview/reviews").json()] == [created["id"]]
