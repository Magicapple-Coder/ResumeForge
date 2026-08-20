"""岗位备注与批量操作测试。"""
import pytest


def _create_job(client, title: str, note: str = "") -> dict:
    response = client.post("/api/jobs", json={"title": title, "note": note})
    assert response.status_code == 201
    return response.json()


def test_job_note_roundtrip_update_and_search(client):
    job = _create_job(client, "推荐算法工程师", "已联系内推人，等待回复")

    assert job["note"] == "已联系内推人，等待回复"
    assert client.get(f"/api/jobs/{job['id']}").json()["note"] == "已联系内推人，等待回复"

    search = client.get("/api/jobs", params={"keyword": "内推人"}).json()
    assert search["total"] == 1
    assert search["items"][0]["id"] == job["id"]
    assert client.get("/api/search", params={"q": "内推人"}).json()["jobs"][0]["id"] == job["id"]

    status = client.post(
        "/api/jobs/batch-status",
        json={"job_ids": [job["id"]], "status": "已投递"},
    )
    assert status.status_code == 200

    updated = client.put(f"/api/jobs/{job['id']}", json={"note": "一面安排在周五"})
    assert updated.status_code == 200
    assert updated.json()["note"] == "一面安排在周五"
    assert updated.json()["status"] == "已投递"


def test_job_additional_info_roundtrip_update_and_search(client):
    response = client.post(
        "/api/jobs",
        json={
            "title": "高中语文教师",
            "additional_info": "提供教师公寓，面试包含试讲环节",
        },
    )
    assert response.status_code == 201
    job = response.json()
    assert job["additional_info"] == "提供教师公寓，面试包含试讲环节"

    listed = client.get("/api/jobs", params={"keyword": "教师公寓"}).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == job["id"]
    global_search = client.get("/api/search", params={"q": "试讲环节"}).json()
    assert global_search["jobs"][0]["id"] == job["id"]

    updated = client.put(
        f"/api/jobs/{job['id']}",
        json={"additional_info": "提供员工宿舍，需参加两轮面试"},
    )
    assert updated.status_code == 200
    assert updated.json()["additional_info"] == "提供员工宿舍，需参加两轮面试"


def test_job_favorite_roundtrip(client):
    job = _create_job(client, "算法工程师")

    assert job["favorite"] is False
    updated = client.put(f"/api/jobs/{job['id']}", json={"favorite": True})
    assert updated.status_code == 200
    assert updated.json()["favorite"] is True

    listed = client.get("/api/jobs").json()["items"]
    assert listed[0]["favorite"] is True


def test_job_list_filters_favorites_with_keyword_and_status(client):
    first = _create_job(client, "算法工程师")
    second = _create_job(client, "算法研究员")
    _create_job(client, "后端工程师")
    assert client.put(f"/api/jobs/{first['id']}", json={"favorite": True}).status_code == 200
    assert (
        client.put(
            f"/api/jobs/{second['id']}", json={"favorite": True, "status": "已投递"}
        ).status_code
        == 200
    )

    response = client.get(
        "/api/jobs",
        params={"favorite": "true", "keyword": "算法", "status": "开放中"},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [first["id"]]


def test_job_note_rejects_oversized_value(client):
    response = client.post("/api/jobs", json={"title": "算法工程师", "note": "x" * 2001})

    assert response.status_code == 422


def test_job_additional_info_rejects_oversized_value(client):
    response = client.post(
        "/api/jobs",
        json={"title": "算法工程师", "additional_info": "x" * 200_001},
    )

    assert response.status_code == 422


def test_job_update_rejects_null_instead_of_raising_database_error(client):
    job = _create_job(client, "算法工程师")

    response = client.put(f"/api/jobs/{job['id']}", json={"note": None})

    assert response.status_code == 422
    assert client.get(f"/api/jobs/{job['id']}").json()["note"] == ""


@pytest.mark.parametrize("method", ["post", "put"])
def test_job_write_rejects_unknown_status(client, method):
    if method == "post":
        response = client.post("/api/jobs", json={"title": "算法工程师", "status": "未知状态"})
    else:
        job = _create_job(client, "算法工程师")
        response = client.put(f"/api/jobs/{job['id']}", json={"status": "未知状态"})

    assert response.status_code == 422
    assert "无效的岗位状态" in response.text


def test_batch_status_deduplicates_ids(client):
    first = _create_job(client, "算法工程师")
    second = _create_job(client, "后端工程师")
    untouched = _create_job(client, "前端工程师")

    response = client.post(
        "/api/jobs/batch-status",
        json={"job_ids": [first["id"], first["id"], second["id"]], "status": "已投递"},
    )

    assert response.status_code == 200
    assert response.json() == {"updated": 2}
    assert client.get(f"/api/jobs/{first['id']}").json()["status"] == "已投递"
    assert client.get(f"/api/jobs/{second['id']}").json()["status"] == "已投递"
    assert client.get(f"/api/jobs/{untouched['id']}").json()["status"] == "开放中"


def test_batch_delete_deduplicates_ids(client):
    first = _create_job(client, "算法工程师")
    second = _create_job(client, "后端工程师")
    untouched = _create_job(client, "前端工程师")

    response = client.post(
        "/api/jobs/batch-delete",
        json={"job_ids": [first["id"], second["id"], first["id"]]},
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": 2}
    assert client.get(f"/api/jobs/{first['id']}").status_code == 404
    assert client.get(f"/api/jobs/{second['id']}").status_code == 404
    assert client.get(f"/api/jobs/{untouched['id']}").status_code == 200


@pytest.mark.parametrize("path", ["batch-status", "batch-delete"])
def test_batch_rejects_empty_ids(client, path):
    payload = {"job_ids": []}
    if path == "batch-status":
        payload["status"] = "已投递"

    response = client.post(f"/api/jobs/{path}", json=payload)

    assert response.status_code == 422
    assert "请至少选择一个岗位" in response.text


def test_batch_status_rejects_invalid_status_without_changes(client):
    job = _create_job(client, "算法工程师")

    response = client.post(
        "/api/jobs/batch-status",
        json={"job_ids": [job["id"]], "status": "未知状态"},
    )

    assert response.status_code == 400
    assert "无效的岗位状态" in response.json()["detail"]
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "开放中"


def test_batch_operations_are_atomic_when_an_id_is_missing(client):
    first = _create_job(client, "算法工程师")
    second = _create_job(client, "后端工程师")
    missing_id = max(first["id"], second["id"]) + 10_000

    status_response = client.post(
        "/api/jobs/batch-status",
        json={"job_ids": [first["id"], missing_id], "status": "已投递"},
    )
    assert status_response.status_code == 404
    assert str(missing_id) in status_response.json()["detail"]
    assert client.get(f"/api/jobs/{first['id']}").json()["status"] == "开放中"

    delete_response = client.post(
        "/api/jobs/batch-delete",
        json={"job_ids": [first["id"], missing_id]},
    )
    assert delete_response.status_code == 404
    assert client.get(f"/api/jobs/{first['id']}").status_code == 200
    assert client.get(f"/api/jobs/{second['id']}").status_code == 200


@pytest.mark.parametrize("job_id", [True, 2**63])
def test_batch_rejects_unsafe_job_ids(client, job_id):
    response = client.post("/api/jobs/batch-delete", json={"job_ids": [job_id]})

    assert response.status_code == 422
