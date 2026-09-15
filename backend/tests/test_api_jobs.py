"""岗位、搜索与统计 API 冒烟测试。"""

import pytest


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
    assert draft["description"].startswith("1、参与产品迭代改进")
    assert draft["additional_info"].splitlines()[:3] == [
        "正式",
        "研发 - 客户端",
        "职位 ID：A134186",
    ]
    assert draft["requirements"].startswith("1、2027届获得本科及以上学历")
    assert client.get("/api/jobs").json()["total"] == 0


def test_job_parse_text_accepts_english_field_and_section_variants(client):
    response = client.post(
        "/api/jobs/parse-text",
        json={
            "text": (
                "Title: Backend Engineer\n"
                "Company: Example Inc\n"
                "Location: Beijing\n"
                "Job Description: Build APIs.\n"
                "Job Requirements: Python."
            )
        },
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["title"] == "Backend Engineer"
    assert draft["company"] == "Example Inc"
    assert draft["location"] == "Beijing"
    assert draft["description"] == "Build APIs."
    assert draft["requirements"] == "Python."
    assert client.get("/api/jobs").json()["total"] == 0


def test_job_parse_text_accepts_inline_metadata_and_numbered_sections(client):
    response = client.post(
        "/api/jobs/parse-text",
        json={
            "text": (
                "Enterprise: Acme Position Name: Data Analyst Work Location: Beijing "
                "Compensation: 30K\n"
                "1. Responsibilities: Build business reports and analyze metrics.\n"
                "2. Qualifications: Proficient with Postgre SQL and Python3."
            )
        },
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["company"] == "Acme"
    assert draft["title"] == "Data Analyst"
    assert draft["location"] == "Beijing"
    assert draft["salary"] == "30K"
    assert draft["description"] == "Build business reports and analyze metrics."
    assert draft["requirements"] == "Proficient with Postgre SQL and Python3."
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
    assert job["description"].startswith("1、参与产品迭代改进")
    assert job["additional_info"].splitlines()[:3] == [
        "正式",
        "研发 - 客户端",
        "职位 ID：A134186",
    ]
    assert job["requirements"].startswith("1、2027届获得本科及以上学历")
    assert job["source_url"] == ""
    assert job["posted_at"] == ""
    assert job["source"] == "手动添加"
    keyword_names = {tag["name"] for tag in job["keywords"]}
    assert {"C++", "Java", "JavaScript"} <= keyword_names
    assert client.get("/api/jobs").json()["total"] == 1


def test_create_job_normalizes_common_skill_aliases(client):
    response = client.post(
        "/api/jobs",
        json={
            "title": "AI 应用开发工程师",
            "description": "使用 Python3、Vue.js 和 K8s 部署检索增强生成应用。",
        },
    )

    assert response.status_code == 201
    keyword_names = {tag["name"] for tag in response.json()["keywords"]}
    assert {"Python", "Vue", "Kubernetes", "RAG"} <= keyword_names


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
