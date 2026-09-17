"""助手侧的台账工具：读得到、写得了，但**不能替用户确认**。

最后一条是这个功能的安全边界：一条主张能不能进正式简历，取决于用户有没有核对过。
如果模型能把某条自己新建的条目直接标成「已确认」，那它等于可以自己给自己发通行证，
台账也就失去意义了。
"""
import json

import pytest

from app.services.assistant_tools import execute_tool, tool_names


def _create(db, **overrides):
    arguments = {
        "title": "检索接口",
        "category": "项目经历",
        "subject": "校园知识检索平台",
        "source_fact": "负责检索接口的实现与联调。",
        "candidate_wording": "实现检索接口并联调上线",
        **overrides,
    }
    return execute_tool(db, "create_claim", arguments)


def test_claim_tools_are_exposed_to_the_model():
    names = set(tool_names())
    assert {"list_claims", "get_claim", "create_claim", "update_claim"} <= names


def test_created_claim_is_always_pending(db_session):
    result = _create(db_session)
    payload = json.loads(result.text)
    assert payload["核实状态"] == "待确认"
    assert result.changed is True
    assert result.link == "/claims"


def test_verification_status_cannot_be_smuggled_in(db_session):
    """即使模型把 verification_status 塞进参数，也必须被忽略。"""
    result = _create(db_session, verification_status="已确认")
    assert json.loads(result.text)["核实状态"] == "待确认"

    claim_id = json.loads(result.text)["id"]
    # 只给这一个字段时要明确拒绝，并说清"该由用户确认"，而不是让他以为参数写错了。
    with pytest.raises(ValueError, match="核实状态不能由助手修改"):
        execute_tool(
            db_session, "update_claim", {"claim_id": claim_id, "verification_status": "已确认"}
        )
    # 混在其它字段里同样不能生效。
    execute_tool(
        db_session,
        "update_claim",
        {"claim_id": claim_id, "boundary": "接口由本人实现。", "verification_status": "已确认"},
    )
    detail = json.loads(execute_tool(db_session, "get_claim", {"claim_id": claim_id}).text)
    assert detail["核实状态"] == "待确认"
    assert detail["个人边界"] == "接口由本人实现。"


def test_update_keeps_status_while_changing_other_fields(db_session):
    claim_id = json.loads(_create(db_session).text)["id"]
    execute_tool(
        db_session,
        "update_claim",
        {"claim_id": claim_id, "candidate_wording": "实现检索接口并完成联调", "boundary": "接口由本人实现。"},
    )
    detail = json.loads(execute_tool(db_session, "get_claim", {"claim_id": claim_id}).text)
    assert detail["简历表述"] == "实现检索接口并完成联调"
    assert detail["个人边界"] == "接口由本人实现。"
    assert detail["核实状态"] == "待确认"


def test_update_without_any_field_fails_loudly(db_session):
    claim_id = json.loads(_create(db_session).text)["id"]
    with pytest.raises(ValueError):
        execute_tool(db_session, "update_claim", {"claim_id": claim_id})


def test_missing_claim_reports_a_readable_error(db_session):
    with pytest.raises(ValueError):
        execute_tool(db_session, "get_claim", {"claim_id": 999})
    with pytest.raises(ValueError):
        execute_tool(db_session, "get_claim", {})


def test_create_requires_content_through_the_shared_schema(db_session):
    """工具不自己判一遍，而是走和接口同一套 schema。"""
    with pytest.raises(Exception):
        execute_tool(db_session, "create_claim", {"title": "只有标题"})


def test_list_filters_and_reports_counts(db_session):
    _create(db_session, title="检索接口")
    _create(db_session, title="数据清洗", category="其他")

    payload = json.loads(execute_tool(db_session, "list_claims", {}).text)
    assert payload["总数"] == 2
    assert len(payload["条目"]) == 2

    filtered = json.loads(execute_tool(db_session, "list_claims", {"category": "其他"}).text)
    assert filtered["总数"] == 1
    assert filtered["条目"][0]["标题"] == "数据清洗"


def test_list_output_stays_compact(db_session):
    """列表是给模型判断"这是不是那条"用的，不该把长文本整段塞进上下文。"""
    _create(db_session, source_fact="X" * 5_000)
    payload = json.loads(execute_tool(db_session, "list_claims", {}).text)
    assert len(payload["条目"][0]["原始事实"]) == 200


def test_detail_includes_interview_material_and_advice(db_session):
    claim_id = json.loads(
        _create(db_session, responsibility_level="主导方案或交付").text
    )["id"]
    detail = json.loads(execute_tool(db_session, "get_claim", {"claim_id": claim_id}).text)
    assert detail["承担程度"] == "主导方案或交付"
    assert "面试细节" in detail
    # 强主张没填面试细节时，读取就应该把这条建议带出来，而不是等用户自己去发现。
    assert any("强主张" in item for item in detail["待改进"])
