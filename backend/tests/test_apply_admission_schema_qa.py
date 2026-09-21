"""对抗性测试：准入闸门五分支、未知结论的保守处理、禁百分比 schema。

产品硬要求（P0-2 / P0-3 / US-2）：
- 五类状态到准入的映射只能有一处权威；
- 未知 / 空结论**绝不能默认放行**，必须保守归入"需确认"；
- 匹配结果 schema 必须挡得住任何百分比 / 评分字段（``extra="forbid"``）。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.apply import (
    ADMISSION_ALLOW,
    ADMISSION_BLOCK,
    ADMISSION_NEEDS_CONFIRM,
    HARD_GATE_MET,
    HARD_GATE_UNKNOWN,
    HARD_GATE_UNMET,
    admission_of,
    requires_confirmation,
)
from app.models.job import Job
from app.schemas.apply import ApplyQueueAddRequest
from app.schemas.job_match import JobMatchResult, MatchCondition
from app.services.job.job_match import (
    finalize_match_result,
    local_match_result,
    parse_match_result,
    validate_evidence,
)
from app.services.llm.base import LLMError


def _condition(label: str, status: str, evidence: str = "", quote: str = "") -> MatchCondition:
    return MatchCondition(label=label, status=status, evidence=evidence, jd_quote=quote)


# ===== 准入闸门：五个分支 =====


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("matched", ADMISSION_ALLOW),
        ("expression_gap", ADMISSION_ALLOW),
        ("evidence_insufficient", ADMISSION_NEEDS_CONFIRM),
        ("to_confirm", ADMISSION_NEEDS_CONFIRM),
        ("real_gap", ADMISSION_BLOCK),
    ],
)
def test_admission_gate_five_branches(status, expected):
    assert admission_of(status) == expected


def test_unknown_empty_or_none_admission_is_conservative():
    """未知 / 空 / None 一律归入"需确认"，绝不默认放行。"""
    for weird in ("", "score", "82%", "MATCHED", None, 123, "unknown_status"):
        assert admission_of(weird) == ADMISSION_NEEDS_CONFIRM
        assert requires_confirmation(weird) is True


# ===== finalize：不信任模型自报的汇总 =====


def test_finalize_forces_block_even_if_model_claims_allow():
    """模型自报 admission=allow，但含一条真实缺口 → 必须被改判为 block。"""
    result = JobMatchResult(
        hard_conditions=[_condition("学历", "real_gap")],
        core_abilities=[_condition("Python", "matched")],
        admission="allow",
        hard_gate="met",
    )
    fixed = finalize_match_result(result)
    assert fixed.admission == ADMISSION_BLOCK
    assert fixed.hard_gate == HARD_GATE_UNMET


def test_finalize_marks_empty_result_as_needs_confirm():
    """没有任何条目的结果不能算"可投"，必须保守为需确认。"""
    fixed = finalize_match_result(JobMatchResult())
    assert fixed.admission == ADMISSION_NEEDS_CONFIRM
    assert fixed.hard_gate == HARD_GATE_UNKNOWN


def test_finalize_hard_gate_met_only_when_all_hard_conditions_matched():
    fixed = finalize_match_result(
        JobMatchResult(hard_conditions=[_condition("本科", "matched"), _condition("经验", "matched")])
    )
    assert fixed.hard_gate == HARD_GATE_MET
    assert fixed.admission == ADMISSION_ALLOW

    # 含一条表达缺口：硬门槛不再判定为 met（保守），但准入仍可自动投。
    mixed = finalize_match_result(
        JobMatchResult(
            hard_conditions=[_condition("本科", "matched"), _condition("经验", "expression_gap")]
        )
    )
    assert mixed.hard_gate == HARD_GATE_UNKNOWN
    assert mixed.admission == ADMISSION_ALLOW


# ===== schema：禁百分比 / 评分 =====


def test_match_condition_rejects_unknown_status():
    with pytest.raises(ValidationError):
        MatchCondition(label="Python", status="score_82")


def test_match_condition_rejects_extra_score_field():
    with pytest.raises(ValidationError):
        MatchCondition.model_validate({"label": "Python", "status": "matched", "score": 0.82})


def test_match_result_rejects_percentage_like_fields():
    for payload in (
        {"match_percent": 82},
        {"score": 82},
        {"匹配度": "82%"},
        {"percentage": 0.82},
    ):
        with pytest.raises(ValidationError):
            JobMatchResult.model_validate(payload)


def test_parse_match_result_rejects_a_score_in_the_model_output():
    raw = (
        '{"hard_conditions": [{"label": "本科", "status": "matched", "score": 0.9}],'
        ' "admission": "allow"}'
    )
    with pytest.raises(LLMError):
        parse_match_result(raw)


def test_parse_match_result_rejects_a_percent_status():
    raw = '{"hard_conditions": [{"label": "本科", "status": "82%"}], "admission": "allow"}'
    with pytest.raises(LLMError):
        parse_match_result(raw)


def test_parse_match_result_accepts_a_valid_result_and_finalizes():
    raw = (
        '{"hard_conditions": [{"label": "本科", "status": "matched", "evidence": "资料中未提供"}],'
        ' "core_abilities": [], "bonus_items": [], "admission": "allow", "advice": "建议投递"}'
    )
    result = parse_match_result(raw)
    assert result.hard_conditions[0].status == "matched"
    fixed = finalize_match_result(result)
    assert fixed.admission == ADMISSION_ALLOW


# ===== 证据锚定：防虚构 =====


def test_validate_evidence_rejects_evidence_not_present_in_sources():
    result = JobMatchResult(
        core_abilities=[_condition("精通 Rust", "matched", evidence="三年 Rust 生产经验")]
    )
    with pytest.raises(LLMError):
        validate_evidence(result, jd_source="熟悉 Python", personal_source="简历：Python 后端")


def test_validate_evidence_accepts_no_evidence_hint():
    result = JobMatchResult(
        bonus_items=[_condition("开源经历", "evidence_insufficient", evidence="资料中未提供")]
    )
    # 不抛异常即通过。
    validate_evidence(result, jd_source="有开源经历加分", personal_source="简历：Python 后端")


# ===== 未配置模型：本地降级而非 500 =====


def test_local_fallback_is_to_confirm_and_warns_in_chinese():
    payload = {
        "title": "后端开发",
        "description": "负责服务端开发\n熟悉 Python 与数据库",
        "requirements": "",
        "additional_info": "",
    }
    result = local_match_result(payload)
    assert result.hard_gate == HARD_GATE_UNKNOWN
    assert result.admission == ADMISSION_NEEDS_CONFIRM
    assert result.hard_conditions, "应当从 JD 里拆出待确认条目"
    assert all(item.status == "to_confirm" for item in result.hard_conditions)
    assert any("未配置大模型" in note for note in result.notes)


# ===== 队列准入：真实缺口拦截 + 未分析确认 =====


def _persist(db, job: Job, result: JobMatchResult):
    from app.services.apply import apply_service

    return apply_service.persist_match(db, job, finalize_match_result(result))


def _make_job(db, title="后端开发", company="A公司") -> Job:
    job = Job(title=title, company=company, source="BOSS直聘", source_url=f"u/{title}")
    db.add(job)
    db.commit()
    return job


def test_queue_blocks_a_real_gap_until_confirmed(db_session):
    from app.services.apply import apply_service

    job = _make_job(db_session)
    _persist(db_session, job, JobMatchResult(hard_conditions=[_condition("五年经验", "real_gap")]))

    with pytest.raises(apply_service.ApplyConflict) as exc:
        apply_service.add_to_queue(
            db_session, ApplyQueueAddRequest(items=[{"job_id": job.id}])
        )
    # 冲突信息里必须带上缺口项，供前端逐条展示。
    assert exc.value.detail.get("gaps") == ["五年经验"]

    created = apply_service.add_to_queue(
        db_session,
        ApplyQueueAddRequest(items=[{"job_id": job.id, "confirm_real_gap": True}]),
    )
    assert len(created) == 1


def test_queue_requires_confirmation_for_unanalyzed_job(db_session):
    from app.services.apply import apply_service

    job = _make_job(db_session, title="未分析岗")
    with pytest.raises(apply_service.ApplyConflict) as exc:
        apply_service.add_to_queue(
            db_session, ApplyQueueAddRequest(items=[{"job_id": job.id}])
        )
    assert exc.value.detail.get("unanalyzed") is True

    created = apply_service.add_to_queue(
        db_session,
        ApplyQueueAddRequest(items=[{"job_id": job.id, "confirm_unanalyzed": True}]),
    )
    assert len(created) == 1


def test_queue_allows_matched_and_expression_gap_without_confirmation(db_session):
    from app.services.apply import apply_service

    matched = _make_job(db_session, title="匹配岗")
    _persist(db_session, matched, JobMatchResult(hard_conditions=[_condition("本科", "matched")]))
    gap = _make_job(db_session, title="表达缺口岗")
    _persist(db_session, gap, JobMatchResult(core_abilities=[_condition("Python", "expression_gap")]))

    created = apply_service.add_to_queue(
        db_session,
        ApplyQueueAddRequest(items=[{"job_id": matched.id}, {"job_id": gap.id}]),
    )
    assert {item.job_id for item in created} == {matched.id, gap.id}


def test_queue_needs_confirmation_item_is_flagged(db_session):
    from app.services.apply import apply_service

    job = _make_job(db_session, title="待确认岗")
    _persist(db_session, job, JobMatchResult(core_abilities=[_condition("K8s", "to_confirm")]))

    created = apply_service.add_to_queue(
        db_session, ApplyQueueAddRequest(items=[{"job_id": job.id}])
    )
    # needs_confirm 级别的岗位允许入队（与"真实缺口"不同），但必须标记为需逐条确认。
    assert created[0].requires_confirm is True
    assert created[0].admission == ADMISSION_NEEDS_CONFIRM


def test_queue_rejects_duplicate_job(db_session):
    from app.services.apply import apply_service

    job = _make_job(db_session, title="重复岗")
    _persist(db_session, job, JobMatchResult(hard_conditions=[_condition("本科", "matched")]))
    apply_service.add_to_queue(
        db_session, ApplyQueueAddRequest(items=[{"job_id": job.id}])
    )
    with pytest.raises(apply_service.ApplyConflict):
        apply_service.add_to_queue(
            db_session, ApplyQueueAddRequest(items=[{"job_id": job.id}])
        )


# ===== 第二轮对抗：换一批"脏结论"形态，确认防御是真补上了 =====


def _dirty_match(db_session, job: Job, *, result, hard_gate: object, requires_confirm: bool = False):
    """绕过 ``persist_match`` 直接落一条"脏"匹配结论行，模拟历史数据 / 未来回归产物。"""
    from app.models.apply import JobMatchAnalysis

    row = JobMatchAnalysis(
        job_id=job.id,
        job_title=job.title,
        company=job.company,
        result=result,
        hard_gate=hard_gate,
        requires_confirm=requires_confirm,
        model="",
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.mark.parametrize(
    ("result", "hard_gate", "label"),
    [
        (None, "unknown", "result=None"),
        ([], "unknown", "result=[] 非 dict"),
        ("plain string", "unknown", "result 是字符串"),
        ({}, "weird", "hard_gate 未知取值"),
        ({}, "", "hard_gate 空串"),
        ({}, None, "hard_gate=None"),
        ({}, "unknown", "空结果 + 未标记（第一轮那条）"),
        ({}, "met", "空结果但 hard_gate=met（易被误判放行）"),
        ({"admission": "score"}, "unknown", "非法 admission 取值"),
        ({"admission": "82%"}, "unknown", "admission 是百分比"),
        ({"hard_conditions": [{"label": "本科", "status": "what?"}]}, "unknown", "条件状态未知"),
        ({"hard_conditions": [{"label": "本科"}]}, "unknown", "条件状态字段缺失"),
        ({"hard_conditions": [{"label": "本科", "status": "matched"}], "admission": None}, "unknown", "admission=None"),
    ],
)
def test_dirty_match_conclusions_never_default_allow(db_session, result, hard_gate, label):
    """任何读不出可用结论的脏行，都必须标记为需逐条确认，绝不默认放行自动投递。"""
    from app.services.apply import apply_service

    job = _make_job(db_session, title=f"脏结论-{label}"[:40])
    _dirty_match(db_session, job, result=result, hard_gate=hard_gate, requires_confirm=False)

    created = apply_service.add_to_queue(
        db_session, ApplyQueueAddRequest(items=[{"job_id": job.id}])
    )
    assert len(created) == 1
    assert created[0].requires_confirm is True, f"脏结论被默认放行：{label}"
    assert created[0].admission != ADMISSION_ALLOW, f"脏结论被判为可自动投递：{label}"


def test_dirty_match_does_not_get_blocked_as_real_gap(db_session):
    """空/脏结论是"需确认"而非"直接不投"：入队不抛 409，但必须带 requires_confirm。"""
    from app.services.apply import apply_service

    job = _make_job(db_session, title="脏但不阻断岗")
    _dirty_match(db_session, job, result={}, hard_gate="unknown", requires_confirm=False)
    created = apply_service.add_to_queue(
        db_session, ApplyQueueAddRequest(items=[{"job_id": job.id}])
    )
    assert created[0].requires_confirm is True


def test_api_queue_never_default_allows_dirty_conclusions(client, db_session):
    """绕过 service 直接从 API 投递（POST /api/apply/queue）：脏结论同样不得默认放行。"""
    cases = [
        (None, "unknown"),
        ([], "unknown"),
        ("plain string", "unknown"),
        ({}, "weird"),
        ({}, "met"),
        ({"admission": "82%"}, "unknown"),
        ({"hard_conditions": [{"label": "本科", "status": "???"}]}, "unknown"),
    ]
    for index, (result, hard_gate) in enumerate(cases):
        job = _make_job(db_session, title=f"API脏结论{index}")
        _dirty_match(db_session, job, result=result, hard_gate=hard_gate, requires_confirm=False)

        response = client.post("/api/apply/queue", json={"items": [{"job_id": job.id}]})
        assert response.status_code == 200, f"case={index} result={result!r} gate={hard_gate!r}"
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]["requires_confirm"] is True, f"API 放行了脏结论：case={index}"
        assert payload[0]["admission"] != ADMISSION_ALLOW


def test_api_queue_response_for_dirty_row_reports_needs_confirm(client, db_session):
    """确认 API 输出层给出的就是"需确认"，而不是 None 让人以为"未分析"。"""
    job = _make_job(db_session, title="API响应形态岗")
    _dirty_match(db_session, job, result={}, hard_gate="unknown", requires_confirm=False)

    payload = client.post("/api/apply/queue", json={"items": [{"job_id": job.id}]}).json()
    # admission 可为 None（读不出可用结论），但 requires_confirm 必须为 True。
    assert payload[0]["requires_confirm"] is True
    assert payload[0]["job_id"] == job.id


# ===== 反向对照：正常结论不受影响 =====


def test_clean_allow_conclusion_is_not_flagged_for_confirmation(db_session):
    """反向对照：干净的可投递结论（matched）不得被新一轮的保守逻辑误标为需确认。"""
    from app.services.apply import apply_service

    job = _make_job(db_session, title="干净匹配岗")
    _persist(db_session, job, JobMatchResult(hard_conditions=[_condition("本科", "matched")]))

    created = apply_service.add_to_queue(
        db_session, ApplyQueueAddRequest(items=[{"job_id": job.id}])
    )
    assert created[0].admission == ADMISSION_ALLOW
    assert created[0].requires_confirm is False
