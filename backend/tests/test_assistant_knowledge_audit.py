"""E5 求职助手知识审计：改为对 ``feature_catalog``（单一事实来源）做一致性守卫。

能力地图不再是手写静态清单，而是运行时从 ``feature_catalog`` 渲染。这个文件把三向一致
钉住，防止"加了功能 / 加了工具却忘了同步助手"时静默退化：

1. 目录渲染要覆盖每个已注册工具名（助手才能如实说"我能查 XX"而不是猜）；
2. 目录渲染要覆盖每个功能域；
3. 目录 FEATURES 要覆盖白名单 UI 功能 key（水印/脱敏/版本对比/风险检测 ATS/质量检测/
   分享包/模板/美化/自动采集/内推）——这些是**前端 UI 功能**，不在后端工具注册表里，
   正是"问水印答没有"的根因；
4. 写入类工具与 ``build_write_tools_line()`` **双向一致**——单靠 ``Tool.writes`` 或单靠
   目录都不可靠，两边互相校验，新增写工具忘任何一边都会变红；
5. 目录 domain 与前端 ``App.tsx`` 的 MENU_ITEMS label、``userGuideSteps.ts`` 的 title
   **双向静态断言**（读取前端源文件文本正则提取）——前端仍是 UI 唯一事实来源。

再加上几个新工具的冒烟测试，确认读工具 live_only、写工具真的落库。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.services.assistant_tools import execute_tool, tool_names
from app.services.feature_catalog import (
    FEATURES,
    FUNCTIONAL_DOMAINS,
    build_capability_map,
    build_write_tools_line,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"
APP_TSX = FRONTEND_DIR / "src" / "App.tsx"
GUIDE_STEPS_TS = FRONTEND_DIR / "src" / "components" / "userGuideSteps.ts"
README_MD = REPO_ROOT / "README.md"

# README「功能特性」表每一行 → 目录里覆盖它的功能 key（可一对多）。
#
# **这张表就是"助手跟不上新功能"的防呆闸门**：README 是本仓库对用户可见功能的权威清单，
# 而 AGENTS.md 已要求用户可见行为变化必须更新 README。守卫测试双向断言这张表与 README
# 的表格行完全一致、且每个 key 都真实存在于 FEATURES——于是"加了功能、写了 README、
# 却没登记给助手"会直接变红，而不是等用户问到才发现助手答"没有这个功能"。
README_FEATURE_KEYS: dict[str, tuple[str, ...]] = {
    "岗位管理": ("job_manage",),
    "备选岗位": ("candidate_jobs",),
    "拖拽导入": ("drag_drop",),
    "模拟面试": ("interview",),
    "个性化题库": ("question_bank", "interview_review"),
    "工作台": ("skills", "style_format_template"),
    "个人资料库": ("profile",),
    "简历照片": ("profile_photo",),
    "事实台账": ("claims",),
    "面试深挖": ("drill",),
    "资料箱": ("materials",),
    "AI 定制简历": ("resume_generate",),
    "自行编写简历": ("resume_manual",),
    "简历写作增强": ("writing_enhance", "version_diff"),
    "质量与合规检查": ("quality_check",),
    "简历历史": ("resume_history",),
    "岗位关联": ("job_resume_link",),
    "收藏夹": ("favorites",),
    "岗位需求解读": ("job_analysis",),
    "岗位匹配度分析": ("job_match",),
    "匹配度参考分": ("match_reference_score",),
    "求职进度": ("tracker", "tracker_import"),
    "日历提醒": ("reminders",),
    "内推管理": ("referral",),
    "求职数据看板": ("analytics",),
    "面经知识库": ("interview_experience",),
    "知识库": ("knowledge",),
    "自动投递台": (
        "collect",
        "apply_queue",
        "apply_progress",
        "apply_records",
        "browser_setting",
        "current_site",
    ),
    "AI 求职助手": ("assistant_chat",),
    "助手技能": ("skills",),
    "会话管理": ("conversation_manage",),
    "通用简历": ("general_resume",),
    "截图与文档识别": ("recognition",),
    "多格式导出": ("export_formats", "watermark", "redact"),
    "离线分享包": ("share_package",),
    "本地模板市场": ("template_market",),
    "首页": ("home_shortcuts", "home_todo"),
    "界面细节": ("ui_details",),
    "全局搜索": ("global_search",),
    "防虚构校验": ("consistency_check",),
    "检查与更新": ("update_check", "dataset"),
    "回收站": ("trash",),
    "你的 Key 你做主": ("own_api_key", "llm_config"),
}


def _readme_feature_names() -> set[str]:
    """从 README「功能特性」表的第一列取出功能名（去掉行首 emoji）。"""
    text = README_MD.read_text(encoding="utf-8")
    section = text.split("## ✨ 功能特性", 1)[1].split("\n## ", 1)[0]
    names: set[str] = set()
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cell = line.split("|")[1].strip()
        if not cell or set(cell) <= set("-: "):
            continue
        cleaned = re.sub(r"^[^\w]+", "", cell).strip()
        if cleaned and cleaned != "模块":
            names.add(cleaned)
    return names

# 数据域 → 至少要有一个对应的只读工具（与能力地图无关，但同样不能静默退化）。
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

# 指南步骤标题 → 它讲授的功能域（用于「目录 ↔ 指南标题」双向守卫）。
GUIDE_TITLE_DOMAINS = {
    "配置 AI": "设置",
    "完善资料与事实台账": "我的资料",
    "导入岗位与投递": "岗位广场",
    "跟进求职进度": "求职进度",
    "制作简历": "简历中心",
    "求职助手": "求职助手",
    "资料箱、知识库与工作台": "工作台",
    "数据备份与更新": "设置",
}


def _menu_labels() -> set[str]:
    text = APP_TSX.read_text(encoding="utf-8")
    return set(re.findall(r'label:\s*"([^"]+)"', text))


def _guide_titles() -> set[str]:
    text = GUIDE_STEPS_TS.read_text(encoding="utf-8")
    return set(re.findall(r'title:\s*"([^"]+)"', text))


def _catalog_write_tools() -> set[str]:
    """从 ``build_write_tools_line()`` 解析出写入工具名单。"""
    line = build_write_tools_line()
    assert line.startswith("写入类工具："), "写入清单必须以「写入类工具：」开头"
    segment = line.split("：", 1)[1]
    return {name for name in re.split(r"[、，\s]+", segment) if name}


def test_catalog_renders_every_tool_name():
    rendered = build_capability_map()
    missing = [name for name in tool_names() if name not in rendered]
    assert not missing, f"能力地图漏了这些已注册工具：{missing}"


def test_catalog_renders_every_domain():
    rendered = build_capability_map()
    missing = [domain for domain in FUNCTIONAL_DOMAINS if domain not in rendered]
    assert not missing, f"能力地图漏了这些功能域：{missing}"


def test_catalog_covers_every_readme_feature():
    """README 功能表的每一行都必须被目录覆盖——这是"助手跟不上新功能"的防呆闸门。

    加了用户可见功能、按 AGENTS.md 更新了 README，却没登记进 feature_catalog 时，
    这条会立刻变红，而不是等用户问到才发现助手答"没有这个功能"。
    """
    keys = {feature.key for feature in FEATURES}
    missing = sorted(
        name
        for name, mapped in README_FEATURE_KEYS.items()
        if not (set(mapped) & keys)
    )
    assert not missing, f"README 里有、目录里没有对应功能：{missing}"

    dangling = sorted(
        f"{name} → {key}"
        for name, mapped in README_FEATURE_KEYS.items()
        for key in mapped
        if key not in keys
    )
    assert not dangling, f"映射表指向了目录里不存在的 key：{dangling}"


def test_readme_table_and_mapping_are_bidirectionally_aligned():
    """README 的表格行与映射表必须一一对应：改任一边都会变红。"""
    readme_names = _readme_feature_names()
    assert readme_names, "未能从 README「功能特性」表提取到功能名"
    assert set(README_FEATURE_KEYS) == readme_names, (
        f"README 功能表与映射表不一致：\n"
        f"  README 有而映射无：{sorted(readme_names - set(README_FEATURE_KEYS))}\n"
        f"  映射有而 README 无：{sorted(set(README_FEATURE_KEYS) - readme_names)}"
    )


def test_every_catalog_feature_is_claimed_by_a_readme_row():
    """反向：目录里不能有 README 功能表没写的条目——两边互为完整。

    否则目录会攒下"只有助手知道、文档里查不到"的功能，用户无从核对助手说得对不对。
    """
    claimed = {key for mapped in README_FEATURE_KEYS.values() for key in mapped}
    orphans = sorted(feature.key for feature in FEATURES if feature.key not in claimed)
    assert not orphans, f"这些目录功能没有被任何 README 功能行认领：{orphans}"


def test_catalog_feature_keys_are_unique():
    keys = [feature.key for feature in FEATURES]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    assert not duplicates, f"目录里有重复的 key：{duplicates}"


def test_every_feature_belongs_to_a_known_domain():
    domains = set(FUNCTIONAL_DOMAINS)
    stray = [feature.key for feature in FEATURES if feature.domain not in domains]
    assert not stray, f"这些功能挂到了不存在的功能域上：{stray}"


def test_every_data_domain_has_a_read_tool():
    names = set(tool_names())
    missing: list[str] = []
    for domain, tools in DOMAIN_READ_TOOLS.items():
        if not any(tool in names for tool in tools):
            missing.append(f"{domain}（期望 {tools} 至少其一）")
    assert not missing, f"这些数据域没有对应的只读工具：{missing}"


def test_write_tools_are_bidirectionally_consistent_with_catalog():
    """写入工具与目录的 ``build_write_tools_line()`` 双向一致：漏标 writes 或漏渲染都会变红。"""
    from app.services.assistant_tools import _TOOLS as registry

    write_tools = {tool.name for tool in registry if tool.writes}
    assert write_tools, "没有任何工具被标记为写入类，writes 字段可能全部漏标"

    catalog_tools = _catalog_write_tools()
    assert catalog_tools, "目录的「写入类工具」清单解析为空"

    assert write_tools == catalog_tools, (
        f"写入工具与目录清单不一致：\n"
        f"  只在注册表：{sorted(write_tools - catalog_tools)}\n"
        f"  只在目录：{sorted(catalog_tools - write_tools)}"
    )


def test_catalog_domains_match_menu_labels_bidirectionally():
    """目录 domain 与前端 MENU_ITEMS label 双向相等：任一方向多/少一项都会变红。"""
    menu_labels = _menu_labels()
    assert menu_labels, "未能从 App.tsx 提取到 MENU_ITEMS label"
    domains = set(FUNCTIONAL_DOMAINS)
    assert domains == menu_labels, (
        f"目录功能域与菜单不一致：\n"
        f"  菜单有而目录无：{sorted(menu_labels - domains)}\n"
        f"  目录有而菜单无：{sorted(domains - menu_labels)}"
    )


def test_catalog_domains_and_guide_titles_are_bidirectionally_linked():
    """指南步骤标题必须逐条映射到目录里的功能域；映射表多/漏一项都会变红。

    反向（每个功能域都有一条专属指南步骤）不成立：指南按"一段旅程"聚合，多个功能域会
    并进同一步（如「资料箱、知识库与工作台」），因此这里只要求"指南 → 目录"这一向严格
    对齐，另一向由上面的"目录 ↔ 菜单"保证。
    """
    titles = _guide_titles()
    assert titles, "未能从 userGuideSteps.ts 提取到指南步骤 title"
    assert set(GUIDE_TITLE_DOMAINS) == titles, (
        f"指南步骤标题与映射表不一致：\n"
        f"  指南有而映射无：{sorted(titles - set(GUIDE_TITLE_DOMAINS))}\n"
        f"  映射有而指南无：{sorted(set(GUIDE_TITLE_DOMAINS) - titles)}"
    )
    domains = set(FUNCTIONAL_DOMAINS)
    stray = [
        f"{title} → {domain}"
        for title, domain in GUIDE_TITLE_DOMAINS.items()
        if domain not in domains
    ]
    assert not stray, f"指南步骤指向了不存在于目录的功能域：{stray}"


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
