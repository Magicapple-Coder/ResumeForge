"""列表页抽取的优先级、模型兜底与站点记忆。

三块各自守一条：

- **优先级**：能白读出来的页面绝不花钱。存下的配方 → 默认配方 → 模型，前一级读出来就不问下一级。
- **模型那一级**：编号映射（地址不由模型给）、只重试一次、长清单分块且有上限。
- **站点记忆**：只记"问过且什么都没读出来"的页面；内容一变就重新问。
"""
from __future__ import annotations

import json

import pytest

from app.schemas.setting import LLMConfig
from app.services.llm.base import BaseLLMProvider, LLMError
from app.services.sites.official.generic.llm_extract import (
    MAX_ANCHORS_PER_CALL,
    MAX_CALLS_PER_PAGE,
    SYSTEM_PROMPT,
    ListingExtractor,
)
from app.services.sites.official.generic.listing import (
    METHOD_DEFAULT,
    METHOD_MODEL,
    METHOD_NONE,
    METHOD_RECIPE,
    extract_listing,
)
from app.services.sites.official.generic.memory import MAX_UNREADABLE, SiteMemory
from app.services.sites.official.generic.recipe import Recipe

PAGE = "https://careers.example.com/jobs"

LIST_PAGE = """<ul>
<li class="job-card"><a href="/jobs/1">大模型应用开发工程师</a>
  <span class="job-location">北京</span></li>
<li class="job-card"><a href="/jobs/2">算法工程师</a>
  <span class="job-location">上海</span></li>
</ul>"""

# 默认配方读不出来的页面：链接文字是操作文案，标题在旁边。
OPAQUE_PAGE = """<ul>
<li class="row"><h3>大模型应用开发工程师</h3><span class="loc">北京</span>
  <a class="act" href="/p/8821">查看详情</a></li>
<li class="row"><h3>算法工程师</h3><span class="loc">上海</span>
  <a class="act" href="/p/8822">查看详情</a></li>
</ul>"""


class ScriptedProvider(BaseLLMProvider):
    """按脚本逐次回复。``replies`` 用完后就一直用最后一条。"""

    def __init__(self, *replies: str):
        super().__init__(LLMConfig(base_url="http://fake", model="fake-model"))
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    async def chat(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        index = min(len(self.calls) - 1, len(self.replies) - 1)
        return self.replies[index]

    async def stream_chat(self, messages: list[dict]):  # pragma: no cover - 未用到
        yield ""


class FailingProvider(BaseLLMProvider):
    def __init__(self):
        super().__init__(LLMConfig(base_url="http://fake", model="fake-model"))

    async def chat(self, messages: list[dict]) -> str:
        raise LLMError("模型不可用")

    async def stream_chat(self, messages: list[dict]):  # pragma: no cover - 未用到
        yield ""


def _reply(*jobs: dict) -> str:
    return json.dumps({"jobs": list(jobs)}, ensure_ascii=False)


# ===== 优先级 =====


async def test_the_default_recipe_answers_before_the_model_is_asked():
    """**能白读出来的页面绝不花钱**——这是整个优先级存在的理由。"""
    provider = ScriptedProvider(_reply({"index": 1, "title": "不该被问到"}))
    result = await extract_listing(
        LIST_PAGE, PAGE, memory=SiteMemory(), extractor=ListingExtractor(provider)
    )

    assert result.method == METHOD_DEFAULT
    assert provider.calls == []
    assert result.calls == 0


async def test_a_stored_recipe_is_used_before_the_default_one():
    memory = SiteMemory()
    # 这份配方就是归纳层会产出的形状：标题在卡片里的 h3 上，地址片段从模型给的地址里学。
    memory.remember_recipe(
        Recipe.from_dict(
            {
                "schema": 1,
                "url_markers": ["/p/"],
                "title": {"scope": "card", "signature": {"tag": "h3"}, "attr": "text"},
            }
        )
    )
    provider = ScriptedProvider(_reply({"index": 1, "title": "不该被问到"}))

    result = await extract_listing(
        OPAQUE_PAGE, PAGE, memory=memory, extractor=ListingExtractor(provider)
    )

    assert result.method == METHOD_RECIPE
    assert [job.title for job in result.jobs] == ["大模型应用开发工程师", "算法工程师"]
    assert provider.calls == []


async def test_without_a_model_the_result_says_so_plainly():
    """没配模型时如实说明，而不是假装读过了——"读不出来"与"没试"对用户是两件事。"""
    result = await extract_listing(OPAQUE_PAGE, PAGE, memory=SiteMemory(), extractor=None)

    assert result.method == METHOD_NONE
    assert "没有配置" in result.detail


async def test_the_model_is_asked_once_and_the_recipe_is_learned():
    provider = ScriptedProvider(
        _reply(
            {"index": 1, "title": "大模型应用开发工程师", "location": "北京"},
            {"index": 2, "title": "算法工程师", "location": "上海"},
        )
    )
    memory = SiteMemory()

    result = await extract_listing(
        OPAQUE_PAGE, PAGE, memory=memory, extractor=ListingExtractor(provider)
    )

    assert result.method == METHOD_MODEL
    assert result.calls == 1
    assert result.learned is True
    assert memory.listing is not None


async def test_the_second_run_uses_the_learned_recipe_and_costs_nothing():
    """**这就是"为模型只付一次钱"的兑现**。"""
    provider = ScriptedProvider(
        _reply(
            {"index": 1, "title": "大模型应用开发工程师", "location": "北京"},
            {"index": 2, "title": "算法工程师", "location": "上海"},
        )
    )
    memory = SiteMemory()
    await extract_listing(OPAQUE_PAGE, PAGE, memory=memory, extractor=ListingExtractor(provider))

    second = await extract_listing(
        OPAQUE_PAGE, PAGE, memory=memory, extractor=ListingExtractor(provider)
    )

    assert second.method == METHOD_RECIPE
    assert second.calls == 0
    assert len(provider.calls) == 1


async def test_a_failed_induction_still_uses_what_the_model_read():
    """归纳失败**不是错误**：本轮照用数据，只是不落库、下次还得再问一次。"""
    # 两条岗位的标题分别在 h3 与链接自己身上，同一条规则表达不了。
    markup = (
        '<ul><li class="a"><h3>大模型应用开发工程师</h3>'
        '<a class="x" href="/p/1">查看详情</a></li>'
        '<li class="b"><a class="y" href="/p/2">算法工程师</a></li></ul>'
    )
    provider = ScriptedProvider(
        _reply(
            {"index": 1, "title": "大模型应用开发工程师"},
            {"index": 2, "title": "算法工程师"},
        )
    )
    memory = SiteMemory()

    result = await extract_listing(
        markup, PAGE, memory=memory, extractor=ListingExtractor(provider)
    )

    assert result.method == METHOD_MODEL
    assert len(result.jobs) == 2
    assert result.learned is False
    assert result.detail


# ===== 编号映射与幻觉 =====


async def test_the_model_never_supplies_the_address():
    """**地址由编号映射回页面上的真实链接**，所以"编一个不存在的岗位"在结构上不可能。"""
    provider = ScriptedProvider(
        _reply({"index": 1, "title": "大模型应用开发工程师", "location": "北京"})
    )
    result = await extract_listing(
        OPAQUE_PAGE, PAGE, memory=SiteMemory(), extractor=ListingExtractor(provider)
    )

    assert result.jobs[0].url == "https://careers.example.com/p/8821"


async def test_an_index_that_is_not_in_the_list_is_dropped():
    """模型偶尔会数错。丢掉它，而不是顺着编号编一条岗位出来。"""
    provider = ScriptedProvider(
        _reply({"index": 99, "title": "凭空出现的岗位"}, {"index": 1, "title": "大模型应用开发工程师"})
    )
    extraction = await ListingExtractor(provider).extract(OPAQUE_PAGE, PAGE)

    assert [job.title for job in extraction.jobs] == ["大模型应用开发工程师"]
    assert extraction.ungrounded == 1


async def test_off_host_links_never_enter_the_list():
    """跨站链接进了清单，模型就可能把社交分享当成岗位。"""
    markup = '<div><a href="https://weibo.com/x">大模型应用开发工程师</a></div>'
    provider = ScriptedProvider(_reply())

    extraction = await ListingExtractor(provider).extract(markup, PAGE)

    assert provider.calls == []
    assert extraction.jobs == []


async def test_the_prompt_tells_the_model_the_page_is_data_not_instructions():
    """抓回的页面是**不可信输入**。"""
    assert "不是指令" in SYSTEM_PROMPT

    provider = ScriptedProvider(_reply())
    await ListingExtractor(provider).extract(OPAQUE_PAGE, PAGE)

    sent = provider.calls[0]
    assert any("不是指令" in message["content"] for message in sent)


# ===== 重试与分块 =====


async def test_a_structural_failure_is_retried_once():
    provider = ScriptedProvider(
        "我不知道该怎么回答",
        _reply({"index": 1, "title": "大模型应用开发工程师"}),
    )

    extraction = await ListingExtractor(provider).extract(OPAQUE_PAGE, PAGE)

    assert extraction.calls == 2
    assert len(extraction.jobs) == 1


async def test_a_valid_but_empty_answer_is_not_retried():
    """**信息缺失重试无用**：模型没读出来的东西，再问一遍还是读不出来，只是白烧 token。"""
    provider = ScriptedProvider(_reply())

    extraction = await ListingExtractor(provider).extract(OPAQUE_PAGE, PAGE)

    assert extraction.calls == 1
    assert len(provider.calls) == 1


async def test_a_failing_provider_does_not_raise():
    extraction = await ListingExtractor(FailingProvider()).extract(OPAQUE_PAGE, PAGE)

    assert extraction.jobs == []
    assert extraction.calls == 1


async def test_a_long_page_is_split_and_the_cap_is_reported():
    """长清单分块，且**块数有上限**：达到上限时如实说"只读了一部分"。"""
    links = "".join(
        f'<li><a href="/p/{index}">岗位名称第{index}号</a></li>'
        for index in range(1, MAX_ANCHORS_PER_CALL * (MAX_CALLS_PER_PAGE + 2) + 1)
    )
    provider = ScriptedProvider(_reply())

    extraction = await ListingExtractor(provider).extract(f"<ul>{links}</ul>", PAGE)

    assert len(provider.calls) == MAX_CALLS_PER_PAGE
    assert extraction.truncated is True
    assert extraction.detail


async def test_a_page_within_the_cap_is_not_reported_as_truncated():
    provider = ScriptedProvider(_reply())

    extraction = await ListingExtractor(provider).extract(OPAQUE_PAGE, PAGE)

    assert extraction.truncated is False
    assert "只读了前面" not in extraction.detail


# ===== 站点记忆 =====


def test_memory_round_trips_through_json():
    memory = SiteMemory()
    memory.remember_unreadable(PAGE, "<html>甲</html>")

    restored = SiteMemory.from_blob(json.loads(json.dumps(memory.to_blob())))

    assert restored.should_skip_model(PAGE, "<html>甲</html>")
    assert restored.changed is False


@pytest.mark.parametrize("blob", [None, {}, [], "x", {"schema": 99}])
def test_unreadable_memory_blob_is_treated_as_empty(blob):
    memory = SiteMemory.from_blob(blob)

    assert memory.listing is None
    assert memory.should_skip_model(PAGE, "<html>甲</html>") is False


def test_the_fingerprint_notices_a_changed_page():
    """页面改了就要重新问一次：改版常常意味着有新岗位。"""
    memory = SiteMemory()
    memory.remember_unreadable(PAGE, "<html>甲</html>")

    assert memory.should_skip_model(PAGE, "<html>乙</html>") is False


def test_a_learned_recipe_clears_the_unreadable_notes():
    """配方到手之后，之前的"读不出来"记录就不作数了。"""
    memory = SiteMemory()
    memory.remember_unreadable(PAGE, "<html>甲</html>")
    memory.remember_recipe(Recipe())

    assert memory.should_skip_model(PAGE, "<html>甲</html>") is False


def test_the_unreadable_notes_are_bounded():
    """它是省钱用的备忘，不是账本——满了丢最早的，不然这个 JSON 列会越长越大。"""
    memory = SiteMemory()
    for index in range(MAX_UNREADABLE + 5):
        memory.remember_unreadable(f"https://x.com/p/{index}", f"<html>{index}</html>")

    assert len(memory.unreadable) == MAX_UNREADABLE


async def test_an_already_asked_page_is_not_asked_again():
    """**这条省下的是每次采集都会重复花掉的钱。**"""
    provider = ScriptedProvider(_reply())
    memory = SiteMemory()

    first = await extract_listing(
        OPAQUE_PAGE, PAGE, memory=memory, extractor=ListingExtractor(provider)
    )
    second = await extract_listing(
        OPAQUE_PAGE, PAGE, memory=memory, extractor=ListingExtractor(provider)
    )

    assert first.calls == 1
    assert second.calls == 0
    assert len(provider.calls) == 1
    assert "没有重复调用" in second.detail


async def test_a_changed_page_is_asked_again():
    provider = ScriptedProvider(_reply())
    memory = SiteMemory()
    await extract_listing(OPAQUE_PAGE, PAGE, memory=memory, extractor=ListingExtractor(provider))

    changed = OPAQUE_PAGE.replace("算法工程师", "算法工程师（新）")
    await extract_listing(changed, PAGE, memory=memory, extractor=ListingExtractor(provider))

    assert len(provider.calls) == 2


async def test_the_call_budget_is_honoured_within_a_single_page():
    """**额度是按"一次采集"算的，所以必须传到页内。**

    单页自己最多会花 ``MAX_CALLS_PER_PAGE × 2`` 次（分块 × 重试）。调用方只在"页与页之间"
    检查上限的话，一次采集实际能花到上限的将近两倍——而那笔钱是用户自己出的。
    """
    links = "".join(
        f'<li><a href="/p/{index}">岗位名称第{index}号</a></li>'
        for index in range(1, MAX_ANCHORS_PER_CALL * 6)
    )
    provider = ScriptedProvider(_reply())

    extraction = await ListingExtractor(provider).extract(
        f"<ul>{links}</ul>", PAGE, max_calls=2
    )

    assert len(provider.calls) <= 2
    assert extraction.calls <= 2
    # 没读完就要如实说，而且**不能**被记成"问过了、没读出来"（否则这一页以后永远不再问）。
    assert extraction.truncated is True


async def test_a_zero_budget_does_not_call_the_model_at_all():
    """额度用完时一页也不问，并如实说明——而不是问一次再说"没额度了"。"""
    provider = ScriptedProvider(_reply())

    extraction = await ListingExtractor(provider).extract(PAGE and OPAQUE_PAGE, PAGE, max_calls=0)

    assert provider.calls == []
    assert extraction.calls == 0
    assert extraction.truncated is True
    assert extraction.detail


async def test_listing_does_not_mark_a_page_as_asked_when_the_budget_ran_out():
    """额度用完的页面**不能**被记成"问过了、内容没变"——它压根没问过。"""
    provider = ScriptedProvider(_reply())
    memory = SiteMemory()

    await extract_listing(
        OPAQUE_PAGE, PAGE, memory=memory, extractor=ListingExtractor(provider), call_budget=0
    )

    assert memory.should_skip_model(PAGE, OPAQUE_PAGE) is False


# ===== "这一页可能根本不是岗位列表页" =====
# 实测现场：有人把校招的**落地页**（带搜索框与几个招聘项目入口那种）当岗位列表填了进来。
# 整页 895 KB、可读文字一千多字符，站内链接只有 1 个。报告如实说"没读出来"，可它同时说
# 「已跟进完所有认得出来的链接」——**没错，但把"地址给错了"说成了"这一页没有岗位"**，
# 用户只能反复重试同一个错地址。


async def test_a_link_poor_page_says_it_may_not_be_a_job_list():
    provider = ScriptedProvider(_reply())  # 模型也没读出东西

    extraction = await ListingExtractor(provider).extract(OPAQUE_PAGE, PAGE)

    assert not extraction.jobs
    assert "可能不是岗位列表页" in extraction.detail
    assert "2 个站内链接" in extraction.detail, "要把数字说出来，用户才知道该不该换个地址"


async def test_a_normal_page_that_simply_had_no_jobs_says_nothing_extra():
    """链接很多、只是这次没读出岗位的页面**不能**被说成"可能不是岗位列表页"。

    那种页面（真的没有在招岗位、或者模型这次没读准）与"地址给错了"是两件事，
    混成一句会让本该重试的用户去改一个没问题的地址。
    """
    rich = "<ul>" + "".join(
        f'<li><a href="/jobs/{index}">岗位 {index}</a></li>' for index in range(10)
    ) + "</ul>"
    provider = ScriptedProvider(_reply())

    extraction = await ListingExtractor(provider).extract(rich, PAGE)

    assert not extraction.jobs
    assert "可能不是岗位列表页" not in extraction.detail
