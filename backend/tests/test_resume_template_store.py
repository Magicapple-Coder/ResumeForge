"""自制模板的持久化与解析：清洗、重名、解析回退。

`resolve_style_template` / `resolve_format_config` 是渲染前的最后一道解析：记录里存的
模板名可能指向一个已被删除的自制模板，那时必须安静地退回默认内置模板，而不是让
预览和导出一起报错。
"""
import pytest

from app.services.resume_template_store import (
    TemplateError,
    custom_format_options,
    custom_template_options,
    resolve_format_config,
    resolve_style_template,
    sanitize_template_html,
)

STYLE_HTML = """<!DOCTYPE html>
<html><head><title>{{ resume.name }}</title></head>
<body><script src="https://evil.example/x.js"></script>
<iframe src="https://evil.example"></iframe>
{% include "_resume_sections.j2" %}
</body></html>
"""


def test_sanitize_strips_network_and_scripts():
    cleaned = sanitize_template_html(STYLE_HTML)
    assert "<script" not in cleaned.lower()
    assert "evil.example" not in cleaned
    # 缺 CSP 时自动补上：导出的 HTML 会被当作普通网页打开。
    assert "Content-Security-Policy" in cleaned


def test_resolve_falls_back_to_builtin(db_session):
    name, html = resolve_style_template(db_session, "这个模板不存在")
    assert name == "classic"
    assert html == ""
    assert resolve_format_config(db_session, "也不存在") == {}


def test_resolve_format_preset(db_session):
    config = resolve_format_config(db_session, "compact")
    assert config["line_height"] == 1.45
    # 标准预设本身没有覆盖项，返回空字典代表"沿用模板自带版式"。
    assert resolve_format_config(db_session, "standard") == {}


def test_custom_template_lifecycle(client, db_session):
    created = client.post(
        "/api/resume-templates",
        json={"name": "自定义A", "kind": "style", "html": STYLE_HTML},
    )
    assert created.status_code == 201
    template_id = created.json()["id"]

    # 创建之后按名字能解析到它自己的 HTML。
    name, html = resolve_style_template(db_session, "自定义A")
    assert name == "classic"  # 内置兜底名（沙箱渲染时用不到它的文件）
    assert "resume.name" in html

    # 重名拒绝：模板名是选择模板时的唯一标识。
    duplicate = client.post(
        "/api/resume-templates", json={"name": "自定义A", "kind": "style", "html": STYLE_HTML}
    )
    assert duplicate.status_code == 400
    assert "同名" in duplicate.json()["detail"]

    # 停用后不再出现在可选清单里。
    assert client.put(f"/api/resume-templates/{template_id}", json={"enabled": False}).status_code == 200
    assert custom_template_options(db_session) == []

    # 删除后按名字解析退回默认模板，而不是抛异常。
    assert client.delete(f"/api/resume-templates/{template_id}").status_code == 204
    assert resolve_style_template(db_session, "自定义A") == ("classic", "")


def test_format_template_requires_a_real_setting(client, db_session):
    # 一项都没设的格式模板对用户是"以为设了什么"，直接拒绝。
    empty = client.post("/api/resume-templates", json={"name": "空版式", "kind": "format"})
    assert empty.status_code == 400

    # 越界值会被丢弃，丢掉后没有剩余项时同样按"空配置"拒绝。
    out_of_range = client.post(
        "/api/resume-templates",
        json={"name": "越界版式", "kind": "format", "config": {"line_height": 99}},
    )
    assert out_of_range.status_code == 400

    created = client.post(
        "/api/resume-templates",
        json={"name": "紧凑A", "kind": "format", "config": {"line_height": 1.5, "accent": "#123456"}},
    )
    assert created.status_code == 201
    assert custom_format_options(db_session)[0]["config"] == {
        "line_height": 1.5,
        "accent": "#123456",
    }


def test_builtin_source_is_readable(client):
    response = client.get("/api/resume-templates/builtin-source?name=modern")
    assert response.status_code == 200
    body = response.json()
    assert body["label"] == "现代"
    assert "_resume_sections.j2" in body["html"]

    assert client.get("/api/resume-templates/builtin-source?name=nope").status_code == 404


def test_name_validation_rejects_markup():
    from app.services.resume_template_store import validate_template_name

    with pytest.raises(TemplateError):
        validate_template_name("<script>")


def test_sanitize_replaces_a_template_supplied_csp():
    """模板自带的 CSP 必须被换成应用这一条，而不是让应用这条整个不注入。

    此前的判断是"文档里已经有 Content-Security-Policy 字样就跳过"，于是模板只要写上
    这个词——哪怕只是注释里提一句——就能让应用的 CSP 完全不出现；没有 CSP 之后，
    `<img onerror=...>` 这类事件属性里的脚本会照常执行。
    """
    hostile = (
        "<!DOCTYPE html><html><head>"
        "<!-- Content-Security-Policy -->"
        '<meta http-equiv="Content-Security-Policy" content="default-src *; script-src '
        "'unsafe-inline'\" />"
        "</head><body><p>我的模板</p></body></html>"
    )

    cleaned = sanitize_template_html(hostile)

    # 应用这一条必须在（用 nonce 与 default-src 'none' 作为标志），
    # 而模板自带那条宽松的必须没了。
    assert "script-src 'nonce-" in cleaned
    assert "default-src 'none'" in cleaned
    assert "default-src *" not in cleaned


def test_sanitize_strips_meta_refresh():
    """`<meta http-equiv="refresh">` 能把浏览器自动跳到外部地址，必须剥掉。

    meta 是空元素、没有闭合标签，而剥离规则原来只写成对匹配的那种写法——
    那条正则要求出现 `</meta ...>`，现实中永远不会命中。
    """
    hostile = (
        "<!DOCTYPE html><html><head>"
        '<meta http-equiv="refresh" content="0;url=https://evil.example/phish" />'
        '<meta charset="utf-8" />'
        "</head><body><p>我的模板</p></body></html>"
    )

    cleaned = sanitize_template_html(hostile)

    assert "evil.example" not in cleaned
    assert "url=" not in cleaned
    # 字符集声明与应用的 CSP（本身就是一条 http-equiv meta）都不能被误伤。
    assert "charset" in cleaned.lower()
    assert "Content-Security-Policy" in cleaned
