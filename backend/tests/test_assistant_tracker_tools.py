"""求职助手对求职进度的查询与修改工具测试。"""

import json

from app.services.assistant_tools import execute_tool


def test_assistant_can_create_list_and_update_application_track(db_session):
    created = execute_tool(
        db_session,
        "create_application_track",
        {
            "company": "示例科技",
            "title": "后端开发工程师",
            "status": "applied",
            "applied_at": "2026-09-20",
            "next_action": "等待筛选结果",
        },
    )
    assert created.changed is True
    track_id = json.loads(created.text)["id"]

    listing = json.loads(
        execute_tool(db_session, "list_application_tracks", {"keyword": "示例科技"}).text
    )
    assert listing["总数"] == 1
    assert listing["求职进度"][0]["status_label"] == "已投递"

    updated = execute_tool(
        db_session,
        "update_application_track",
        {"track_id": track_id, "status": "interview", "stage_note": "一面"},
    )
    assert updated.changed is True
    detail = json.loads(execute_tool(db_session, "get_application_track", {"track_id": track_id}).text)
    assert detail["status"] == "interview"
    assert detail["stage_note"] == "一面"


def test_assistant_tracker_tools_do_not_expose_delete():
    from app.services.assistant_tools import tool_names

    assert "delete_application_track" not in tool_names()
