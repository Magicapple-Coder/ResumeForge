"""完整度对账的判定。

这组用例守的是一条性质：**结论宁可说"无法确认"，也绝不把"被截断"说成"已确认为全量"。**
其中最要紧的是 ``test_blocked_crawl_is_never_reported_complete``——那个 bug 不会抛异常、
不会写错误日志，只会给用户一份看起来正常的报告。
"""
from __future__ import annotations

import pytest

from app.models.official import (
    BLOCK_NONE,
    BLOCK_NOT_FOUND,
    BLOCK_RATE_LIMIT,
    BLOCK_SOFT,
    VERDICT_COMPLETE,
    VERDICT_INCOMPLETE,
    VERDICT_UNKNOWN,
)
from app.services.sites.official.reconcile import (
    EVIDENCE_ENUMERATED,
    EVIDENCE_LIST,
    EVIDENCE_NONE,
    EVIDENCE_TOTAL,
    MAX_CANDIDATE_URLS,
    TERMINATION_BLOCKED,
    TERMINATION_CONFLICTED,
    TERMINATION_EXHAUSTED,
    TERMINATION_LIMIT,
    ReconcileInput,
    classify_termination,
    reconcile,
)


# ===== 翻页终止 =====


def test_clean_run_is_exhausted():
    result = classify_termination(blocks=(BLOCK_NONE, BLOCK_NONE), last_has_more=False)
    assert result.state == TERMINATION_EXHAUSTED


def test_rate_limit_anywhere_makes_termination_blocked():
    result = classify_termination(
        blocks=(BLOCK_NONE, BLOCK_RATE_LIMIT, BLOCK_NONE), last_has_more=False
    )
    assert result.state == TERMINATION_BLOCKED


def test_blocked_wins_over_reaching_the_last_page():
    """既被限流又恰好翻到底时，必须先说"被阻断"。

    否则后面那条"到底了"会把结论带成"已确认为全量"。
    """
    result = classify_termination(blocks=(BLOCK_RATE_LIMIT,), last_has_more=False)
    assert result.state == TERMINATION_BLOCKED


def test_page_limit_is_not_exhausted():
    """达到页数上限 = 没走完。它和"抓到底了"是完全不同的两件事。"""
    result = classify_termination(
        blocks=(BLOCK_NONE,), reached_page_limit=True, last_has_more=True
    )
    assert result.state == TERMINATION_LIMIT


def test_site_says_more_but_we_stopped_is_not_exhausted():
    result = classify_termination(blocks=(BLOCK_NONE,), last_has_more=True)
    assert result.state == TERMINATION_LIMIT


def test_late_404_is_conflicted_not_exhausted():
    """第 2 页起 404：既可能是"没有了"，也可能是"接口改了"。不猜。"""
    result = classify_termination(blocks=(BLOCK_NONE, BLOCK_NOT_FOUND), last_has_more=False)
    assert result.state == TERMINATION_CONFLICTED


def test_first_page_404_is_not_conflicted():
    """第 1 页就 404 = 这个端点根本不对（探测阶段的正常否定），不是翻页矛盾。"""
    result = classify_termination(blocks=(BLOCK_NOT_FOUND,), last_has_more=False)
    assert result.state == TERMINATION_EXHAUSTED


# ===== 总量对账（硬结论）=====


def test_total_match_is_complete():
    report = reconcile(ReconcileInput(total_hint=47, collected=47, blocks=(BLOCK_NONE,)))
    assert report.verdict == VERDICT_COMPLETE
    assert report.evidence == EVIDENCE_TOTAL
    assert "47" in report.headline


def test_total_mismatch_reports_the_exact_gap():
    report = reconcile(ReconcileInput(total_hint=47, collected=31, blocks=(BLOCK_NONE,)))
    assert report.verdict == VERDICT_INCOMPLETE
    assert report.missing == 16


def test_more_collected_than_declared_is_unknown_not_complete():
    """抓到的比声明的还多：不是"超额完成"，而是两边口径不一致，不能当作全量。"""
    report = reconcile(ReconcileInput(total_hint=10, collected=14, blocks=(BLOCK_NONE,)))
    assert report.verdict == VERDICT_UNKNOWN
    assert report.evidence == EVIDENCE_TOTAL


def test_total_anchor_survives_a_blocked_termination_when_counts_match():
    """总数已经对上时，中途的限流不影响结论——硬证据不依赖怎么停下来的。

    这条和下面那条一起，划出了"什么证据能压过什么"的边界：**账目对得上**可以压过终止的不确定，
    但账目对不上时终止的不确定只会让结论更保守。
    """
    report = reconcile(
        ReconcileInput(total_hint=20, collected=20, blocks=(BLOCK_NONE, BLOCK_RATE_LIMIT))
    )
    assert report.verdict == VERDICT_COMPLETE


def test_blocked_crawl_with_a_gap_is_incomplete_and_says_why():
    """被限流且总数对不上：结论仍是"已确认不全"，但**必须同时说明是被阻断的**。

    差额本身是确凿的——站点声明 47、我们只有 20，那 27 条确实不在手上，原因不影响这个事实。
    但对用户来说"为什么差"决定了下一步该做什么（重试 vs 换条件），所以终止状态要一并给出。
    """
    report = reconcile(
        ReconcileInput(total_hint=47, collected=20, blocks=(BLOCK_NONE, BLOCK_RATE_LIMIT))
    )
    assert report.verdict == VERDICT_INCOMPLETE
    assert report.missing == 27
    assert report.termination is not None
    assert report.termination.state == TERMINATION_BLOCKED
    assert any("阻断" in str(layer.get("detail", "")) for layer in report.layers)


# ===== 集合对账（硬结论）=====


def test_sitemap_gap_is_unconfirmed_not_a_confirmed_shortfall():
    """**站点地图的差额不是确凿的漏抓数。**

    地图里会有早就招满、URL 却还留着的岗位，所以"地图里有 N 个没抓到"既可能是我们漏了、
    也可能是那些岗位已经下架——不逐个访问就无法区分。报成"已确认不全：差 2 条"就是
    把不确定说成了确定。
    """
    report = reconcile(
        ReconcileInput(enumerated_total=4, candidates=frozenset({"c", "d"}))
    )
    assert report.verdict == VERDICT_UNKNOWN
    assert report.evidence == EVIDENCE_ENUMERATED
    assert report.missing == 2
    # 差额要作为**待核实候选**交给用户，而不是当成结论里的既成事实。
    assert report.candidates == ["c", "d"]
    assert "下架" in report.headline or "核实" in report.headline


def test_sitemap_coverage_alone_does_not_prove_completeness():
    """覆盖了站点地图全集是**正向证据**，但站点地图自己也可能不全，不足以单独下"全量"。"""
    report = reconcile(ReconcileInput(enumerated_total=2, candidates=frozenset()))
    assert report.verdict != VERDICT_INCOMPLETE, "多出来的不该被判成问题"
    # 没有其它层能给出硬结论时，它仍然只能是"无法确认"。
    assert report.verdict == VERDICT_UNKNOWN


def test_sitemap_coverage_combined_with_a_total_anchor_is_hard():
    """集合覆盖 + 总量相符两条正向证据同时在，才可以给出硬结论。"""
    report = reconcile(
        ReconcileInput(total_hint=2, collected=2, enumerated_total=2)
    )
    assert report.verdict == VERDICT_COMPLETE
    assert report.evidence == EVIDENCE_TOTAL


def test_candidates_are_capped_when_the_gap_is_large():
    candidates = frozenset(f"u{index}" for index in range(500))
    report = reconcile(ReconcileInput(enumerated_total=501, candidates=candidates))
    assert report.missing == 500
    assert len(report.candidates) == MAX_CANDIDATE_URLS


# ===== 存活校验（把差额变成硬结论的唯一途径）=====


def test_verified_live_candidates_confirm_a_shortfall():
    """核实出**仍在招**却没抓到的：这是确凿的漏抓，可以给出硬结论。"""
    report = reconcile(
        ReconcileInput(
            enumerated_total=3,
            candidates=frozenset({"a", "b"}),
            verified_live=frozenset({"a"}),
            verified_gone=frozenset({"b"}),
        )
    )
    assert report.verdict == VERDICT_INCOMPLETE
    assert report.missing == 1
    assert report.candidates == ["a"], "只列还在招的那些，它们才是真的漏了"


def test_all_candidates_verified_gone_upgrades_to_complete():
    """差额**全部**核实为已下架 → 差额被完全解释掉了，这才是硬结论。

    注意这与"没差额"是两回事：没差额只是正向证据（地图自己可能不全），而这里是
    **逐条核实过**的。
    """
    report = reconcile(
        ReconcileInput(
            enumerated_total=4,
            candidates=frozenset({"a", "b"}),
            verified_gone=frozenset({"a", "b"}),
        )
    )
    assert report.verdict == VERDICT_COMPLETE
    assert report.evidence == EVIDENCE_ENUMERATED
    assert "下架" in report.headline


def test_partially_verified_difference_stays_unknown():
    """只核实了一部分时，结论必须停在"无法确认"——剩下的仍分不出漏抓与已下架。"""
    report = reconcile(
        ReconcileInput(
            enumerated_total=4,
            candidates=frozenset({"a", "b", "c"}),
            verified_gone=frozenset({"a"}),
        )
    )
    assert report.verdict == VERDICT_UNKNOWN
    assert report.candidates == ["b", "c"], "已核实的从待核实里去掉"


def test_truncated_difference_never_upgrades_to_complete():
    """**差额明细被截断时永远不给"已确认为全量"**：看不见的候选没法核实。

    这里最容易顺手写错——看得见的都核实完了，看起来"处理干净了"，但还有没见过的候选。
    """
    report = reconcile(
        ReconcileInput(
            enumerated_total=500,
            candidates=frozenset({"a", "b"}),
            enumerated_truncated=True,
            verified_gone=frozenset({"a", "b"}),
        )
    )
    assert report.verdict == VERDICT_UNKNOWN
    assert "截断" in report.headline


def test_enumerated_argument_does_not_depend_on_how_the_crawl_ended():
    """集合论证与"怎么停下来的"无关，被阻断也不例外。

    它证明的是"站点地图列出的每一个都被要么抓到、要么核实为已下架"，这个论证不依赖翻页是否
    走完。所以结论可以是硬的——但**终止状态照旧如实写进报告**，用户才知道这次采集被打断过。
    （它依赖的前提是"站点地图足够全"，那是另一个独立的风险，与是否被阻断无关。）
    """
    report = reconcile(
        ReconcileInput(
            enumerated_total=4,
            candidates=frozenset({"a"}),
            verified_gone=frozenset({"a"}),
            blocks=(BLOCK_RATE_LIMIT,),
        )
    )
    assert report.verdict == VERDICT_COMPLETE
    assert report.termination is not None
    assert report.termination.state == TERMINATION_BLOCKED
    assert any("阻断" in str(layer.get("detail", "")) for layer in report.layers)


# ===== 列表对账（软结论）=====


def test_list_counts_agreeing_on_every_page_is_complete():
    report = reconcile(
        ReconcileInput(
            collected=30,
            blocks=(BLOCK_NONE, BLOCK_NONE, BLOCK_NONE),
            page_counts=((10, 10), (10, 10), (10, 10)),
            last_has_more=False,
        )
    )
    assert report.verdict == VERDICT_COMPLETE
    assert report.evidence == EVIDENCE_LIST


def test_page_whose_parsed_count_is_short_is_unknown():
    """一整页只解析出 3 条而页面写着 20 条 = 选择器开始失效。这类漂移不报错，只会静默少数据。"""
    report = reconcile(
        ReconcileInput(
            collected=23,
            blocks=(BLOCK_NONE, BLOCK_NONE),
            page_counts=((20, 20), (3, 20)),
            last_has_more=False,
        )
    )
    assert report.verdict == VERDICT_UNKNOWN
    assert report.evidence == EVIDENCE_LIST
    assert any("2" in str(layer.get("detail", "")) for layer in report.layers)


def test_list_evidence_without_agreement_is_unknown():
    """没有自称条数可比对时，只凭"翻到底了"不足以下"已确认为全量"。"""
    report = reconcile(
        ReconcileInput(
            collected=30,
            blocks=(BLOCK_NONE,),
            page_counts=((30, None),),
            last_has_more=False,
        )
    )
    assert report.verdict == VERDICT_UNKNOWN
    assert report.evidence == EVIDENCE_NONE


def test_failed_first_page_says_why_instead_of_talking_about_evidence():
    """一条都没拿到时，结论要回答"为什么"，而不是"没有依据可比对"。

    接口在第一页就 404（识别结果过期了）时，后者是事实却答非所问。
    """
    report = reconcile(
        ReconcileInput(
            collected=0,
            blocks=(BLOCK_NOT_FOUND,),
            stop_detail="接口不存在（HTTP 404）",
        )
    )
    assert report.verdict == VERDICT_UNKNOWN
    assert "接口不存在" in report.headline


def test_stop_detail_is_ignored_once_something_was_collected():
    """只要拿到了东西，"为什么停下来"就退居次要，结论仍按账目走。"""
    report = reconcile(
        ReconcileInput(
            total_hint=10,
            collected=4,
            blocks=("", "rate_limit"),
            stop_detail="站点限流",
        )
    )
    assert report.verdict == VERDICT_INCOMPLETE
    assert "接口" not in report.headline


def test_no_evidence_at_all_is_unknown():
    report = reconcile(ReconcileInput(collected=5, blocks=(BLOCK_NONE,)))
    assert report.verdict == VERDICT_UNKNOWN
    assert report.evidence == EVIDENCE_NONE


def test_soft_block_terminates_in_unknown():
    report = reconcile(ReconcileInput(collected=0, blocks=(BLOCK_SOFT,)))
    assert report.verdict == VERDICT_UNKNOWN
    assert "软封禁" in report.headline or "无法确认" in report.headline


# ===== 反过来守一遍：任何不确定的路径都不许给出"已确认为全量" =====


@pytest.mark.parametrize(
    "data",
    [
        ReconcileInput(collected=10, blocks=(BLOCK_RATE_LIMIT,)),
        ReconcileInput(collected=10, blocks=(BLOCK_SOFT,)),
        ReconcileInput(collected=10, blocks=(BLOCK_NONE,), reached_page_limit=True),
        ReconcileInput(collected=10, blocks=(BLOCK_NONE, BLOCK_NOT_FOUND)),
        ReconcileInput(collected=10, blocks=(BLOCK_NONE,), page_counts=((5, 10),)),
    ],
)
def test_uncertain_inputs_never_report_complete(data):
    assert reconcile(data).verdict != VERDICT_COMPLETE


@pytest.mark.parametrize(
    "data",
    [
        # 一条都没抓到、站点也没给总数——这正是"认了一个空入口"之后会出现的情形。
        ReconcileInput(collected=0, blocks=(BLOCK_NONE,)),
        # 队列走空（确认到底）也一样：**"翻到底了"不等于"这里有岗位"**。
        ReconcileInput(collected=0, blocks=(BLOCK_NONE,), last_has_more=False),
        # 站点地图可枚举、但差额一条都没核实过。
        ReconcileInput(collected=0, blocks=(BLOCK_NONE,), enumerated_total=3),
    ],
)
def test_an_empty_collection_never_claims_completeness(data):
    """**没有总数契约时，一条都没抓到报不出"已确认为全量"**——这条性质被一处判据依赖。

    ``GenericFeed.empty_entry_is_conclusive`` 之所以敢认"用户给的招聘页地址可以采、哪怕这次
    一条都没读到"，前提就是这里：通用路径不提供总数契约，0 条只会得到「无法确认」。
    哪天有人让这条路径能产出"已确认为全量"，那个判据就必须跟着改回去——所以把它钉在这里，
    而不是只写在注释里。

    **反过来要注意**：有总数契约的适配器不受这条约束（``total_hint == 0`` 时"0 条"是一条
    硬结论，因为接口本身就在回答"这个板子上有几条"）。所以这条性质属于**通用路径**，
    不是"任何 0 条采集都如此"。
    """
    report = reconcile(data)

    assert report.verdict == VERDICT_UNKNOWN
    assert report.verdict != VERDICT_COMPLETE


def test_the_map_layer_cannot_overrule_the_total_contract():
    """**集合层不能压过总量层。**

    站点声明的总数是另一份硬证据。当"地图里的差额全部核实为已下架"与"总数说还差很多"
    同时成立时，至少有一份是错的——这时报「已确认为全量」就是把用户往最危险的方向引：
    他会以为没有漏掉岗位。

    触发它的是一个真实形状：源既有总数契约，又有一批早已失效的站点地图地址（站点整体迁过
    URL / 地图只覆盖一部分）。没有这条判据时，账目明明是 2/200，报告却写"已确认为全量"。
    """
    data = ReconcileInput(
        total_hint=200,
        collected=2,
        blocks=(BLOCK_NONE,),
        enumerated_total=5,
        candidates=frozenset({"https://a.example/jobs/1", "https://a.example/jobs/2"}),
        verified_gone=frozenset({"https://a.example/jobs/1", "https://a.example/jobs/2"}),
    )

    report = reconcile(data)

    assert report.verdict == VERDICT_UNKNOWN
    assert "对不上" in report.headline
    assert any(layer["layer"] == "conflict" for layer in report.layers)


def test_the_map_layer_still_concludes_when_there_is_no_total_contract():
    """反过来：没有总数契约时，地图差额全解释掉就是一份硬结论——这条不能被上面那条削掉。"""
    data = ReconcileInput(
        collected=2,
        blocks=(BLOCK_NONE,),
        enumerated_total=5,
        candidates=frozenset({"https://a.example/jobs/1"}),
        verified_gone=frozenset({"https://a.example/jobs/1"}),
    )

    report = reconcile(data)

    assert report.verdict == VERDICT_COMPLETE


def test_a_matching_total_still_allows_the_map_layer_to_conclude():
    """总数也对得上时，两层证据一致，没有冲突可言。"""
    data = ReconcileInput(
        total_hint=2,
        collected=2,
        blocks=(BLOCK_NONE,),
        enumerated_total=3,
        candidates=frozenset({"https://a.example/jobs/1"}),
        verified_gone=frozenset({"https://a.example/jobs/1"}),
    )

    report = reconcile(data)

    assert report.verdict == VERDICT_COMPLETE
