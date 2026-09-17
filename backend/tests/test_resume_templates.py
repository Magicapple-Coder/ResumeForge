"""简历模板体系：内置样式、格式模板校验、用户自制模板的清洗与渲染。"""
import pytest

from app.database import SessionLocal
from app.services.exporter import render_html
from app.services.resume_sample import sample_resume_content
from app.services.resume_template_store import (
    TemplateError,
    sanitize_template_html,
    validate_template_name,
)
from app.services.resume_templates import (
    FORMAT_PRESETS,
    RESUME_TEMPLATES,
    format_css,
    validated_format_config,
)

CUSTOM_STYLE = """<!DOCTYPE html>
<html><head><title>{{ resume.name }}</title>
<style>body { font-size: var(--fs); } .section-title { color: #123456; }</style>
</head><body>
<script>alert("删除我")</script>
{% include "_resume_sections.j2" %}
</body></html>
"""


@pytest.mark.parametrize("name", sorted(RESUME_TEMPLATES))
def test_every_builtin_template_renders(name):
    html = render_html(sample_resume_content(), template=name)
    assert "<html" in html
    # 页数自适应脚本必须存在：预览靠它判断"内容塞不下"。
    assert "body.dataset" in html or "dataset" in html


def test_format_config_is_validated():
    config = validated_format_config(
        {
            "accent": "#0F766E",
            "line_height": 9.9,  # 超出范围 → 丢弃
            "page_padding": 20,
            "font_scale_adjust": 1.05,
            "evil": "x",  # 不在清单里 → 丢弃
            "text_color": "javascript:alert(1)",  # 不是十六进制 → 丢弃
        }
    )
    assert config == {"accent": "#0f766e", "page_padding": 20.0, "font_scale_adjust": 1.05}


def test_format_css_contains_root_and_rules():
    css = format_css({"accent": "#123456", "line_height": 1.9, "page_padding": 18})
    assert "--accent: #123456;" in css
    assert "line-height: 1.9 !important" in css
    assert "padding: 18mm !important" in css
    # 没有配置时不该产出任何样式块（否则会平白覆盖模板自身版式）。
    assert format_css({}) == ""


def test_format_config_scales_font_and_accent():
    html = render_html(
        sample_resume_content(),
        template="classic",
        font_scale="standard",
        format_config={"font_scale_adjust": 1.1, "accent": "#abcdef"},
    )
    # 标准字号 14px × 1.1 = 15.4px，同时强调色被覆盖。
    assert "--fs: 15.4px" in html
    assert "--accent: #abcdef" in html


def test_font_scale_adjust_has_no_css_mapping():
    """字号系数**只**通过 `base_px` 生效，不能再给一条 CSS 覆盖。

    给两条路会叠乘：界面上调 1.1 会实得 1.21 倍。而这种偏差只有拿尺子量才看得出来，
    所以在这里钉死——`format_css` 对它必须什么都不产出。
    """
    css = format_css({"font_scale_adjust": 0.9})
    assert css == ""
    # 但 base_px 那条路要照常生效（它是对内置模板与用户自制模板都有效的唯一路径）。
    html = render_html(
        sample_resume_content(),
        template="classic",
        font_scale="standard",
        format_config={"font_scale_adjust": 0.9},
    )
    assert "--fs: 12.6px" in html


def test_sanitize_removes_scripts_and_adds_csp():
    cleaned = sanitize_template_html(CUSTOM_STYLE)
    assert "alert(" not in cleaned
    assert "Content-Security-Policy" in cleaned


def test_template_name_validation():
    assert validate_template_name("我的 模板-1") == "我的 模板-1"
    with pytest.raises(TemplateError):
        validate_template_name("")
    with pytest.raises(TemplateError):
        validate_template_name("<script>")


def test_user_style_template_crud_and_render(client, db_session):
    created = client.post(
        "/api/resume-templates",
        json={"name": "我的深色模板", "kind": "style", "html": CUSTOM_STYLE, "description": "测试"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["kind"] == "style"
    # 返回的 HTML 已清洗：脚本被去掉、CSP 已补齐。
    assert "alert(" not in body["html"]
    template_id = body["id"]

    # 出现在可选模板清单里，并被标记为自制。
    catalog = client.get("/api/resumes/templates").json()
    custom = [item for item in catalog["templates"] if item["custom"]]
    assert [item["name"] for item in custom] == ["我的深色模板"]

    # 用它渲染：走沙箱环境，include 的正文片段仍能命中。
    rendered = client.post(
        "/api/resumes/render",
        json={
            "content": sample_resume_content().model_dump(),
            "template": "我的深色模板",
            "page_limit": 1,
            "font_scale": "standard",
        },
    )
    assert rendered.status_code == 200
    assert "白" in rendered.text or "示例" in rendered.text

    # 重名拒绝：名称是选择模板时的唯一标识。
    duplicate = client.post(
        "/api/resume-templates", json={"name": "我的深色模板", "kind": "style", "html": CUSTOM_STYLE}
    )
    assert duplicate.status_code == 400

    assert client.delete(f"/api/resume-templates/{template_id}").status_code == 204
    assert client.get(f"/api/resume-templates/{template_id}").status_code == 404


def test_user_format_template_changes_layout(client):
    created = client.post(
        "/api/resume-templates",
        json={
            "name": "紧凑版式",
            "kind": "format",
            "config": {"line_height": 1.4, "page_padding": 10, "accent": "#111827"},
        },
    )
    assert created.status_code == 201
    assert created.json()["config"]["page_padding"] == 10.0

    # 空配置的格式模板没有意义（用户以为设了什么，实际什么都没生效）。
    empty = client.post("/api/resume-templates", json={"name": "空版式", "kind": "format"})
    assert empty.status_code == 400

    html = render_html(
        sample_resume_content(),
        template="classic",
        format_config=created.json()["config"],
    )
    assert "padding: 10mm !important" in html
    assert "--accent: #111827" in html


def test_layout_update_stores_custom_name_and_ignores_unknown(client):
    client.post(
        "/api/resume-templates",
        json={"name": "我的深色模板", "kind": "style", "html": CUSTOM_STYLE},
    )
    created = client.post(
        "/api/resumes/manual",
        json={"title": "版式测试", "content": {"name": "张三"}},
    )
    record_id = created.json()["id"]

    patched = client.patch(
        f"/api/resumes/{record_id}/layout",
        json={"template": "我的深色模板", "format_name": "不存在", "page_limit": 2, "font_scale": "small"},
    )
    assert patched.status_code == 200
    assert patched.json()["template"] == "我的深色模板"
    # 无法解析的格式模板名不会写进记录，否则导出时会拿到一个空配置。
    assert patched.json()["format_name"] == ""
    assert patched.json()["page_limit"] == 2


def test_template_preview_uses_sample_content(client):
    response = client.post(
        "/api/resume-templates/preview",
        json={"template_name": "modern", "page_limit": 1, "font_scale": "standard"},
    )
    assert response.status_code == 200
    assert "示例" in response.text or "张" in response.text


def test_template_preview_reports_broken_html(client):
    response = client.post(
        "/api/resume-templates/preview",
        json={"html": "<html><head></head><body>{% if %}</body></html>"},
    )
    assert response.status_code == 400
    assert "模板渲染失败" in response.json()["detail"]


def test_format_presets_are_valid():
    for preset in FORMAT_PRESETS:
        # 预设自身必须能通过校验，否则用户选它等于什么都没设。
        validated = validated_format_config(preset["config"])
        assert validated == validated_format_config(validated)
        assert not (preset["name"] != "standard" and preset["config"] and not validated)


def test_generating_with_a_custom_style_keeps_its_name(client, monkeypatch):
    """用自制样式模板生成的简历，记录里必须存**这个名字**，而不是退回 classic。

    生成路径此前用的是 `template_spec(name)["name"]`，那个函数会把不认识的模板名换成
    默认内置模板——于是用户用自制模板生成后一重开预览就变回内置样式，看起来像"我选的
    模板没生效"。PATCH 路径一直是对的，两条路径现在共用同一个解析。
    """
    from app.api import resumes as resumes_api

    created = client.post(
        "/api/resume-templates",
        json={"name": "我的深色模板", "kind": "style", "html": CUSTOM_STYLE},
    )
    assert created.status_code == 201

    # 直接走落库那一步（生成接口要流式调模型，这里不引入假 provider 也测得到同一行代码）。
    with SessionLocal() as db:
        record = resumes_api._save_record(
            db,
            content=sample_resume_content().model_dump(mode="json"),
            warnings=[],
            job=None,
            raw="",
            model="test-model",
            enhancement_enabled=False,
            enhancement_level="balanced",
            template="我的深色模板",
            requested_title="自制模板测试",
        )
        assert record.template == "我的深色模板"
        # 内置模板名仍然规范化，未知名字才退回默认内置模板。
        assert resumes_api._resolved_style_name(db, "modern") == "modern"
        assert resumes_api._resolved_style_name(db, "不存在的模板") == "classic"
