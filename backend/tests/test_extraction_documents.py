"""岗位/个人资料识别接口的文档输入测试（离线：不配置模型，全走本地规则）。

PDF 走的服务层与这里完全相同（``extract_documents_text``），只是 PDF 的文字层用
ASCII 才能由测试自己拼出来，所以接口层用 DOCX 覆盖中文场景。
"""

import base64

from tests.test_document_text import DOCX_MIME, build_docx, data_url

JOB_DOCUMENT_TEXT = """职位名称：后端开发工程师
公司：字节跳动
工作地点：北京
职位描述
负责 FastAPI 服务开发与维护。
任职要求
熟悉 Python 与 SQL，具备良好的沟通能力。"""

PROFILE_DOCUMENT_LINES = (
    "教育经历",
    "天津工业大学｜软件工程｜本科｜2022.09-2026.06",
)


def document(name: str, *paragraphs: str) -> dict:
    raw = build_docx(*paragraphs)
    return {"name": name, "mime_type": DOCX_MIME, "data": data_url(raw, DOCX_MIME)}


def png_stub(name: str) -> dict:
    raw = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    return {"name": name, "mime_type": "image/png", "data": data_url(raw, "image/png")}


def test_job_parse_text_reads_a_docx_without_a_model(client):
    """文档文字在本机提取，所以没配置模型时本地规则照样能识别。"""
    response = client.post(
        "/api/jobs/parse-text",
        json={"documents": [document("jd.docx", *JOB_DOCUMENT_TEXT.splitlines())]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "后端开发工程师"
    assert body["company"] == "字节跳动"
    assert body["description"] == "负责 FastAPI 服务开发与维护。"
    assert body["requirements"] == "熟悉 Python 与 SQL，具备良好的沟通能力。"
    assert body["recognition_source"] == "local"
    assert any("文档文字已在本机提取" in warning for warning in body["warnings"])


def test_profile_parse_text_merges_pasted_text_and_document(client):
    response = client.post(
        "/api/profile/parse-text",
        json={
            "text": "姓名：张三\n邮箱：zhangsan@example.com",
            "documents": [document("resume.docx", *PROFILE_DOCUMENT_LINES)],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "张三"
    assert body["email"] == "zhangsan@example.com"
    assert body["educations"][0]["school"] == "天津工业大学"


def test_warning_explains_both_screenshot_and_document_limits(client):
    """同时给了截图和文档、又没配模型时，两条说明都要出现。"""
    response = client.post(
        "/api/jobs/parse-text",
        json={
            "images": [png_stub("shot.png")],
            "documents": [document("jd.docx", *JOB_DOCUMENT_TEXT.splitlines())],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "后端开发工程师"
    [warning] = [item for item in body["warnings"] if "未配置大模型" in item]
    assert "图片识别无法进行" in warning
    assert "文档文字已在本机提取" in warning


def test_long_document_warning_reaches_the_response(client):
    # 用真实的多行内容（而不是一整行超长文本）：本地规则解析对单行超长输入是平方级，
    # 拿那种输入做用例会把这条路径的耗时算到解析器头上。
    lines = [f"项目经历：负责第 {index} 个模块的开发与维护" for index in range(1_200)]
    response = client.post(
        "/api/profile/parse-text",
        json={"documents": [document("long.docx", *lines)]},
    )

    assert response.status_code == 200
    assert any("文档内容较长" in warning for warning in response.json()["warnings"])


def test_images_and_documents_share_one_count_budget(client):
    response = client.post(
        "/api/jobs/parse-text",
        json={
            "images": [png_stub(f"{index}.png") for index in range(3)],
            "documents": [document("a.docx", "张三"), document("b.docx", "李四")],
        },
    )

    assert response.status_code == 422
    assert "最多上传 4 个" in response.json()["detail"]


def test_corrupt_document_returns_422_with_a_readable_message(client):
    response = client.post(
        "/api/profile/parse-text",
        json={
            "documents": [
                {
                    "name": "broken.docx",
                    "mime_type": DOCX_MIME,
                    "data": data_url(b"PK\x03\x04broken", DOCX_MIME),
                }
            ]
        },
    )

    assert response.status_code == 422
    assert "DOCX" in response.json()["detail"]


def test_document_is_rejected_before_it_reaches_the_model(client, monkeypatch):
    """损坏的文档在解析阶段就该失败，不该浪费一次模型调用。"""
    calls: list[int] = []

    def _create_provider(_config):
        calls.append(1)
        raise AssertionError("损坏的文档不应触发模型调用")

    monkeypatch.setattr("app.api.profile.create_provider", _create_provider)
    client.put(
        "/api/settings/llm",
        json={"base_url": "https://api.example.com/v1", "api_key": "k", "model": "m"},
    )

    response = client.post(
        "/api/profile/parse-text",
        json={
            "documents": [
                {
                    "name": "scan.pdf",
                    "mime_type": "application/pdf",
                    "data": "data:application/pdf;base64,"
                    + base64.b64encode(b"%PDF-1.4\nnot-a-pdf").decode("ascii"),
                }
            ]
        },
    )

    assert response.status_code == 422
    assert calls == []
