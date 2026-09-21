"""模板市场（R-19）：``/api/resumes/templates`` 返回 ≥4 套预设，映射既有模板、无新增样式文件。"""
from app.services.resume.resume_templates import (
    FONT_SCALES,
    FORMAT_PRESETS,
    RESUME_TEMPLATES,
    TEMPLATE_MARKET_PRESETS,
    market_options,
)


def test_market_presets_have_at_least_four_categories():
    assert len(TEMPLATE_MARKET_PRESETS) >= 4


def test_market_options_returns_copies():
    options = market_options()
    assert len(options) == len(TEMPLATE_MARKET_PRESETS)
    # 返回的是副本，改调用方拿到的列表不会动到全局常量。
    options[0]["label"] = "被改掉"
    assert TEMPLATE_MARKET_PRESETS[0]["label"] != "被改掉"


def test_every_market_preset_maps_to_existing_builtin_template():
    """4 套预设必须映射既有样式模板，不新建 .html.j2、不引在线资源。"""
    for preset in TEMPLATE_MARKET_PRESETS:
        assert preset["template"] in RESUME_TEMPLATES, preset
        assert preset["format_name"] in {item["name"] for item in FORMAT_PRESETS}, preset
        assert preset["font_scale"] in FONT_SCALES, preset
        assert preset["page_limit"] >= 1


def test_market_field_is_exposed_in_resume_templates_catalog(client):
    response = client.get("/api/resumes/templates")
    assert response.status_code == 200

    market = response.json()["market"]
    assert len(market) >= 4
    for preset in market:
        assert {"name", "label", "category", "description", "template", "format_name", "font_scale"} <= set(preset)
