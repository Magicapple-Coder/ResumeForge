"""岗位 URL、请求边界、搜索和统计 API 测试。"""

import pytest


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
    assert (
        client.post("/api/jobs/batch-delete", json={"job_ids": list(range(1, 502))}).status_code
        == 422
    )
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
    client.post(
        "/api/jobs", json={"title": "后端开发工程师", "company": "A公司", "description": "Python"}
    )
    client.post(
        "/api/jobs", json={"title": "前端开发工程师", "company": "B公司", "description": "React"}
    )
    response = client.get("/api/jobs", params={"keyword": "后端"})
    body = response.json()
    assert body["total"] == 1 and body["items"][0]["company"] == "A公司"
    response = client.get("/api/jobs", params={"page": 2, "page_size": 1})
    assert response.json()["total"] == 2 and len(response.json()["items"]) == 1


def test_search_across_jobs(client):
    client.post(
        "/api/jobs", json={"title": "算法工程师", "company": "C公司", "description": "机器学习"}
    )
    response = client.get("/api/search", params={"q": "机器学习"})
    body = response.json()
    assert len(body["jobs"]) == 1 and body["jobs"][0]["company"] == "C公司"


def test_stats(client):
    client.post("/api/jobs", json={"title": "算法工程师", "company": "C公司"})
    response = client.get("/api/stats")
    body = response.json()
    assert body["job_count"] == 1 and body["open_job_count"] == 1
    assert body["resume_count"] == 0
