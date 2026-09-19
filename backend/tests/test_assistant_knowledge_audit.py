"""E5 求职助手知识审计的覆盖测试。

三件事在这里钉住，防止将来"加了功能 / 加了工具却忘了同步助手"时静默退化：

1. 系统提示词的能力地图要提到每个功能域（用户问"某功能在哪"时助手才能如实指路）；
2. 每个数据域都要有对应的只读工具（助手才能答"我有几个 X"而不是猜）；
3. 写入类工具与系统提示词的「写入类工具」清单**双向一致**——单靠 `Tool.writes` 或单靠
   提示词清单都不可靠，只有两边互相校验，新增写工具忘任何一边都会变红。

再加上几个新工具的冒烟测试，确认读工具 live_only、写工具真的落库。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.services.assistant_tools import execute_tool, tool_names

PROMPT_PATH = Path(__file__).resolve().parents[1] / "app" / "prompts" / "assistant_system.md"

# 功能域 → 提示词里必须出现的关键词（与「能力地图」一一对应）。
FUNCTIONAL_DOMAINS = (
    "岗位广场",
    "收藏夹",
    "简历中心",
    "投递台",
    "求职进度",
    "模拟面试",
    "我的资料",
    "资料箱",
    "工作台",
    "事实台账",
    "求职统计",
    "知识库",
    "回收站",
    "设置",
    "匹配度分析",
)

# 数据域 → 至少要有一个对应的只读工具。
DOMAIN_READ_TOOLS = {
    "岗位/收藏": ["list_jobs", "get_job"],
    "简历": ["list_resumes", "get_resume"],
    "个人资料": ["get_profile"],
    "资料箱": ["list_materials", "get_material"],
    "事实台账": ["list_claims", "get_claim"],
    "备选岗位": ["list_candidate_jobs", "get_candidate_job"],
    "模拟面试": ["list_interview_sessions", "get_interview_report"],
    "面试深挖": ["list_drill_sessions", "get_drill_report"],
    "技能": ["list_skills", "get_skill"],
    "提醒": ["list_reminders"],
    "内推": ["list_referrals"],
    "面经": ["list_interview_experiences"],
    "题库历史": ["list_question_banks"],
    "复盘历史": ["list_reviews"],
    "知识库": ["list_knowledge", "get_knowledge"],
    "求职统计": ["get_analytics_overview"],
    "分享包": ["list_share_packages"],
}


def _prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _prompt_write_tools() -> set[str]:
    """从提示词「写入类工具：」那一行解析出工具名单。"""
    for line in _prompt().splitlines():
        if line.strip().startswith("写入类工具："):
            segment = line.split("：", 1)[1]
            return {name for name in re.split(r"[、，\s]+", segment) if name}
    return set()


def test_prompt_mentions_every_functional_domain():
    prompt = _prompt()
    missing = [domain for domain in FUNCTIONAL_DOMAINS if domain not in prompt]
    assert not missing, f"系统提示词的能力地图漏了这些功能域：{missing}"


def test_every_data_domain_has_a_read_tool():
    names = set(tool_names())
    missing: list[str] = []
    for domain, tools in DOMAIN_READ_TOOLS.items():
        if not any(tool in names for tool in tools):
            missing.append(f"{domain}（期望 {tools} 至少其一）")
    assert not missing, f"这些数据域没有对应的只读工具：{missing}"


def test_write_tools_are_bidirectionally_consistent_with_prompt():
    """写入工具与提示词清单双向一致：漏标 writes 或漏写提示词都会变红。"""
    from app.services.assistant_tools import _TOOLS as registry

    write_tools = {tool.name for tool in registry if tool.writes}
    assert write_tools, "没有任何工具被标记为写入类，writes 字段可能全部漏标"

    prompt_tools = _prompt_write_tools()
    assert prompt_tools, "系统提示词里没有解析到「写入类工具」清单"

    assert write_tools == prompt_tools, (
        f"写入工具与提示词清单不一致：\n"
        f"  只在注册表：{sorted(write_tools - prompt_tools)}\n"
        f"  只在提示词：{sorted(prompt_tools - write_tools)}"
    )


# ===== 新工具冒烟测试 =====


def test_create_and_list_knowledge(db_session):
    result = execute_tool(
        db_session,
        "create_knowledge",
        {"title": "STAR 法则", "category": "简历技巧", "content": "# STAR 法则"},
    )
    assert result.changed is True
    entry_id = json.loads(result.text)["id"]

    listing = json.loads(execute_tool(db_session, "list_knowledge", {"q": "STAR"}).text)
    assert listing["总数"] == 1
    assert listing["知识库"][0]["id"] == entry_id

    detail = json.loads(execute_tool(db_session, "get_knowledge", {"knowledge_id": entry_id}).text)
    assert detail["content"] == "# STAR 法则"


def test_create_and_list_reminder(db_session):
    result = execute_tool(
        db_session,
        "create_reminder",
        {"title": "参加某司二面", "remind_at": "2026-09-20T10:00:00", "kind": "interview"},
    )
    assert result.changed is True

    listing = json.loads(execute_tool(db_session, "list_reminders", {}).text)
    assert listing["总数"] == 1
    assert listing["提醒"][0]["title"] == "参加某司二面"


def test_new_list_tools_report_zero_when_empty(db_session):
    for tool in (
        "list_referrals",
        "list_interview_experiences",
        "list_question_banks",
        "list_reviews",
        "list_share_packages",
    ):
        payload = json.loads(execute_tool(db_session, tool, {}).text)
        assert payload["总数"] == 0, f"{tool} 空库时应返回总数 0"


def test_analytics_overview_reports_zero_when_empty(db_session):
    payload = json.loads(execute_tool(db_session, "get_analytics_overview", {}).text)
    assert payload["total_applications"] == 0
    assert payload["offer_count"] == 0
    assert isinstance(payload["funnel"], list)


def test_soft_deleted_knowledge_is_not_listed(db_session):
    from app.services.knowledge_service import delete_knowledge

    result = execute_tool(db_session, "create_knowledge", {"title": "要删的一条"})
    entry_id = json.loads(result.text)["id"]

    delete_knowledge(db_session, entry_id)

    listing = json.loads(execute_tool(db_session, "list_knowledge", {}).text)
    assert listing["总数"] == 0
