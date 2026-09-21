"""新增模块的接口测试：资料箱、备选岗位、个人照片、技能工作台、简历版式与备份兼容。"""
import json
import zipfile

import pytest

from app.database import SessionLocal
from app.database_migrations import application_tables
from app.models.profile import UserProfile
from app.services.data_backup import (
    BACKUP_FORMAT_VERSION,
    DATABASE_MEMBER,
    MANIFEST_MEMBER,
    BackupError,
    inspect_archive,
)
from app.services.resume.resume_templates import FONT_SCALES
from app.services.update_check import _is_newer

PHOTO_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


# ===== 资料箱 =====


def test_materials_crud_and_category_listing(client):
    created = client.post(
        "/api/materials",
        json={
            "title": "CET-6 成绩单",
            "category": "证书",
            "content": "总分 560",
            "url": "https://example.com/cert",
            "note": "投递时可能要上传扫描件",
            "files": [],
        },
    )
    assert created.status_code == 201
    material_id = created.json()["id"]

    listed = client.get("/api/materials", params={"keyword": "CET"})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [material_id]

    assert client.get("/api/materials", params={"keyword": "不存在"}).json() == []

    updated = client.put(
        f"/api/materials/{material_id}",
        json={
            "title": "CET-6 成绩单（已核验）",
            "category": "证书",
            "content": "总分 560",
            "url": "",
            "note": "",
            "files": [],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "CET-6 成绩单（已核验）"
    assert updated.json()["url"] == ""

    categories = client.get("/api/materials/categories")
    assert categories.status_code == 200
    assert "证书" in categories.json()

    assert client.delete(f"/api/materials/{material_id}").status_code == 204
    assert client.get(f"/api/materials/{material_id}").status_code == 404


def test_material_requires_content_and_caps_attachments(client):
    empty = client.post("/api/materials", json={"title": "", "content": "", "files": []})
    assert empty.status_code == 422

    from app.schemas.material import MAX_MATERIAL_FILES, MAX_MATERIAL_IMAGE_FILES

    def upload(count: int, *, image: bool) -> int:
        files = [
            {
                "name": f"{index}.png" if image else f"{index}.txt",
                "data_url": PHOTO_PNG if image else "",
                "text": "" if image else "正文",
            }
            for index in range(count)
        ]
        return client.post("/api/materials", json={"title": "上限测试", "files": files}).status_code

    # 张数上限之内可用，超过才拒绝。
    assert upload(MAX_MATERIAL_IMAGE_FILES, image=True) == 201
    assert upload(MAX_MATERIAL_IMAGE_FILES + 1, image=True) == 422
    # 文本附件同样有上限，且额度比图片大（文字体积小得多）。
    assert upload(MAX_MATERIAL_FILES, image=False) == 201
    assert upload(MAX_MATERIAL_FILES + 1, image=False) == 422


# ===== 备选岗位 =====


def test_candidate_jobs_crud_and_import_marker(client):
    created = client.post(
        "/api/candidate-jobs",
        json={
            "title": "后端开发工程师",
            "company": "示例公司",
            "raw_text": "岗位职责：负责服务端开发。",
            "note": "等内推码",
            "source": "粘贴文本",
        },
    )
    assert created.status_code == 201
    candidate = created.json()
    assert candidate["status"] == "pending"
    assert candidate["imported_job_id"] is None

    job = client.post(
        "/api/jobs",
        json={
            "title": candidate["title"],
            "company": candidate["company"],
            "description": candidate["raw_text"],
            "recognition_source": "备选岗位导入",
        },
    )
    assert job.status_code == 201
    job_id = job.json()["id"]
    # 来源标注会被自动写进备注，方便用户回溯这条招聘信息是怎么来的。
    assert "来源：备选岗位导入" in job.json()["note"]

    marked = client.post(f"/api/candidate-jobs/{candidate['id']}/imported", json={"job_id": job_id})
    assert marked.status_code == 200
    assert marked.json()["status"] == "imported"
    assert marked.json()["imported_job_id"] == job_id

    assert client.get("/api/candidate-jobs", params={"status": "pending"}).json() == []
    assert len(client.get("/api/candidate-jobs", params={"status": "imported"}).json()) == 1

    assert client.delete(f"/api/candidate-jobs/{candidate['id']}").status_code == 204


def test_candidate_job_requires_some_content(client):
    empty = client.post("/api/candidate-jobs", json={"title": "", "raw_text": ""})
    assert empty.status_code == 422


# ===== 个人照片 =====


def test_profile_photos_switch_and_follow_the_primary(client):
    assert client.get("/api/profile/photos").json() == []

    first = client.post("/api/profile/photos", json={"name": "证件照", "image": PHOTO_PNG})
    assert first.status_code == 201
    assert first.json()["is_primary"] is True

    second = client.post("/api/profile/photos", json={"name": "生活照", "image": PHOTO_PNG})
    assert second.status_code == 201
    # 第二张不会自动抢走主照片的位置。
    assert second.json()["is_primary"] is False

    switched = client.patch(f"/api/profile/photos/{second.json()['id']}", json={"is_primary": True})
    assert switched.status_code == 200
    photos = client.get("/api/profile/photos").json()
    assert [item["is_primary"] for item in photos] == [False, True]

    # 主照片必须同步到 user_profile.photo：简历链路的每一环都只读那个字段。
    with SessionLocal() as db:
        assert db.query(UserProfile).first().photo == PHOTO_PNG

    # 删掉主照片后自动接替，否则简历会突然没有照片。
    assert client.delete(f"/api/profile/photos/{second.json()['id']}").status_code == 204
    remaining = client.get("/api/profile/photos").json()
    assert len(remaining) == 1
    assert remaining[0]["is_primary"] is True

    assert client.delete(f"/api/profile/photos/{remaining[0]['id']}").status_code == 204
    with SessionLocal() as db:
        assert db.query(UserProfile).first().photo == ""


def test_photo_rejects_non_image_payload(client):
    bad = client.post("/api/profile/photos", json={"name": "坏图", "image": "data:text/plain;base64,aGk="})
    assert bad.status_code == 422


# ===== 技能工作台 =====


def test_skill_workbench_create_detail_and_update(client):
    created = client.post(
        "/api/assistant/skills",
        json={
            "name": "简历要点精炼",
            "description": "改写简历要点时使用",
            "prompt": "每条要点不超过 35 字。",
            "files": [{"path": "示例.md", "content": "参考内容"}],
        },
    )
    assert created.status_code == 201
    skill_id = created.json()["id"]
    assert created.json()["prompt"] == "每条要点不超过 35 字。"
    assert [item["path"] for item in created.json()["file_details"]] == ["示例.md"]
    # 知识文件正文要带回来，否则工作台编辑后会把它写空。
    assert created.json()["file_details"][0]["content"] == "参考内容"
    assert created.json()["files_truncated"] is False

    detail = client.get(f"/api/assistant/skills/{skill_id}")
    assert detail.status_code == 200
    assert detail.json()["prompt"] == "每条要点不超过 35 字。"

    updated = client.put(
        f"/api/assistant/skills/{skill_id}",
        json={"prompt": "每条要点不超过 30 字。", "enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["prompt"] == "每条要点不超过 30 字。"
    assert updated.json()["enabled"] is False

    # 同名技能拒绝创建：静默覆盖会丢掉用户已经写好的提示词。
    duplicate = client.post(
        "/api/assistant/skills",
        json={"name": "简历要点精炼", "prompt": "另一份"},
    )
    assert duplicate.status_code == 400


def test_skill_requires_prompt(client):
    missing_prompt = client.post("/api/assistant/skills", json={"name": "没有提示词", "prompt": ""})
    assert missing_prompt.status_code == 400


# ===== 简历版式 =====


def test_resume_template_catalog_and_layout_update(client):
    catalog = client.get("/api/resumes/templates")
    assert catalog.status_code == 200
    body = catalog.json()
    names = {item["name"] for item in body["templates"]}
    # 内置样式模板（自制模板以 custom=True 追加在后面，未创建时应为空）。
    assert {"classic", "modern", "compact", "elegant", "technical", "minimal"} <= names
    assert [item for item in body["templates"] if item["custom"]] == []
    assert {item["name"] for item in body["font_scales"]} == {"small", "standard", "large"}
    # 每个档位都必须带 `base_px`，且**与后端唯一的档位表 FONT_SCALES 完全一致**：
    # 无级字号滑块靠它把拖出来的绝对像素映射回"最近档位 + 系数"。期望值现读
    # FONT_SCALES，而不是在这里抄一份 12/14/15.5——抄了就等于在测试里养出第二份真相，
    # 改档位（后端改一行）时它不会跟着动，"下发值"与"实际渲染值"就会悄悄分叉。
    assert {item["name"]: item["base_px"] for item in body["font_scales"]} == {
        name: spec["base_px"] for name, spec in FONT_SCALES.items()
    }
    # 光"有"这个字段还不够：值必须是正数，否则前端会算出 0 甚至负数的滑块范围。
    assert all(item["base_px"] > 0 for item in body["font_scales"])
    # 格式模板的参数清单与内置预设也要一起下发：生成弹窗与工作台共用这一份。
    assert {item["key"] for item in body["format_fields"]} >= {"accent", "line_height", "page_padding"}
    assert "compact" in {item["name"] for item in body["format_presets"]}
    # 四个版式参数的默认值都由后端下发：生成弹窗每次打开按它重置，
    # 前端自行写死的话，改默认值就会变成两处不一致。
    assert body["defaults"] == {
        "template": "classic",
        "font_scale": "standard",
        "page_limit": 1,
        "format_name": "",
    }
    # 有没有中文字体决定「直接下载 PDF」是否可用，接口必须如实报告。
    assert isinstance(body["pdf_direct_available"], bool)

    created = client.post(
        "/api/resumes/manual",
        json={"title": "版式测试", "content": {"name": "张三", "summary": "测试"}},
    )
    assert created.status_code == 201
    record_id = created.json()["id"]

    layout = client.patch(
        f"/api/resumes/{record_id}/layout",
        json={"template": "modern", "page_limit": 2, "font_scale": "small"},
    )
    assert layout.status_code == 200
    assert layout.json()["template"] == "modern"
    assert layout.json()["page_limit"] == 2
    assert layout.json()["font_scale"] == "small"

    # 渲染接口按同样的版式参数出 HTML：页数写进 body 高度。
    rendered = client.post(
        "/api/resumes/render",
        json={
            "content": {"name": "张三", "summary": "测试"},
            "template": "modern",
            "page_limit": 2,
            "font_scale": "small",
        },
    )
    assert rendered.status_code == 200
    assert "594mm" in rendered.text  # 2 页 × 297mm


def test_resume_layout_rejects_unknown_template(client):
    created = client.post(
        "/api/resumes/manual",
        json={"title": "未知模板", "content": {"name": "张三"}},
    )
    record_id = created.json()["id"]
    # 不认识的模板名不会存进记录：回退到默认模板，而不是渲染时炸掉。
    patched = client.patch(
        f"/api/resumes/{record_id}/layout",
        json={"template": "not-a-template", "page_limit": 1, "font_scale": "standard"},
    )
    assert patched.status_code == 200
    assert patched.json()["template"] == "classic"


def test_template_preview_merges_format_name_with_overrides(client):
    """预览必须与真实渲染同口径：format_name 的基础版式 + format_config 的逐键覆盖。

    此前预览是"有 format_config 就整份顶替 format_name"，于是前端一旦把当前字号系数
    （在 format_config 里）传进来，就会把 format_name 的版式（如 compact 的行高/页边距）
    整个丢掉——缩略图里看到的是"被我自己的系数挤掉版式"的结果，与实际生成的简历不一致。
    """
    response = client.post(
        "/api/resume-templates/preview",
        json={
            "template_name": "classic",
            "format_name": "compact",  # 基础版式：行高 1.45 / 页边距 11mm / 区块间距 0.85
            "format_config": {"font_scale_adjust": 1.021},
            "page_limit": 1,
            "font_scale": "standard",
        },
    )
    assert response.status_code == 200
    body = response.text
    # 1) format_name 的基础版式没有被 format_config 顶掉。
    assert "line-height: 1.45" in body
    assert "padding: 11mm" in body
    # 2) format_config 的系数也照常叠加：标准档 14 × 1.021 = 14.29px。
    assert "calc(14.29px" in body


# ===== 备份与更新检查 =====


def test_application_tables_follow_the_model_registry():
    """表清单必须来自模型注册表：漏一张新表就会让"自己的备份导不回来"。"""
    tables = set(application_tables())
    assert {"material", "candidate_job", "profile_photo"} <= tables
    assert "alembic_version" not in tables


def test_backup_rejects_a_newer_format(tmp_path, db_session):
    archive_path = tmp_path / "future.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(DATABASE_MEMBER, b"placeholder")
        archive.writestr(
            MANIFEST_MEMBER,
            json.dumps({"format": BACKUP_FORMAT_VERSION + 1, "api_key_included": False}),
        )

    with pytest.raises(BackupError, match="更新版本"):
        inspect_archive(archive_path, db_session.get_bind(), tmp_path / "staging")


def test_update_check_version_comparison():
    assert _is_newer("v0.7.0", "0.6.0") is True
    assert _is_newer("0.6.1", "0.6.0") is True
    assert _is_newer("0.6.0", "0.6.0") is False
    # 无法解析的标签不做"有更新"的判断，避免把日期之类的标签当成版本号。
    assert _is_newer("nightly", "0.6.0") is False


# ===== 服务端 PDF 导出 =====


def test_resume_pdf_export_reports_its_page_count(client):
    """PDF 用服务端自己那套排版，页数未必等于用户选的上限——必须如实报出来。

    以前超出上限只写一行服务端日志：用户下载完才发现版式和预览不一样。
    现在页数与上限随响应头一起回去，界面据此提示。
    """
    created = client.post(
        "/api/resumes/manual",
        json={"title": "PDF 测试", "content": {"name": "张三", "summary": "测试"}},
    )
    record_id = created.json()["id"]

    available = client.get("/api/resumes/templates").json()["pdf_direct_available"]
    response = client.get(f"/api/resumes/{record_id}/export?format=pdf")

    if not available:
        # 机器上没有中文字体：接口必须给出可执行的替代方案，而不是产出一份乱码 PDF。
        assert response.status_code == 409
        assert "打印" in response.json()["detail"]
        return

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    pages = int(response.headers["X-Resume-Pages"])
    assert pages >= 1
    assert int(response.headers["X-Resume-Page-Limit"]) == 1


def test_a_long_note_still_keeps_its_source_line():
    """备注接近上限时，来源标注不能被截掉。

    之前是先拼再整体截断：正文一长，刚加上的"来源："就被裁没了，功能静默失效——
    用户以为这条是手填的，而实际上它来自图片识别。
    """
    from app.services.job.job_service import MAX_JOB_NOTE_CHARS, note_with_source

    long_note = "备" * MAX_JOB_NOTE_CHARS
    merged = note_with_source(long_note, "图片识别")

    assert "来源：图片识别" in merged
    assert len(merged) <= MAX_JOB_NOTE_CHARS
    # 用户原文照旧保留在前面，只是被裁到给标注让位。
    assert merged.startswith("备")
