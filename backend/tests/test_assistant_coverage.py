"""求职助手的数据域覆盖守卫：**每一张表都要有一个明确交代**。

用户的要求是"一定要保证助手知道简历通内所有信息，并且可以操作每一个数据"。
靠人工对着 41 张表逐个回忆是靠不住的——加一张表、加一个功能，没人会记得回来补工具，
而失败方式是**静默的**：助手只是回答"没有这个信息"，用户看不出这是缺陷。

所以这里把"表 → 覆盖它的工具 / 不暴露的理由"写成一张明表：
- 少写一张表 → 测试红（新增模型时必须回来做决定）；
- 写了一个不存在的工具名 → 测试红（工具改名/删除时立刻发现）；
- 写「不暴露」但理由空洞 → 测试红（防止用一句"暂不支持"糊过去）。

"不暴露"本身是允许的，而且有些是**必须**的：密钥（llm_config_record）、照片、
投递任务的执行日志、回收站等。区别在于——**它得是个决定了的事，不是一个漏了的事**。
"""

from __future__ import annotations

from app.database_migrations import application_tables
from app.services.assistant_tools import tool_names

# 表名 → 覆盖它的助手工具名（元组）；或 "不暴露：<理由>"。
#
# 判断标准：
# - 「知道信息」= 至少有一个工具能读到这张表里的内容；
# - 「操作数据」= 至少有工具能改它（只读也算覆盖，但要在理由里说清是只读）。
COVERAGE: dict[str, tuple[str, ...] | str] = {
    # ===== 设置与密钥：刻意不暴露 =====
    "app_setting": "不暴露：全局设置（数据集、界面偏好）。改动会影响整个应用的行为，"
    "应当由用户在设置页显式操作，助手不代为修改。",
    "llm_config_record": "不暴露：模型配置里含 API Key。助手既不读也不写这份配置，"
    "避免密钥进入对话上下文或被间接改动。",
    "profile_photo": "不暴露：照片是二进制图片。助手无法理解图片内容，换照片在「我的资料」里做。",
    # ===== 资料（个人档案与各分区）=====
    "user_profile": ("get_profile", "update_profile"),
    "education": ("get_profile", "update_profile", "add_profile_entry"),
    "experience": ("get_profile", "update_profile", "add_profile_entry"),
    "campus_experience": ("get_profile", "update_profile", "add_profile_entry"),
    "project": ("get_profile", "update_profile", "add_profile_entry"),
    "award": ("get_profile", "update_profile", "add_profile_entry"),
    # ===== 岗位与匹配 =====
    "job": ("list_jobs", "get_job", "create_job", "update_job"),
    "job_match_analysis": ("get_job", "list_jobs", "list_apply_queue"),
    "candidate_job": (
        "list_candidate_jobs",
        "get_candidate_job",
        "create_candidate_job",
        "update_candidate_job",
        "import_candidate_job",
    ),
    # ===== 官网采集（功能已移除，表为历史数据保留）=====
    #
    # 这三张表**还在库里、也还在模型里**：删掉模型会让 ``application_tables()`` 少三张表，
    # 于是含这些表的旧备份会在导入时被判成"来自更新版本"而**拒收**（见 ``data_backup`` 的
    # 表集合校验）。所以表留着，但功能与助手工具都已移除，助手不再读它们。
    "official_site": "不暴露：官网采集功能已移除，这张表只为历史数据保留，助手不再读取。",
    "official_collect_run": "不暴露：官网采集功能已移除，这张表只为历史数据保留，助手不再读取。",
    "official_discovery_search": "不暴露：旧版「按岗位找公司」的历史表，该功能与官网采集都已移除，"
    "表只为历史数据保留，助手不再读取。",
    # ===== 简历 =====
    "resume_record": ("list_resumes", "get_resume", "update_resume_layout"),
    "resume_template": ("create_format_template", "update_format_template"),
    "resume_generate_task": "不暴露：生成任务的实时进度（已收到多少字符、在做什么）。"
    "它是瞬时的过程状态，界面上已经能看到；助手在任务结束后读的是生成好的简历本身。",
    "share_package": ("list_share_packages",),
    # ===== 投递 =====
    "apply_queue_item": ("list_apply_queue",),
    "apply_task": "不暴露：一次投递批次的执行记录。助手不代为发起投递（那一步必须用户点击），"
    "也不需要回放执行日志；队列状态用 list_apply_queue 就能答。",
    "apply_task_item": "不暴露：与 apply_task 同源的单条执行明细，理由同上。",
    # ===== 进度、统计、内推 =====
    "application_track": (
        "list_application_tracks",
        "get_application_track",
        "create_application_track",
        "update_application_track",
    ),
    "referral": ("list_referrals",),
    "reminder": ("list_reminders", "create_reminder"),
    # ===== 事实台账 =====
    "claim_record": ("list_claims", "get_claim", "create_claim", "update_claim"),
    # ===== 资料箱、知识库、技能、题库 =====
    "material": ("list_materials", "get_material", "create_material", "update_material"),
    "knowledge_entry": (
        "list_knowledge",
        "get_knowledge",
        "create_knowledge",
        "update_knowledge",
    ),
    "skill": ("list_skills", "get_skill", "create_skill", "update_skill"),
    "question_bank_record": ("list_question_banks",),
    # ===== 面试与演练 =====
    "interview_session": ("list_interview_sessions", "get_interview_report"),
    "interview_message": ("get_interview_report",),
    "interview_experience": ("list_interview_experiences",),
    "interview_review_record": ("list_reviews",),
    "drill_session": ("list_drill_sessions", "get_drill_report"),
    "drill_contract": ("get_drill_report",),
    "drill_turn": ("get_drill_report",),
    # ===== 助手自身的会话与技能 =====
    "chat_conversation": "不暴露：助手自己的会话记录。它就在对话里，不需要再提供一个工具去读它。",
    "chat_message": "不暴露：助手自己的消息明细。对话内容就在上下文里，"
    "再给一个「读历史消息」的工具只会让助手绕远路去查它已经看得到的东西。",
    "assistant_skill": ("read_skill_knowledge",),
    "assistant_skill_file": ("read_skill_knowledge",),
}


def test_every_application_table_has_a_decision():
    """新增一张表就必须在这里做一个决定：给它工具，或者写明为什么不给。"""
    tables = set(application_tables())
    missing = sorted(tables - set(COVERAGE))
    assert not missing, (
        "这些表既没有对应的助手工具、也没有写明不暴露的理由："
        f"{missing}。新增模型后请到 tests/test_assistant_coverage.py 的 COVERAGE 里做决定。"
    )
    stale = sorted(set(COVERAGE) - tables)
    assert not stale, f"COVERAGE 里有已经不存在于数据库的表：{stale}"


def test_named_tools_actually_exist():
    """写了工具名就得真的有这个工具——改名字时这里立刻红。"""
    known = set(tool_names())
    for table, value in COVERAGE.items():
        if isinstance(value, str):
            continue
        unknown = [name for name in value if name not in known]
        assert not unknown, f"表 {table} 写的工具不存在：{unknown}"


def test_not_exposed_entries_carry_a_real_reason():
    """「不暴露」是允许的，但必须说明为什么——否则它就从"决定"退化成"漏了"。"""
    for table, value in COVERAGE.items():
        if not isinstance(value, str):
            continue
        assert value.startswith("不暴露："), f"表 {table} 的说明不是「不暴露：…」格式"
        reason = value.removeprefix("不暴露：").strip()
        assert len(reason) >= 10, f"表 {table} 的不暴露理由太短，等于没写：{reason!r}"
        assert "暂不" not in reason[:6], f"表 {table} 用了「暂不支持」这类没信息量的说法"


def test_core_user_facing_domains_are_readable():
    """这几个域是用户最常问的，**必须**有工具能读到，不接受"不暴露"。"""
    must_be_readable = (
        "job",
        "resume_record",
        "application_track",
        "candidate_job",
        "claim_record",
        "knowledge_entry",
        "material",
        "skill",
        "interview_session",
        "drill_session",
        "referral",
        "reminder",
    )
    for table in must_be_readable:
        value = COVERAGE[table]
        assert not isinstance(value, str), f"{table} 是核心数据域，必须能被助手读到"


def test_assistant_never_gets_a_delete_tool():
    """助手不提供删除类工具是产品决定（删除只能在页面或回收站里做）。

    这条守卫的意义：将来有人"顺手"加了个 delete_xxx，这里会红。
    """
    forbidden = [name for name in tool_names() if "delete" in name or "remove" in name]
    assert not forbidden, f"助手不应有删除类工具：{forbidden}"
