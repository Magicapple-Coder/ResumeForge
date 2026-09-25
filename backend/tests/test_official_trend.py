"""趋势离群：这次条数与这家公司近期相比算不算异常。

三组用例各有明确目的：

- **算法**：中位数基线、绝对差额下限、基线为 0 的边界；
- **测量的有效性**：被阻断/停止/失败的那些**不是**测量，混进基线会把真实掉量掩盖掉；
- **措辞**：它必须说清"这不一定是漏抓"——条数下降有两个来源，只看条数分不出来。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.models.official import (
    BLOCK_FORBIDDEN,
    BLOCK_NONE,
    BLOCK_RATE_LIMIT,
    RUN_DONE,
    RUN_FAILED,
    RUN_RUNNING,
    RUN_STOPPED,
)
from app.services.sites.official.trend import (
    MIN_HISTORY,
    TREND_DROPPED,
    TREND_INSUFFICIENT,
    TREND_JUMPED,
    TREND_STABLE,
    compare_trend,
    is_measurement,
    measured_counts,
)


@dataclass
class FakeRun:
    status: str = RUN_DONE
    collected: int = 0
    blocks: list[str] = field(default_factory=lambda: [BLOCK_NONE])


# ===== 算法 =====


def test_insufficient_history_says_so_instead_of_guessing():
    """历史不足时**说不了**，而不是当成"正常"。它是三态里的"不知道"。"""
    for prior in ([], [10], [10, 12]):
        signal = compare_trend(list(prior), latest=3)
        assert signal.state == TREND_INSUFFICIENT, prior
        assert signal.baseline is None
        assert str(MIN_HISTORY) in signal.detail


def test_stable_when_close_to_the_baseline():
    signal = compare_trend([40, 42, 38], latest=39)
    assert signal.state == TREND_STABLE
    assert signal.baseline == 40
    assert signal.latest == 39


def test_dropped_when_far_below_the_baseline():
    signal = compare_trend([40, 42, 38], latest=3)
    assert signal.state == TREND_DROPPED
    assert signal.baseline == 40


def test_jumped_when_far_above_the_baseline():
    signal = compare_trend([10, 12, 11], latest=60)
    assert signal.state == TREND_JUMPED
    assert signal.baseline == 11


def test_median_beats_mean_for_a_single_low_outlier():
    """**中位数而不是平均数**：一次"只返回了一半"的采集会混进历史，把平均数拽低，
    从而让一次真实的掉量看起来正常——那正是这个模块要发现的东西。

    这里历史里混了一个 5（异常低），中位数仍是 40；而平均数是 31.25，
    用它当基线时 22 条落在 0.6 倍（18.75）之上，**不会报警**。
    """
    prior = [40, 40, 40, 5]

    signal = compare_trend(prior, latest=22)

    assert signal.baseline == 40, "基线取的是中位数"
    assert signal.state == TREND_DROPPED, "真实的掉量不该被一条异常低的记录掩盖"


def test_small_absolute_change_is_not_flagged():
    """**比例在小数上不可靠**：4 条掉到 2 条也是"腰斩"，但那多半只是正常的岗位增减。"""
    signal = compare_trend([4, 5, 4], latest=2)
    assert signal.state == TREND_STABLE


def test_absolute_floor_still_catches_a_real_drop_on_a_small_board():
    """但绝对差额够大时，小盘子的掉量照样要报。"""
    signal = compare_trend([20, 20, 20], latest=2)
    assert signal.state == TREND_DROPPED


def test_baseline_of_zero_makes_any_positive_a_jump():
    """基线是 0：之前每次都抓不到。此时"突然抓到了"是有信息量的。"""
    signal = compare_trend([0, 0, 0], latest=12)
    assert signal.state == TREND_JUMPED
    assert signal.baseline == 0


def test_baseline_of_zero_with_zero_is_stable_not_a_false_alarm():
    signal = compare_trend([0, 0, 0], latest=0)
    assert signal.state == TREND_STABLE
    assert "一直是 0" in signal.detail


@pytest.mark.parametrize("latest", [0, 1, 2])
def test_dropping_to_near_zero_is_flagged(latest):
    signal = compare_trend([50, 48, 52], latest=latest)
    assert signal.state == TREND_DROPPED


# ===== 措辞 =====


def test_drop_message_says_it_is_not_necessarily_a_miss():
    """**最要紧的一条措辞**：条数下降既可能是我们漏抓，也可能是公司真的关掉了岗位。

    只说"少了"会让用户以为工具坏了；只说是工具的问题又会让"公司缩减招聘"被误报成故障。
    """
    signal = compare_trend([40, 42, 38], latest=3)

    assert "不一定是漏抓" in signal.detail
    assert "关掉" in signal.detail


def test_jump_message_offers_both_explanations():
    signal = compare_trend([10, 12, 11], latest=60)
    assert "扩招" in signal.detail
    assert "站点改了返回的内容" in signal.detail


def test_every_state_has_a_label():
    from app.services.sites.official.trend import TREND_LABELS

    for state in (TREND_STABLE, TREND_DROPPED, TREND_JUMPED, TREND_INSUFFICIENT):
        assert TREND_LABELS.get(state), state


# ===== 什么才算一次测量 =====


def test_completed_run_is_a_measurement():
    assert is_measurement(FakeRun()) is True


@pytest.mark.parametrize("status", [RUN_RUNNING, RUN_STOPPED, RUN_FAILED])
def test_unfinished_runs_are_not_measurements(status):
    assert is_measurement(FakeRun(status=status)) is False


def test_blocked_run_is_not_a_measurement():
    """**它的 0 是"我们没拿到"，不是"这家公司没有岗位"。**

    混进基线会把基线越拉越低，最终掩盖掉一次真实的掉量。
    """
    assert is_measurement(FakeRun(collected=0, blocks=[BLOCK_RATE_LIMIT])) is False


def test_robots_refused_run_is_not_a_measurement():
    """被 robots 拒绝也记成"已完成"，但它根本没尝试采集。"""
    assert is_measurement(FakeRun(status=RUN_DONE, collected=0, blocks=[BLOCK_FORBIDDEN])) is False


def test_measured_counts_filters_and_keeps_order():
    runs = [
        FakeRun(collected=10),
        FakeRun(collected=0, blocks=[BLOCK_RATE_LIMIT]),
        FakeRun(collected=12),
        FakeRun(status=RUN_STOPPED, collected=5),
        FakeRun(collected=11),
    ]
    assert measured_counts(runs) == [10, 12, 11]


def test_a_blocked_run_does_not_poison_the_baseline():
    """端到端地看这件事：一次被限流的采集不该把基线拉低到掩盖真实掉量的程度。"""
    history = [FakeRun(collected=40), FakeRun(collected=0, blocks=[BLOCK_RATE_LIMIT]),
               FakeRun(collected=40), FakeRun(collected=42)]

    signal = compare_trend(measured_counts(history), latest=3)

    assert signal.baseline == 40
    assert signal.state == TREND_DROPPED
