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


def test_job_list_source_kind_filter(client):
    """来源筛选只按「自动采集 / 手动添加」二分，而不是去猜 source 站点名。

    采集写入的 recognition_source 是固定值「岗位采集」，手动录入则是一串五花八门的
    值（含空串），所以用「等于岗位采集」判定采集、其余都算手动，才是稳定口径。
    """
    client.post(
        "/api/jobs",
        json={"title": "采集岗", "company": "X公司", "recognition_source": "岗位采集"},
    )
    client.post("/api/jobs", json={"title": "手动岗", "company": "Y公司"})

    collected = client.get("/api/jobs", params={"source_kind": "collected"}).json()
    assert collected["total"] == 1 and collected["items"][0]["title"] == "采集岗"

    manual = client.get("/api/jobs", params={"source_kind": "manual"}).json()
    assert manual["total"] == 1 and manual["items"][0]["title"] == "手动岗"

    # 不传该参数时仍是全量。
    assert client.get("/api/jobs").json()["total"] == 2


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


def test_stats_reports_the_todos_the_home_page_lists(client):
    """首页「接下来做什么」只列**待办**，所以这几个数必须真的是待办的数量。

    这里钉住的是"数据库里有什么，首页就报什么"——不是"报了个数"。这几项此前首页拿不到，
    于是概览页只能显示四个计数卡，看不出"我现在该做什么"。
    """
    client.post("/api/jobs", json={"title": "算法工程师", "company": "C公司", "favorite": True})
    client.post("/api/jobs", json={"title": "后端开发", "company": "D公司"})

    body = client.get("/api/stats").json()

    # 收藏是"你自己标的"，所以它是首页能报的一个数；没收藏的那个不该被算进去。
    assert body["favorite_job_count"] == 1
    # 一个空项目里，这几项都是 0 而不是缺字段——前端按数字直接渲染。
    assert body["pending_claim_count"] == 0
    assert body["pending_claims"] == []
    assert body["apply_queue_count"] == 0
    assert body["stalled_application_count"] == 0
    assert body["latest_applications"] == []


def test_stats_counts_a_pending_claim_and_names_it(client):
    """首页会**点名**待确认的台账条目，所以除了数量还要能拿到标题。"""
    created = client.post(
        "/api/claims",
        json={
            "title": "检索平台召回率提升",
            "subject": "检索平台",
            # 台账要求"原始事实"与"简历表述"至少有一条，否则这条主张无从核对。
            "source_fact": "把关键词召回的召回率从 71% 提到 89%",
            "verification_status": "待确认",
        },
    )
    assert created.status_code == 201, created.text

    body = client.get("/api/stats").json()
    assert body["pending_claim_count"] == 1
    assert [item["title"] for item in body["pending_claims"]] == ["检索平台召回率提升"]


def test_a_confirmed_claim_is_no_longer_a_todo(client):
    """核实完就不该再出现在"接下来做什么"里——否则待办永远清不掉，用户会开始忽略它。"""
    payload = {
        "title": "换一种说法",
        "subject": "检索平台",
        "source_fact": "用混合召回替换了纯关键词召回",
        "verification_status": "待确认",
    }
    created = client.post("/api/claims", json=payload)
    assert created.status_code == 201, created.text
    claim_id = created.json()["id"]
    # 这个接口是 PUT（**整体替换**语义）：只发 verification_status 会把 source_fact 清空，
    # 而"至少要有原始事实或简历表述"是硬校验，于是整条更新被拒。前端编辑弹窗发的也是整份。
    updated = client.put(
        f"/api/claims/{claim_id}", json={**payload, "verification_status": "已确认"}
    )
    assert updated.status_code == 200, updated.text

    body = client.get("/api/stats").json()
    assert body["pending_claim_count"] == 0
    assert body["pending_claims"] == []
