"""导出管线与全参数导出 / 脱敏预览接口。

管线是唯一导出出口：这里钉住注册表含全部六种格式、脱敏作为前置步骤、水印后处理，
以及 ``POST /export`` 全参数与 ``POST /redact`` 预览不落库、不回写。
"""
import urllib.parse

import pytest

from app.schemas.resume import ResumeContent
from app.services.export_pipeline import (
    FORMAT_RENDERERS,
    ExportRequest,
    RenderContext,
    build_export,
)
from app.services.privacy import MASK, RedactionOptions


def _resume() -> ResumeContent:
    return ResumeContent(
        name="张三",
        phone="13800000000",
        email="a@example.com",
        summary="负责后端服务。",
        experience=[{"company": "字节跳动", "role": "工程师", "description": ["实现检索接口"]}],
    )


# ===== 管线单元 =====


def test_registry_includes_all_six_formats():
    assert set(FORMAT_RENDERERS) >= {"json", "md", "html", "pdf", "docx", "txt"}


def test_build_export_renders_docx_and_txt():
    resume = _resume()

    docx = build_export(ExportRequest(format="docx"), resume, RenderContext())
    assert docx.content.startswith(b"PK")
    assert docx.media_type.startswith("application/vnd.openxmlformats")

    txt = build_export(ExportRequest(format="txt"), resume, RenderContext())
    assert txt.media_type == "text/plain; charset=utf-8"
    assert "张三" in txt.content.decode("utf-8")


def test_build_export_applies_redaction_before_rendering():
    resume = _resume()

    artifact = build_export(
        ExportRequest(format="json", redact=True, redact_options=RedactionOptions()),
        resume,
        RenderContext(),
    )

    text = artifact.content.decode("utf-8")
    assert MASK in text
    assert "张三" not in text
    assert "字节跳动" not in text
    assert "a@example.com" not in text


def test_build_export_applies_watermark_to_html():
    resume = _resume()

    artifact = build_export(
        ExportRequest(format="html", watermark="内部使用"),
        resume,
        RenderContext(),
    )

    # 水印是「倾斜 + 重复平铺」的覆盖层；文案在 SVG 数据里，URL 解码后可见。
    text = artifact.content.decode("utf-8")
    assert "background-repeat:repeat" in text
    assert "内部使用" in urllib.parse.unquote(text)


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        build_export(ExportRequest(format="xlsx"), _resume(), RenderContext())


# ===== 全参数导出 / 脱敏预览接口 =====


def _manual_resume(client, content: dict, title: str = "测试") -> int:
    response = client.post(
        "/api/resumes/manual",
        json={"title": title, "content": content, "job_id": None},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_post_export_full_params_returns_docx(client):
    resume_id = _manual_resume(client, {"name": "张三", "summary": "关注后端。"})

    response = client.post(
        f"/api/resumes/{resume_id}/export",
        json={"format": "docx", "watermark": "内部", "redact": False, "include_photo": True},
    )

    assert response.status_code == 200
    assert response.content.startswith(b"PK")
    # 响应头保留页数 / 页数上限（Word 也回传）。
    assert "X-Resume-Page-Limit" in response.headers


def test_post_export_redaction_removes_pii(client):
    resume_id = _manual_resume(
        client, {"name": "张三", "phone": "13800000000", "summary": "关注后端。"}
    )

    response = client.post(
        f"/api/resumes/{resume_id}/export",
        json={"format": "json", "redact": True},
    )

    assert response.status_code == 200
    text = response.content.decode("utf-8")
    assert "***" in text
    assert "张三" not in text
    assert "13800000000" not in text


def test_post_export_unknown_format_is_rejected(client):
    resume_id = _manual_resume(client, {"name": "张三"})

    response = client.post(f"/api/resumes/{resume_id}/export", json={"format": "xlsx"})

    assert response.status_code == 422


def test_post_export_still_honours_the_incomplete_gate(client):
    resume_id = _manual_resume(client, {"name": "张三", "summary": "关注后端【待补】"})

    blocked = client.post(f"/api/resumes/{resume_id}/export", json={"format": "docx"})
    assert blocked.status_code == 409

    allowed = client.post(
        f"/api/resumes/{resume_id}/export",
        json={"format": "docx", "allow_incomplete": True},
    )
    assert allowed.status_code == 200


def test_redact_preview_returns_redacted_content_without_persisting(client):
    resume_id = _manual_resume(
        client, {"name": "张三", "phone": "13800000000", "summary": "关注后端。"}
    )

    response = client.post(f"/api/resumes/{resume_id}/redact", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "***"
    assert body["phone"] == "***"

    # 不落库、不回写：原记录仍是真实值。
    detail = client.get(f"/api/resumes/{resume_id}").json()["content"]
    assert detail["name"] == "张三"
    assert detail["phone"] == "13800000000"


def test_redact_preview_options_are_configurable(client):
    resume_id = _manual_resume(
        client,
        {
            "name": "张三",
            "summary": "关注后端。",
            "education": [{"school": "清华大学", "major": "计算机"}],
        },
    )

    response = client.post(
        f"/api/resumes/{resume_id}/redact",
        json={"mask_school": True, "mask_name": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "张三"  # mask_name=False：不遮罩
    assert body["education"][0]["school"] == "***"  # mask_school=True：遮罩
