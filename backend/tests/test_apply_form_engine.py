"""通用表单引擎离线测试：喂静态控件快照，断言类型识别与字段映射。

不起浏览器：控件清单是纯数据结构（就是页面脚本会返回的那份 ``controls`` 列表）。
"""
from app.services.apply.form_engine import (
    FIELD_SYNONYMS,
    Control,
    FieldMapping,
    FormEngine,
)
from app.services.browser.cdp_client import CdpClient


class FakeCdpClient(CdpClient):
    def __init__(self, evaluate_result=None):
        self.evaluate_result = evaluate_result
        self.expressions: list[str] = []
        self.uploaded: list[tuple[str, list[str]]] = []
        self.tabs: list[str] = []

    def list_targets(self):
        return []

    def new_tab(self, url: str = "about:blank") -> str:
        self.tabs.append(url)
        return "TAB"

    def send(self, method, params=None, *, timeout=None):
        return {}

    def evaluate(self, expression, *, timeout=None):
        self.expressions.append(expression)
        return self.evaluate_result

    def set_file_input(self, selector, files, *, timeout=None):
        self.uploaded.append((selector, list(files)))

    def close(self):
        pass


RAW_CONTROLS = [
    {
        "index": 0,
        "type": "text",
        "name": "realName",
        "label": "姓名",
        "placeholder": "请输入姓名",
        "required": True,
        "selector": '[data-rf-index="0"]',
    },
    {
        "index": 1,
        "type": "text",
        "name": "mobile",
        "label": "手机号",
        "required": True,
        "selector": '[data-rf-index="1"]',
    },
    {
        "index": 2,
        "type": "text",
        "name": "",
        "placeholder": "请输入邮箱",
        "aria_label": "邮箱",
        "selector": '[data-rf-index="2"]',
    },
    {
        "index": 3,
        "type": "select",
        "name": "",
        "label": "期望城市",
        "options": ["北京", "上海"],
        "selector": '[data-rf-index="3"]',
    },
    {
        "index": 4,
        "type": "radio",
        "name": "edu",
        "label": "学历",
        "selector": '[data-rf-index="4"]',
    },
    {
        "index": 5,
        "type": "file",
        "name": "resume",
        "label": "上传简历",
        "selector": '[data-rf-index="5"]',
    },
    {
        "index": 6,
        "type": "textarea",
        "name": "",
        "label": "自我评价",
        "selector": '[data-rf-index="6"]',
    },
    {
        "index": 7,
        "type": "text",
        "name": "captcha",
        "label": "验证码",
        "required": True,
        "selector": '[data-rf-index="7"]',
    },
]


def test_snapshot_controls_recognizes_types_and_falls_back_to_unknown():
    controls = FormEngine().snapshot_controls(
        RAW_CONTROLS + [{"index": 99, "type": "weird", "label": "未知控件"}]
    )

    assert [c.type for c in controls] == [
        "text",
        "text",
        "text",
        "select",
        "radio",
        "file",
        "textarea",
        "text",
        "unknown",
    ]
    assert controls[3].options == ("北京", "上海")
    assert controls[0].required is True


def test_read_controls_parses_the_page_payload():
    payload = '{"controls": [{"index": 0, "type": "text", "label": "姓名"}]}'
    engine = FormEngine()

    controls = engine.read_controls(FakeCdpClient(payload))

    assert len(controls) == 1
    assert controls[0].label == "姓名"


def test_read_controls_tolerates_a_broken_payload():
    engine = FormEngine()
    assert engine.read_controls(FakeCdpClient("not json")) == []
    assert engine.read_controls(FakeCdpClient({"unexpected": True})) == []


def test_match_fields_maps_by_label_placeholder_aria_and_type():
    engine = FormEngine()
    controls = engine.snapshot_controls(RAW_CONTROLS)
    data = {
        "name": "张三",
        "phone": "13800000000",
        "email": "zhangsan@example.com",
        "city": "北京",
        "education": "本科",
        "resume_file": "/tmp/resume.pdf",
        "summary": "熟悉 Python",
    }

    mapping = {m.field: m.control.index for m in engine.match_fields(controls, data)}

    assert mapping == {
        "name": 0,
        "phone": 1,
        "email": 2,       # 无 label，靠 placeholder / aria-label 命中
        "city": 3,
        "education": 4,   # radio 也认
        "resume_file": 5,
        "summary": 6,
    }


def test_match_fields_never_reuses_one_control_for_two_fields():
    engine = FormEngine()
    controls = engine.snapshot_controls(
        [{"index": 0, "type": "text", "label": "姓名", "selector": '[data-rf-index="0"]'}]
    )

    mappings = engine.match_fields(controls, {"name": "张三", "phone": "138"})

    assert [m.field for m in mappings] == ["name"]


def test_unmapped_required_reports_controls_without_a_field():
    engine = FormEngine()
    controls = engine.snapshot_controls(RAW_CONTROLS)
    mappings = engine.match_fields(controls, {"name": "张三"})

    unmapped = engine.unmapped_required(controls, mappings)

    # "手机号"（必填、未提供资料）与"验证码"（无对应字段）都应被报出来。
    assert {control.index for control in unmapped} == {1, 7}


def test_apply_dispatches_by_control_type():
    engine = FormEngine()
    controls = engine.snapshot_controls(RAW_CONTROLS)
    fake = FakeCdpClient()
    mappings = [
        FieldMapping(control=controls[0], field="name", value="张三"),        # text
        FieldMapping(control=controls[3], field="city", value="北京"),        # select
        FieldMapping(control=controls[4], field="education", value="本科"),  # radio
        FieldMapping(control=controls[5], field="resume_file", value="/tmp/a.pdf"),  # file
        FieldMapping(control=controls[6], field="summary", value="介绍"),      # textarea
    ]

    engine.apply(fake, mappings)

    assert fake.uploaded == [('[data-rf-index="5"]', ["/tmp/a.pdf"])]
    joined = "\n".join(fake.expressions)
    assert "rf:set-value" in joined
    assert "rf:click-control" in joined  # radio 走点击
    assert "HTMLTextAreaElement.prototype" in joined  # textarea 用原生 setter


def test_field_synonyms_cover_every_documented_field():
    for field in ("name", "phone", "email", "city", "resume_file", "summary"):
        assert FIELD_SYNONYMS[field], field


def test_control_signature_is_lowercased_and_handles_empty_strings():
    control = Control(index=0, label="姓名", name="realName")
    assert control.signature() == "姓名 realname"
    assert Control(index=1).signature() == ""
