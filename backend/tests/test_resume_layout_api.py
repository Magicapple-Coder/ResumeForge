"""版面诊断接口与按简历的版式覆盖。

最要紧的一条是**预览与导出必须用同一份版式配置**：如果自动一页只改了预览，
用户会在下载 PDF 之后才发现字号没变——而那时他已经按预览的样子投出去了。
所以这里显式钉住"导出走的是同一条解析路径"。
"""
from app.api.resumes import _record_format_config
from app.models.resume import ResumeRecord

PAGE = 2600.0


def _make_resume(client, **overrides) -> int:
    payload = {
        "title": "测试简历",
        "content": {"name": "张三", "summary": "软件工程本科生。"},
        "job_id": None,
        **overrides,
    }
    response = client.post("/api/resumes/manual", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ===== 诊断接口 =====


def test_analyze_offers_a_ladder_when_the_content_overflows(client):
    resume_id = _make_resume(client)
    response = client.post(
        f"/api/resumes/{resume_id}/layout/analyze",
        json={"measure": {"used_height": PAGE * 1.3, "page_content_height": PAGE, "page_limit": 1}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["diagnosis"]["status"] == "overflow"
    assert body["diagnosis"]["pages_needed"] == 2
    assert len(body["fit_ladder"]) > 0
    # 每一档都要带可直接注入预览的 CSS——客户端不该自己拼这段 CSS。
    assert all(item["css"] for item in body["fit_ladder"])
    assert body["fit_ladder"][0]["config"]["page_padding"] < 14


def test_analyze_returns_no_ladder_when_it_already_fits(client):
    """放得下时给一堆"再收紧一点"只会让人白改一轮。"""
    resume_id = _make_resume(client)
    body = client.post(
        f"/api/resumes/{resume_id}/layout/analyze",
        json={"measure": {"used_height": PAGE * 0.9, "page_content_height": PAGE, "page_limit": 1}},
    ).json()
    assert body["diagnosis"]["status"] == "healthy"
    assert body["fit_ladder"] == []


def test_analyze_reports_the_font_floor_so_the_button_is_not_a_surprise(client):
    resume_id = _make_resume(client)
    body = client.post(
        f"/api/resumes/{resume_id}/layout/analyze",
        json={"measure": {"used_height": PAGE * 1.3, "page_content_height": PAGE, "page_limit": 1}},
    ).json()
    room = body["fit_room"]
    assert room["font_floor_px"] == 12.0
    assert room["has_room"] is True
    assert "9pt" in room["font_floor_note"]


def test_analyze_rejects_an_impossible_measurement(client):
    resume_id = _make_resume(client)
    response = client.post(
        f"/api/resumes/{resume_id}/layout/analyze",
        json={"measure": {"used_height": 100, "page_content_height": 0, "page_limit": 1}},
    )
    # page_content_height 必须是正数——0 表示"还没渲染完就量了"，那是客户端的问题。
    assert response.status_code == 422


def test_analyze_on_a_missing_resume_is_404(client):
    response = client.post(
        "/api/resumes/999/layout/analyze",
        json={"measure": {"used_height": 100, "page_content_height": PAGE, "page_limit": 1}},
    )
    assert response.status_code == 404


# ===== 按简历的版式覆盖 =====


def test_layout_patch_saves_the_override(client):
    resume_id = _make_resume(client)
    response = client.patch(
        f"/api/resumes/{resume_id}/layout",
        json={
            "template": "classic",
            "format_name": "",
            "page_limit": 1,
            "font_scale": "standard",
            "format_config": {"line_height": 1.4, "page_padding": 12},
        },
    )
    assert response.status_code == 200
    assert response.json()["format_config"] == {"line_height": 1.4, "page_padding": 12}


def test_layout_patch_without_format_config_leaves_it_alone(client):
    """`None` 是"这次不涉及"，不能把用户调好的覆盖顺手清掉。"""
    resume_id = _make_resume(client)
    client.patch(
        f"/api/resumes/{resume_id}/layout",
        json={"format_config": {"line_height": 1.4}},
    )
    client.patch(
        f"/api/resumes/{resume_id}/layout",
        json={"page_limit": 2},  # 只改页数，不带 format_config
    )
    assert client.get(f"/api/resumes/{resume_id}").json()["format_config"] == {"line_height": 1.4}


def test_layout_patch_with_an_empty_object_clears_the_override(client):
    """空字典是"清掉覆盖"——与 None 的语义必须区分开。"""
    resume_id = _make_resume(client)
    client.patch(f"/api/resumes/{resume_id}/layout", json={"format_config": {"line_height": 1.4}})
    client.patch(f"/api/resumes/{resume_id}/layout", json={"format_config": {}})
    assert client.get(f"/api/resumes/{resume_id}").json()["format_config"] == {}


def test_layout_patch_validates_the_override(client):
    """这段配置会被拼进 HTML 的 <style>，不校验就等于把 CSS 注入的口子交给前端。"""
    resume_id = _make_resume(client)
    response = client.patch(
        f"/api/resumes/{resume_id}/layout",
        json={
            "format_config": {
                "line_height": 99,  # 超出范围，应被丢掉
                "accent": "javascript:alert(1)",  # 不是十六进制颜色，应被丢掉
                "page_padding": 12,  # 合法
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["format_config"] == {"page_padding": 12}


# ===== 预览与导出必须一致 =====


def test_exported_html_uses_the_per_resume_override(client):
    """自动一页改了预览却没改导出，是这类功能最坏的失败方式。"""
    resume_id = _make_resume(client)
    client.patch(
        f"/api/resumes/{resume_id}/layout",
        json={"format_config": {"line_height": 1.42, "page_padding": 12}},
    )
    html = client.get(f"/api/resumes/{resume_id}/export", params={"format": "html"}).text
    assert "line-height: 1.42" in html
    assert "padding: 12mm" in html


def test_render_accepts_a_temporary_override_without_saving_it(client):
    """自动一页逐档试版式时走这条路：试出来的方案在用户点确认之前不能落库。"""
    resume_id = _make_resume(client)
    response = client.post(
        "/api/resumes/render",
        json={
            "content": {"name": "张三", "summary": "软件工程本科生。"},
            "template": "classic",
            "page_limit": 1,
            "font_scale": "standard",
            "format_config": {"line_height": 1.35},
        },
    )
    assert response.status_code == 200
    assert "line-height: 1.35" in response.text
    # 没有落库
    assert client.get(f"/api/resumes/{resume_id}").json()["format_config"] == {}


def test_font_scale_adjust_reaches_the_html(client):
    """字号系数必须真的作用到渲染出来的 HTML。

    它走的是"渲染前预乘进 base_px"这条路（唯一对内置模板与用户自制模板都生效的路径），
    所以这里断言的是 `--fs` 的最终像素值，而不是某个可以被覆盖的 CSS 变量——
    后者会与预乘叠乘，让界面上调 1.1 实得 1.21 倍。
    """
    response = client.post(
        "/api/resumes/render",
        json={
            "content": {"name": "张三", "summary": "软件工程本科生。"},
            "template": "classic",
            "page_limit": 1,
            "font_scale": "standard",
            "format_config": {"font_scale_adjust": 0.9},
        },
    )
    assert response.status_code == 200
    # 标准档 14px × 0.9 = 12.6px
    assert "--fs: 12.6px" in response.text


def test_override_wins_over_the_named_format_template(client):
    """按简历的覆盖叠加在具名格式模板之上，而不是被它盖掉。"""
    resume_id = _make_resume(client)
    client.patch(
        f"/api/resumes/{resume_id}/layout",
        json={"format_name": "compact", "format_config": {"line_height": 1.9}},
    )
    html = client.get(f"/api/resumes/{resume_id}/export", params={"format": "html"}).text
    # compact 预设本身把行高压到 1.45，按简历的覆盖要能盖过它。
    assert "line-height: 1.9" in html
    assert "line-height: 1.45" not in html


def test_record_format_config_is_the_single_resolution_point(db_session):
    """导出、预览、PDF 三处都调这一个函数，避免各解析一次、解析得不一样。"""
    record = ResumeRecord(
        title="测试",
        content={"name": "张三"},
        format_name="compact",
        format_config={"line_height": 1.9, "accent": "#123456"},
    )
    db_session.add(record)
    db_session.commit()

    config = _record_format_config(db_session, record)
    assert config["line_height"] == 1.9  # 按简历的覆盖赢了
    assert config["accent"] == "#123456"
    assert config["page_padding"] == 11  # 预设里其余项保留
