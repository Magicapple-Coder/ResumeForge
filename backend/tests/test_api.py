"""API 冒烟测试：资料、岗位、搜索与统计核心链路。"""

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
    assert saved["section_order"][:2] == ["basic_info", "projects"]

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


def test_profile_parse_text_accepts_full_width_and_english_variants(client):
    response = client.post(
        "/api/profile/parse-text",
        json={
            "text": (
                "Ｆｕｌｌ Ｎａｍｅ: Alice\n"
                "Ｐｈｏｎｅ Ｎｕｍｂｅｒ: +86 138-0000-0000\n"
                "Ｅｍａｉｌ Ａｄｄｒｅｓｓ: alice@example.com\n"
                "Work History\n"
                "Company: Example Inc | Position: Backend Engineer | Period: Jan 2024 - Present\n"
                "Technical Expertise\n"
                "Python, JavaScript and SQL"
            )
        },
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["name"] == "Alice"
    assert draft["phone"] == "13800000000"
    assert draft["email"] == "alice@example.com"
    assert draft["experiences"][0]["role"] == "Backend Engineer"
    assert {skill["name"] for skill in draft["skills"]} >= {"Python", "JavaScript", "SQL"}


def test_profile_parse_text_accepts_employment_dates_alias(client):
    response = client.post(
        "/api/profile/parse-text",
        json={
            "text": (
                "Name: Li Ming\n"
                "Enterprise: Acme\n"
                "Work Position: Backend Engineer\n"
                "Employment Dates: 2024 - Present\n"
                "Work Content: Build APIs"
            )
        },
    )

    assert response.status_code == 200
    draft = response.json()
    assert len(draft["experiences"]) == 1
    experience = draft["experiences"][0]
    assert experience["company"] == "Acme"
    assert experience["role"] == "Backend Engineer"
    assert experience["start_date"] == "2024"
    assert experience["end_date"] == "Present"
    assert experience["description"] == "Build APIs"


def test_profile_parse_text_infers_unlabeled_company_role_date_block(client):
    response = client.post(
        "/api/profile/parse-text",
        json={
            "text": (
                "Name: Wang Wu\n"
                "Example Technology\n"
                "Machine Learning Intern\n"
                "2024-2025\n"
                "Trained ranking models"
            )
        },
    )

    assert response.status_code == 200
    draft = response.json()
    assert len(draft["experiences"]) == 1
    experience = draft["experiences"][0]
    assert experience["company"] == "Example Technology"
    assert experience["role"] == "Machine Learning Intern"
    assert experience["start_date"] == "2024"
    assert experience["end_date"] == "2025"
    assert experience["description"] == "Trained ranking models"


def test_profile_parse_text_bounds_overlong_fields_instead_of_returning_500(client):
    response = client.post(
        "/api/profile/parse-text",
        json={"text": f"项目名称：{'x' * 200}\n角色：开发"},
    )

    assert response.status_code == 200
    assert len(response.json()["projects"][0]["name"]) == 128


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
