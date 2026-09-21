"""P6 · 用户自定义必须**真实生效**。

这个文件针对的是一类很伤信任的问题：设置在界面上存下来了、看起来生效了，但实际发出去的
请求里根本没有它。用户投诉的正是"存了但没用上"——而只测"存进去了"完全发现不了。

所以这里的每一条都断言到**最终产物**上：
- 简历自定义样式 → 渲染出来的 HTML；
- 联网搜索的开关与"抓正文条数" → 下发给模型的**工具描述 + 系统提示**；
- 面试的难度 / 轮数 / 考察重点 / 人设 → 发给模型的 **system 消息**；
- 投递招呼语 → 适配器**实际收到**的那一条（见 ``test_apply_task_runner`` 里的同名用例）。

已经另处覆盖、这里不重复的：
- 助手技能提示词进 system 消息 → ``test_assistant.py``；
- 格式模板参数的 CSS 产出 → ``test_resume_templates.py``。
"""
import pytest

from app.api.assistant import _system_prompt, _web_search_addendum
from app.models.interview import InterviewSession
from app.services.assistant_tools import tool_definitions
from app.services.exporter import render_html
from app.services.interview.interview import build_interview_messages
from app.services.resume.resume_sample import sample_resume_content

SENTINEL = "ZZQR_SENTINEL_9F3A"


# ===== 简历：自定义样式模板 =====


def test_a_custom_style_template_reaches_the_rendered_html():
    """用户自制模板里的样式必须真的出现在渲染结果里。

    以前只测过 ``sanitize_template_html``（把危险内容洗掉）——那是"能不能安全地存"，
    和"存进去的东西有没有真的拿去渲染"是两件事。这里用哨兵串把后者钉住。
    """
    custom = (
        "<!DOCTYPE html><html><head><title>{{ resume.name }}</title>"
        f'<style>body {{ --marker: "{SENTINEL}"; }}</style></head><body>'
        '{% include "_resume_sections.j2" %}'
        "</body></html>"
    )

    html = render_html(sample_resume_content(), template_html=custom)

    assert SENTINEL in html
    # 自制模板同样要拿到版式自适应脚本，否则它的预览与打印会对不上。
    assert "--fit-scale" in html
    # 正文片段也要真的渲染进去（而不是只出了一张空壳）。
    assert "专业技能" in html


# ===== 助手：联网搜索配置 =====


def test_web_search_off_removes_both_the_tool_and_the_addendum(db_session):
    """关掉联网开关就是不希望助手联网：工具不下发，系统提示里也不该出现那套说明。

    只删工具、留着"你拥有 web_search 工具"的说明，会让模型去调用一个不存在的工具。
    """
    definitions = tool_definitions(web_search=False)
    assert all("web_search" not in item["function"]["name"] for item in definitions)

    prompt = _system_prompt(db_session, web_search=False)
    assert "联网搜索工具已开启" not in prompt


def test_web_search_on_without_page_fetching_says_it_only_sees_summaries(db_session):
    """抓正文条数为 0（默认）时，必须告诉模型"只看得到摘要"。

    否则它会以为手里有完整正文，引用时就会编出正文里没有的要求。

    注意断言范围：基础系统提示里**本来就有**一句"（只有摘要，还是也含正文节选）由下方的联网
    工具说明给出，以那一节为准"——那是刻意的设计（基础提示不写死答案，交给动态那一节）。
    所以"两版说明互斥"这条只能在**附加说明本身**上验，而不是整份系统提示。
    """
    definitions = tool_definitions(web_search=True, fetch_pages=0)
    search_tool = next(item for item in definitions if item["function"]["name"] == "web_search")
    assert "不打开网页" in search_tool["function"]["description"]

    addendum = _web_search_addendum(fetch_pages=0)
    assert "不得声称已打开网页" in addendum
    assert "正文节选" not in addendum

    prompt = _system_prompt(db_session, web_search=True, fetch_pages=0)
    assert "联网搜索工具已开启" in prompt
    assert addendum in prompt


def test_web_search_on_with_page_fetching_stops_claiming_it_cannot_open_pages(db_session):
    """用户把"抓取正文条数"调大之后，说明必须跟着改口。

    反过来（开着抓正文却告诉模型"不得声称已打开网页"）会让它放着拿到的正文不用，
    回头跟用户说"我只能看到摘要"——用户于是以为这个设置没用。这正是"设了没反应"的典型。
    """
    definitions = tool_definitions(web_search=True, fetch_pages=3)
    search_tool = next(item for item in definitions if item["function"]["name"] == "web_search")
    description = search_tool["function"]["description"]
    assert "抓取正文" in description
    assert "不打开网页" not in description

    addendum = _web_search_addendum(fetch_pages=3)
    assert "正文节选" in addendum
    assert "不得声称已打开网页" not in addendum

    assert addendum in _system_prompt(db_session, web_search=True, fetch_pages=3)


# ===== 模拟面试：设定项进 system 消息 =====


def _session(**overrides) -> InterviewSession:
    data = {
        "title": "面试",
        "interview_type": "技术面",
        "difficulty": "高级",
        "interviewer_style": "严谨专业",
        "rounds": 5,
        "persona": "",
        "focus": "",
    }
    data.update(overrides)
    return InterviewSession(**data)


def _system_of(session: InterviewSession) -> str:
    messages = build_interview_messages(session, index=2)
    return next(item["content"] for item in messages if item["role"] == "system")


def test_interview_settings_all_reach_the_system_message():
    """难度 / 轮数 / 考察重点 / 人设**每一项**都要进 system 消息。

    逐项断言而不是只测人设：只测一项的话，另外几项被某次重构悄悄丢掉时没人会发现。
    """
    system = _system_of(
        _session(
            difficulty="专家",
            rounds=7,
            focus=f"考察重点哨兵 {SENTINEL}",
            persona=f"人设哨兵 {SENTINEL}",
        )
    )

    assert "专家" in system
    assert "7" in system
    assert f"考察重点哨兵 {SENTINEL}" in system
    assert f"人设哨兵 {SENTINEL}" in system
    # 人设那一段要标明"优先级高于默认风格"，否则模型可能两边各取一半。
    assert "优先级高于上面的默认风格" in system


def test_an_empty_persona_does_not_leave_a_dangling_section():
    """没填人设时，那一段必须整段消失（提示词用的是 `{% if persona %}` 条件块）。

    留一个空标题会让模型看到"面试官人设（用户自定义）"下面什么都没有，
    它可能自己编一条人设出来——比不给更糟。
    """
    system = _system_of(_session(persona=""))

    assert "面试官人设" not in system


def test_persona_is_trimmed_before_it_reaches_the_model():
    """前后空白不该进提示词。

    这不只是"好看"的问题：提示词里是 `{% if persona %}`，而 Jinja 认为**纯空白字符串为真**，
    所以"只打了几个空格"的人设会渲染出一个空的「面试官人设」标题——模型看到标题下面什么都没有，
    可能自己编一条出来。所以进入提示词前必须 strip。
    """
    system = _system_of(_session(persona=f"\n\n   {SENTINEL}   \n\n"))

    assert SENTINEL in system
    assert f"   {SENTINEL}" not in system
    assert f"{SENTINEL}   " not in system


def test_a_whitespace_only_persona_is_treated_as_empty():
    """只打了空格的人设等于没填——不能渲染出一个空标题。"""
    system = _system_of(_session(persona="   \n\t  "))

    assert "面试官人设" not in system
    # 纯空白的考察重点也不该盖掉"未指定"的兜底文案。
    assert "未指定，按面试类型通用考察点提问" in system


@pytest.mark.parametrize("field", ["difficulty", "rounds", "focus", "persona"])
def test_each_setting_alone_changes_the_prompt(field):
    """**逐项独立**验证：单独改一项就必须在提示词里体现出来。

    一起改四项再断言"都在"，可能掩盖"其中一项其实是被另一项带进去的"这种巧合。
    """
    baseline = _system_of(_session())
    changed = {
        "difficulty": {"difficulty": "入门"},
        "rounds": {"rounds": 3},
        "focus": {"focus": "只考察分布式事务"},
        "persona": {"persona": "只用英文提问的面试官"},
    }[field]

    assert _system_of(_session(**changed)) != baseline
