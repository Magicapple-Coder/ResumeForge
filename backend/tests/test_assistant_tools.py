"""助手工具的测试：读写边界、参数校验，以及最容易出事的资料合并。"""
import json

import pytest

from app.schemas.profile import EducationIn, ProfileOut, ProfileUpdate
from app.services.assistant_tools import execute_tool, tool_definitions, tool_names
from app.services.profile_service import get_profile_detail, update_profile

PHOTO = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _seed_profile(db_session) -> None:
    update_profile(
        db_session,
        ProfileUpdate(
            name="不应被清空的姓名",
            phone="13800000000",
            city="北京",
            summary="原有总结",
            photo=PHOTO,
            educations=[EducationIn(school="天津工业大学", major="软件工程")],
        ),
    )


def _profile_snapshot(db_session) -> dict:
    return ProfileOut.model_validate(get_profile_detail(db_session)).model_dump()


def test_update_profile_preserves_everything_the_model_did_not_touch(db_session):
    """资料接口是整份替换语义；工具必须 read-modify-write。

    这是本功能最危险的一处：只提交模型给出的字段，姓名、电话、照片和整段教育经历
    都会被清空。
    """
    _seed_profile(db_session)

    result = execute_tool(db_session, "update_profile", {"city": "天津"})

    assert result.changed is True
    snapshot = _profile_snapshot(db_session)
    assert snapshot["city"] == "天津"
    assert snapshot["name"] == "不应被清空的姓名"
    assert snapshot["phone"] == "13800000000"
    assert snapshot["summary"] == "原有总结"
    assert snapshot["photo"] == PHOTO
    assert [item["school"] for item in snapshot["educations"]] == ["天津工业大学"]


def test_update_profile_rejects_fields_outside_the_editable_set(db_session):
    _seed_profile(db_session)

    # educations 不在可编辑集合里：给出它应当被忽略，而不是覆盖掉原有条目。
    execute_tool(db_session, "update_profile", {"educations": [], "city": "上海"})

    snapshot = _profile_snapshot(db_session)
    assert snapshot["city"] == "上海"
    assert [item["school"] for item in snapshot["educations"]] == ["天津工业大学"]


def test_update_profile_without_editable_fields_fails_loudly(db_session):
    with pytest.raises(ValueError, match="没有给出可修改的资料字段"):
        execute_tool(db_session, "update_profile", {"educations": []})


def test_create_job_validates_through_the_shared_schema(db_session):
    result = execute_tool(db_session, "create_job", {"title": "后端开发实习生", "company": "字节跳动"})

    assert result.changed is True
    assert result.link == "/jobs"
    assert json.loads(result.text)["title"] == "后端开发实习生"


def test_create_job_rejects_invalid_input(db_session):
    # title 必填、status 必须是枚举值——都由 JobCreate 拦下，工具不另写一套校验。
    with pytest.raises(Exception):
        execute_tool(db_session, "create_job", {"company": "只有公司"})
    with pytest.raises(Exception):
        execute_tool(db_session, "create_job", {"title": "岗位", "status": "不存在的状态"})


def test_update_job_only_changes_the_given_fields(db_session):
    created = json.loads(
        execute_tool(db_session, "create_job", {"title": "原岗位", "company": "原公司"}).text
    )

    execute_tool(db_session, "update_job", {"job_id": created["id"], "company": "新公司"})

    text = execute_tool(db_session, "get_job", {"job_id": created["id"]}).text
    assert "新公司" in text
    assert "原岗位" in text


def test_get_job_reports_a_missing_id_instead_of_guessing(db_session):
    with pytest.raises(ValueError, match="不存在"):
        execute_tool(db_session, "get_job", {"job_id": 999})


def test_get_profile_tool_excludes_identity_fields(db_session):
    _seed_profile(db_session)

    text = execute_tool(db_session, "get_profile", {}).text

    # 与项目原有的隐私取舍一致：姓名/电话/照片不进模型上下文。
    assert "不应被清空的姓名" not in text
    assert "13800000000" not in text
    assert "base64" not in text


def test_overview_reports_what_is_already_filled_in(db_session):
    _seed_profile(db_session)
    execute_tool(db_session, "create_job", {"title": "岗位甲"})

    payload = json.loads(execute_tool(db_session, "get_overview", {}).text)

    assert payload["数量"]["岗位"] == 1
    assert payload["数量"]["简历"] == 0
    assert "city" in payload["个人资料已填写"]
    assert "educations(1)" in payload["个人资料已填写"]


def test_no_destructive_tool_is_exposed_to_the_model():
    """用户确认的边界：助手能新增和修改，但没有任何删除能力。"""
    names = tool_names()

    assert names, "工具列表不应为空"
    assert not any(token in name for name in names for token in ("delete", "remove", "clear"))


def test_tool_definitions_are_well_formed():
    for definition in tool_definitions():
        assert definition["type"] == "function"
        function = definition["function"]
        assert function["name"] and function["description"]
        assert function["parameters"]["type"] == "object"


def test_tool_definitions_can_be_disabled():
    assert tool_definitions(enabled=False) == []


def test_unknown_tool_fails_loudly(db_session):
    with pytest.raises(ValueError, match="未知工具"):
        execute_tool(db_session, "drop_everything", {})
