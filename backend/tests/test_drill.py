"""面试深挖的核心规则：证据状态、状态只能凭新证据前进、契约先锁后问。

这个模块唯一会误导用户的地方是**状态**：一个虚高的「已验证」会让他以为这条主张讲得清了，
然后在真面试里被问穿。所以测试重点全在"什么时候**不**该升级"上。
"""
import json

import pytest

from app.models.drill import (
    EVIDENCE_CONTRADICTORY,
    EVIDENCE_NOT_COVERED,
    EVIDENCE_PARTIAL,
    EVIDENCE_UNVERIFIED,
    EVIDENCE_VERIFIED,
    REHEARSE_STATUSES,
    evidence_label,
    needs_rehearsal,
    should_promote,
)
from app.models.claim import (
    RESPONSIBILITY_MODULE,
    VERIFICATION_CONFIRMED,
    VERIFICATION_PENDING,
    ClaimRecord,
)
from app.schemas.drill import DrillCreate, DrillPlan
from app.schemas.setting import LLMConfig
from app.services.drill import (
    local_review,
    open_contract,
    parse_plan,
    parse_review,
    parse_verdict,
    select_claims,
    session_summary,
)
from app.services.llm.base import BaseLLMProvider, LLMError


class ScriptedProvider(BaseLLMProvider):
    def __init__(self, response: str):
        super().__init__(LLMConfig(base_url="http://fake", model="fake-model"))
        self.response = response
        self.messages: list[dict] | None = None

    async def chat(self, messages):
        self.messages = messages
        return self.response

    async def stream_chat(self, messages):  # pragma: no cover - 未用到
        yield ""


# ===== 状态只能凭新证据前进 =====


def test_status_advances_only_with_new_evidence():
    assert should_promote(EVIDENCE_UNVERIFIED, EVIDENCE_PARTIAL)
    assert should_promote(EVIDENCE_PARTIAL, EVIDENCE_VERIFIED)
    assert should_promote(EVIDENCE_UNVERIFIED, EVIDENCE_VERIFIED)


def test_status_never_backslides_without_a_contradiction():
    """答得比上次差、但没发现矛盾时不该把状态打回去——那只会让人以为自己退步了。"""
    assert not should_promote(EVIDENCE_VERIFIED, EVIDENCE_PARTIAL)
    assert not should_promote(EVIDENCE_PARTIAL, EVIDENCE_UNVERIFIED)
    assert not should_promote(EVIDENCE_VERIFIED, EVIDENCE_UNVERIFIED)


def test_repeating_the_same_level_is_not_progress():
    for status in (EVIDENCE_VERIFIED, EVIDENCE_PARTIAL, EVIDENCE_UNVERIFIED):
        assert not should_promote(status, status)


def test_contradiction_can_always_overwrite():
    """发现矛盾是决定性的：它可以把"已验证"打回原形。"""
    assert should_promote(EVIDENCE_VERIFIED, EVIDENCE_CONTRADICTORY)
    assert should_promote(EVIDENCE_PARTIAL, EVIDENCE_CONTRADICTORY)
    assert should_promote(EVIDENCE_NOT_COVERED, EVIDENCE_CONTRADICTORY)


def test_not_covered_is_never_a_result():
    """"未覆盖"不是一种结论，任何时候都不该凭它升级。"""
    for previous in (EVIDENCE_NOT_COVERED, EVIDENCE_UNVERIFIED, EVIDENCE_VERIFIED):
        assert not should_promote(previous, EVIDENCE_NOT_COVERED)


def test_recovery_from_a_contradiction_is_a_real_judgement():
    assert should_promote(EVIDENCE_CONTRADICTORY, EVIDENCE_PARTIAL)
    assert should_promote(EVIDENCE_CONTRADICTORY, EVIDENCE_VERIFIED)
    # 但不能靠"未覆盖"来摆脱矛盾。
    assert not should_promote(EVIDENCE_CONTRADICTORY, EVIDENCE_NOT_COVERED)


def test_unknown_status_never_promotes():
    assert not should_promote(EVIDENCE_UNVERIFIED, "看起来还行")
    assert not should_promote("看起来还行", EVIDENCE_VERIFIED)


def test_unknown_status_gets_a_neutral_label():
    assert "未知" in evidence_label("不存在的状态")
    assert evidence_label(EVIDENCE_VERIFIED).startswith("已验证")


def test_only_weak_statuses_need_rehearsal():
    assert needs_rehearsal(EVIDENCE_PARTIAL)
    assert needs_rehearsal(EVIDENCE_UNVERIFIED)
    assert needs_rehearsal(EVIDENCE_CONTRADICTORY)
    # 已验证的不必再练；未覆盖的只是没轮到。
    assert not needs_rehearsal(EVIDENCE_VERIFIED)
    assert not needs_rehearsal(EVIDENCE_NOT_COVERED)
    assert set(REHEARSE_STATUSES) == {
        EVIDENCE_PARTIAL,
        EVIDENCE_UNVERIFIED,
        EVIDENCE_CONTRADICTORY,
    }


# ===== 契约解析 =====


def _plan(**overrides) -> str:
    payload = {
        "intent": "验证个人边界",
        "required_evidence": ["说清两条召回路径各自解决什么", "说明本人负责的实现范围"],
        "followup_triggers": ["只罗列名词，没有数据流"],
        "stop_condition": "必要证据已支持，并完成至多一个反事实追问",
        "question": "为什么用混合召回？",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_parse_plan_reads_a_complete_contract():
    plan = parse_plan(_plan())
    assert plan.question == "为什么用混合召回？"
    assert len(plan.required_evidence) == 2
    assert plan.intent == "验证个人边界"


def test_a_contract_without_required_evidence_is_rejected():
    """没有"必要证据"就没法判定——那会让后面每一轮都变成凭印象打分。"""
    with pytest.raises(LLMError, match="必要证据"):
        parse_plan(_plan(required_evidence=[]))
    with pytest.raises(LLMError, match="必要证据"):
        parse_plan(_plan(required_evidence="说清楚"))


def test_a_contract_without_a_question_is_rejected():
    with pytest.raises(LLMError):
        parse_plan(_plan(question="   "))


def test_parse_plan_rejects_malformed_json():
    with pytest.raises(LLMError):
        parse_plan("不是 JSON")


# ===== 判定解析 =====


def _verdict(**overrides) -> str:
    payload = {
        "status": EVIDENCE_PARTIAL,
        "evidence_found": ["说明了 FTS5 与向量召回的分工"],
        "missing": ["没有说明本人负责的代码范围"],
        "contradictions": [],
        "feedback": "还差个人边界",
        "done": False,
        "action": "followup",
        "followup_kind": "responsibility",
        "question": "这块具体是谁写的？",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_parse_verdict_reads_a_followup():
    verdict = parse_verdict(_verdict(), previous_status=EVIDENCE_NOT_COVERED)
    assert verdict.status == EVIDENCE_PARTIAL
    assert verdict.done is False
    assert verdict.followup_kind == "responsibility"
    assert verdict.question


def test_model_cannot_declare_verified_without_naming_any_evidence():
    """模型说"这次算过了"却列不出任何证据时，绝不能判成「已验证」。

    这是本模块最伤信任的一种失败：一个虚高的「已验证」会让用户以为这条主张讲得清了，
    然后照着它去投简历，面试时第一个问题就露馅。
    """
    # 从「还没判过」出发时降级成「未验证」——这是最保守的诚实结论。
    assert (
        parse_verdict(
            _verdict(status=EVIDENCE_VERIFIED, evidence_found=[], done=True),
            previous_status=EVIDENCE_NOT_COVERED,
        ).status
        == EVIDENCE_UNVERIFIED
    )
    # 从已有判定出发时**保留原判定**：一次没有依据的"通过"不该顺带把已有的结论改掉。
    # 这里只断言"不等于已验证"，因为具体保留成什么由状态机决定、不该由测试猜。
    for previous in (EVIDENCE_PARTIAL, EVIDENCE_UNVERIFIED, EVIDENCE_VERIFIED):
        assert (
            parse_verdict(
                _verdict(status=EVIDENCE_VERIFIED, evidence_found=[], done=True),
                previous_status=previous,
            ).status
            != EVIDENCE_VERIFIED
            or previous == EVIDENCE_VERIFIED
        )


def test_first_verdict_on_an_unanswered_question_is_accepted():
    """`not_covered` 是起点而不是结论——第一次判定必须能生效。"""
    verdict = parse_verdict(
        _verdict(status=EVIDENCE_PARTIAL), previous_status=EVIDENCE_NOT_COVERED
    )
    assert verdict.status == EVIDENCE_PARTIAL


def test_verified_with_evidence_is_accepted_on_the_first_verdict():
    verdict = parse_verdict(
        _verdict(status=EVIDENCE_VERIFIED, done=True), previous_status=EVIDENCE_NOT_COVERED
    )
    assert verdict.status == EVIDENCE_VERIFIED


def test_model_can_advance_when_it_has_evidence():
    verdict = parse_verdict(
        _verdict(status=EVIDENCE_VERIFIED, done=True),
        previous_status=EVIDENCE_PARTIAL,
    )
    assert verdict.status == EVIDENCE_VERIFIED


def test_model_cannot_walk_the_status_backwards():
    verdict = parse_verdict(
        _verdict(status=EVIDENCE_PARTIAL, done=True),
        previous_status=EVIDENCE_VERIFIED,
    )
    assert verdict.status == EVIDENCE_VERIFIED


def test_contradiction_is_accepted_even_from_verified():
    verdict = parse_verdict(
        _verdict(status=EVIDENCE_CONTRADICTORY, contradictions=["与台账写的范围对不上"]),
        previous_status=EVIDENCE_VERIFIED,
    )
    assert verdict.status == EVIDENCE_CONTRADICTORY
    assert verdict.contradictions


def test_unknown_status_falls_back_to_unverified():
    """模型给出没见过的状态时不能猜——落到最保守的「未验证」。"""
    verdict = parse_verdict(
        _verdict(status="差不多过了吧"), previous_status=EVIDENCE_NOT_COVERED
    )
    assert verdict.status == EVIDENCE_UNVERIFIED


def test_unknown_followup_kind_is_dropped():
    verdict = parse_verdict(_verdict(followup_kind="随便问问"), previous_status=EVIDENCE_PARTIAL)
    assert verdict.followup_kind == ""


def test_saying_followup_without_a_question_finishes_the_claim():
    """说要追问却没给问题：当作这道题结束，免得界面停在"等面试官说话"。"""
    verdict = parse_verdict(
        _verdict(done=False, question="  "), previous_status=EVIDENCE_PARTIAL
    )
    assert verdict.done is True


def test_evidence_lists_are_cleaned_and_bounded():
    verdict = parse_verdict(
        _verdict(evidence_found=["a", "a", "  ", "b"]), previous_status=EVIDENCE_PARTIAL
    )
    assert verdict.evidence_found == ["a", "b"]


# ===== 复盘解析 =====


def test_parse_review_reads_actions_and_rehearsal():
    raw = json.dumps(
        {
            "review": {
                "covered": "问了 2 条主张",
                "verified_summary": "一条讲得清",
                "gaps_summary": "一条缺指标口径",
            },
            "actions": [
                {"claim_title": "检索接口", "kind": "补事实", "detail": "补上 QPS 基线"},
                {"claim_title": "空的一条", "kind": "补事实", "detail": "   "},
            ],
            "rehearsal": [
                {"claim_title": "检索接口", "kind": "evidence", "why": "说不清口径"},
                {"claim_title": "另一条", "kind": "不存在的题型", "why": "缺证据"},
            ],
        },
        ensure_ascii=False,
    )
    review = parse_review(raw)
    assert review["covered"] == "问了 2 条主张"
    # 没有 detail 的行动项丢掉——空建议只会让清单看起来很长。
    assert len(review["actions"]) == 1
    # 未知题型退回"变体题"，而不是丢掉这条复练建议。
    assert review["rehearsal"][1]["kind"] == "variant"
    assert review["rehearsal"][0]["kind"] == "evidence"


def test_parse_review_survives_a_missing_review_object():
    review = parse_review(json.dumps({"actions": []}))
    assert review["covered"] == ""
    assert review["actions"] == []


def test_local_review_summarises_without_pretending():
    """没配置模型时的降级：只汇总已有判定，不说"已做过 AI 复盘"。"""
    from app.models.drill import DrillContract, DrillSession

    session = DrillSession(id=1, title="测试")
    session.contracts = [
        DrillContract(id=1, session_id=1, claim_title="讲得清的", status=EVIDENCE_VERIFIED),
        DrillContract(
            id=2,
            session_id=1,
            claim_title="还差的",
            status=EVIDENCE_PARTIAL,
            missing=["没有说明个人边界"],
        ),
    ]
    review = local_review(session)
    assert "讲得清的" in review["verified_summary"]
    assert "还差的" in review["gaps_summary"]
    assert review["actions"][0]["detail"] == "没有说明个人边界"
    assert review["rehearsal"][0]["claim_title"] == "还差的"


# ===== 选哪些主张来挖 =====


def _claim(db, **overrides) -> ClaimRecord:
    payload = {
        "title": "检索接口",
        "category": "项目经历",
        "subject": "检索平台",
        "source_fact": "负责检索接口的实现与联调。",
        "candidate_wording": "实现检索接口并联调上线",
        "responsibility_level": RESPONSIBILITY_MODULE,
        "verification_status": VERIFICATION_CONFIRMED,
        "boundary": "接口由本人实现。",
        "sources": [{"type": "link", "location": "x", "public": True, "note": ""}],
    }
    payload.update(overrides)
    record = ClaimRecord(**payload)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def test_only_confirmed_claims_are_selected(db_session):
    """待确认的主张本来就还没定稿，拿它做"讲不讲得清"的判断没有意义。"""
    confirmed = _claim(db_session, title="已确认的")
    _claim(
        db_session,
        title="待确认的",
        verification_status=VERIFICATION_PENDING,
        candidate_wording="【待补】实现检索接口",
    )
    selected = select_claims(db_session, [], 10)
    assert [item.title for item in selected] == [confirmed.title]


def test_explicit_ids_still_filter_to_confirmed(db_session):
    a = _claim(db_session, title="A")
    b = _claim(
        db_session,
        title="B",
        verification_status=VERIFICATION_PENDING,
        candidate_wording="【待补】做了一件事",
    )
    selected = select_claims(db_session, [a.id, b.id], 10)
    assert [item.title for item in selected] == ["A"]


def test_selection_is_bounded(db_session):
    for index in range(5):
        _claim(db_session, title=f"主张 {index}")
    assert len(select_claims(db_session, [], 2)) == 2


# ===== 会话计数 =====


def test_session_summary_counts_each_status():
    from app.models.drill import DrillContract, DrillSession

    session = DrillSession(id=1, title="测试")
    session.contracts = [
        DrillContract(id=1, session_id=1, claim_title="a", status=EVIDENCE_VERIFIED),
        DrillContract(id=2, session_id=1, claim_title="b", status=EVIDENCE_PARTIAL),
        DrillContract(id=3, session_id=1, claim_title="c", status=EVIDENCE_NOT_COVERED),
    ]
    summary = session_summary(session)
    assert summary["questions"] == 3
    assert summary["verified_count"] == 1
    assert summary["partial_count"] == 1
    # 没有的状态也要出现，界面不用再补 0。
    assert summary["status_counts"][EVIDENCE_CONTRADICTORY] == 0


# ===== Schema =====


def test_drill_create_deduplicates_claim_ids():
    payload = DrillCreate(claim_ids=[3, 1, 3, 2])
    assert payload.claim_ids == [3, 1, 2]


def test_drill_create_rejects_an_unknown_feedback_policy():
    with pytest.raises(Exception):
        DrillCreate(feedback_policy="随便")


def test_drill_plan_requires_at_least_one_evidence_item():
    with pytest.raises(Exception):
        DrillPlan(question="问什么？", required_evidence=[])


def test_open_contract_keeps_the_plan_intact(db_session):
    """契约落库后必须与生成时逐字一致——判定要照着它判。"""
    from app.models.drill import DrillSession

    record = _claim(db_session)
    session = DrillSession(id=1, title="测试")
    db_session.add(session)
    db_session.commit()

    plan = DrillPlan(
        question="为什么用混合召回？",
        intent="验证技术取舍",
        required_evidence=["说清分工", "说明本人范围"],
        followup_triggers=["只说名词"],
        stop_condition="证据齐了就结束",
    )
    contract = open_contract(session, record, plan)
    assert contract.claim_id == record.id
    assert contract.claim_title == record.title
    assert contract.question == plan.question
    assert contract.required_evidence == plan.required_evidence
    assert contract.followup_triggers == plan.followup_triggers
    assert contract.stop_condition == plan.stop_condition
    assert contract.status == EVIDENCE_NOT_COVERED
    # 契约一落库，会话就该认为"已经开始了这道题"。
    assert session.current_index == 1
    db_session.rollback()
