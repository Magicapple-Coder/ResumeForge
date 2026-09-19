"""``match_scoring`` 参考分的纯函数测试。

重点钉住两条性质：

1. 参考分是**派生值**：调用后不改变输入 ``JobMatchResult`` 的五类结论与准入结论；
2. 五维常量表结构正确（5 维、权重和为 1、每维都返回 0-100 分）。
"""
from app.schemas.job_match import JobMatchResult, MatchCondition
from app.services.match_scoring import MATCH_SCORE_DIMENSIONS, score_match_result


def _by_key(score):
    return {dimension.key: dimension for dimension in score.dimensions}


def test_dimensions_are_five_and_weights_sum_to_one():
    assert len(MATCH_SCORE_DIMENSIONS) == 5
    assert abs(sum(spec.weight for spec in MATCH_SCORE_DIMENSIONS) - 1.0) < 1e-9


def test_score_returns_five_dimensions_and_disclaimer():
    score = score_match_result(JobMatchResult(), {}, "", "")
    assert 0 <= score.score <= 100
    assert len(score.dimensions) == 5
    assert score.disclaimer


def test_hard_gate_met_vs_unmet():
    met = JobMatchResult(
        hard_conditions=[MatchCondition(label="学历", status="matched")],
        hard_gate="met",
    )
    unmet = JobMatchResult(
        hard_conditions=[MatchCondition(label="学历", status="real_gap")],
        hard_gate="unmet",
    )
    assert _by_key(score_match_result(met, {}, "", ""))["hard_gate"].score == 100
    assert _by_key(score_match_result(unmet, {}, "", ""))["hard_gate"].score == 0


def test_scoring_does_not_change_admission_or_hard_gate():
    """参考分绝不参与、也绝不改变五类结论与准入闸门。"""
    result = JobMatchResult(
        hard_conditions=[MatchCondition(label="硬门槛", status="real_gap")],
        hard_gate="unmet",
        admission="block",
    )
    score_match_result(
        result,
        {"requirements": "需要 3 年经验，熟悉 Python"},
        "",
        "",
    )
    assert result.admission == "block"
    assert result.hard_gate == "unmet"
    # 该结果里唯一的硬条件仍是 real_gap，五类结论没有被评分逻辑改写。
    assert result.hard_conditions[0].status == "real_gap"


def test_jd_keyword_coverage_scores_partial_overlap():
    result = JobMatchResult()
    score = score_match_result(
        result,
        {"requirements": "熟悉 Python 与 机器学习"},
        "",
        "我熟悉 Python",
    )
    coverage = _by_key(score)["jd_keyword_coverage"]
    # 命中一半关键词：既不是满分也不是零分。
    assert 0 < coverage.score < 100


def test_neutral_score_when_no_signals():
    """没有任何信号时给出中性分，而不是误报成 0 分（不匹配）。"""
    score = score_match_result(JobMatchResult(), {}, "", "")
    assert score.score == 50
