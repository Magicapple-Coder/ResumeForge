"""措辞门槛：黑话/空话的确定性检查，以及"改写一次"的重试行为。

真机两轮生成的实测结果：提示词点名禁掉的词，模型偶尔仍会写出来（第二轮没有、第一轮有
一个「闭环」），所以除了提示词还需要一层确定性检查。这里的用例钉住三件事：检出是否准确、
是否只重试一次、以及关闭美化时不许碰用户原文。
"""

from app.schemas.resume import GenerateOptions
from app.services.resume_generator import ResumeGenerator, coerce_resume
from app.services.resume_wording import cliche_shortfalls, find_cliches
from tests.test_resume_generator import (
    GOOD_RESUME,
    QualityRetryProvider,
    collect_events,
    make_job,
    make_profile,
)


def _resume(**overrides):
    return coerce_resume({**GOOD_RESUME, **overrides})


def _done(events: list[dict]) -> dict:
    return next(event for event in events if event["type"] == "done")


def test_finds_high_confidence_jargon_in_descriptive_fields():
    resume = _resume(
        summary="以数据驱动的方式赋能业务增长。",
        projects=[
            {
                **GOOD_RESUME["projects"][0],
                "description": ["打通商品与订单流程，形成三端业务闭环"],
            }
        ],
    )

    assert find_cliches(resume) == ["赋能", "闭环"]
    assert "赋能、闭环" in cliche_shortfalls(resume)[0]


def test_ignores_legitimate_resume_verbs():
    """「推动」「落地」「梳理」「负责」是正当的简历表达，不能判成黑话。"""
    resume = _resume(
        summary="负责后端开发，推动接口性能提升，梳理并落地了自动化测试。",
        experience=[
            {
                **GOOD_RESUME["experience"][0],
                "description": ["主导订单服务重构，接口平均响应时间下降 30%"],
            }
        ],
    )

    assert find_cliches(resume) == []
    assert cliche_shortfalls(resume) == []


async def test_cliche_triggers_one_rewrite_and_keeps_the_clean_result():
    dirty = {**GOOD_RESUME, "summary": "以数据驱动的方式赋能业务增长。"}
    clean = {**GOOD_RESUME, "summary": "独立完成后端接口开发，平均响应时间下降 30%。"}
    provider = QualityRetryProvider(dirty, clean)

    events = await collect_events(
        ResumeGenerator(provider).generate(
            make_profile(),
            make_job(),
            GenerateOptions(enhance=True, enhancement_level="balanced"),
        )
    )
    done = _done(events)

    # 只改写一次，且短板清单明确点名了黑话
    assert len(provider.chat_messages) == 1
    assert "空话或互联网黑话" in provider.chat_messages[0][-1]["content"]
    assert any(
        event["type"] == "progress" and "空话或套话" in event["message"] for event in events
    )
    assert done["resume"]["summary"] == clean["summary"]
    assert not any("空话或黑话" in warning for warning in done["warnings"])


async def test_surviving_cliche_is_reported_instead_of_silently_kept():
    first = {**GOOD_RESUME, "summary": "以数据驱动的方式赋能业务增长。"}
    still_dirty = {**GOOD_RESUME, "summary": "持续赋能业务，形成闭环。"}
    provider = QualityRetryProvider(first, still_dirty)

    events = await collect_events(
        ResumeGenerator(provider).generate(
            make_profile(),
            make_job(),
            GenerateOptions(enhance=True, enhancement_level="balanced"),
        )
    )
    done = _done(events)

    # 重试后仍不达标：保留首轮结果，但必须让用户看见（警告列的是最终结果里仍存在的词）
    assert len(provider.chat_messages) == 1
    assert done["resume"]["summary"] == first["summary"]
    assert any("空话或黑话" in warning and "赋能" in warning for warning in done["warnings"])


async def test_cliche_is_left_alone_when_enhancement_is_disabled():
    """关闭美化时正文是用户资料原文，改它就是篡改用户自己的表述。"""
    dirty = {**GOOD_RESUME, "summary": "以数据驱动的方式赋能业务增长。"}
    provider = QualityRetryProvider(dirty, {**GOOD_RESUME})

    events = await collect_events(
        ResumeGenerator(provider).generate(make_profile(), make_job(), GenerateOptions())
    )
    done = _done(events)

    assert provider.chat_messages == []
    assert not any("空话或黑话" in warning for warning in done["warnings"])
