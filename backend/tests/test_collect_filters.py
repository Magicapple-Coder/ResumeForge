"""采集条件本地筛选的判据测试。

这一块的风险不在代码复杂度，而在**方向**：用户填的是**自己的条件**，而岗位上的
`jobDegree` 是**岗位要求的最低学历**。方向写反了不会报错，只会悄悄把该留的岗位筛掉、
把不该留的留下——所以这里的用例是逐条钉语义的。

另一条同样重要的：**判断不了就保留**。字段缺失时宁可让用户多看到几条，也不能丢掉他真正
想要的那条；但必须把"没判断成"如实报出来（``undecided`` / ``unapplied``）。
"""
import pytest

from app.services.apply.collect_filters import (
    education_level,
    evaluate_filters,
    number_range,
    ranges_overlap,
    salary_band,
)


# ===== 学历档位 =====


@pytest.mark.parametrize(
    ("text", "level"),
    [
        ("本科", 4),
        ("大学本科", 4),
        ("学士", 4),
        ("大专", 3),
        ("专科", 3),
        ("大专及以上", 3),
        ("硕士", 5),
        ("研究生", 5),
        ("博士", 6),
        ("高中/中专", 2),
        ("初中及以下", 1),
        # 「不限」是**确定的**答案（谁都能投），档位 0；认不出才是 None。两者不能混。
        ("学历不限", 0),
        ("不限", 0),
        ("无要求", 0),
        ("", None),
        ("管培生", None),
    ],
)
def test_education_level(text, level):
    assert education_level(text) == level


# ===== 经验 / 数值区间 =====


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3-5年", (3.0, 5.0)),
        ("3-5 年", (3.0, 5.0)),
        ("1年以内", (0.0, 1.0)),
        ("3年以上", (3.0, float("inf"))),
        ("5年", (5.0, 5.0)),
        ("经验不限", (0.0, float("inf"))),
        ("应届生", (0.0, 1.0)),
        ("在校/应届", (0.0, 1.0)),
        ("", None),
        ("面议", None),
    ],
)
def test_number_range(text, expected):
    assert number_range(text) == expected


def test_ranges_overlap_includes_the_endpoint():
    """含端点：岗位要求 3-5 年、我有 5 年，是重叠的。"""
    assert ranges_overlap((3.0, 5.0), (5.0, 10.0)) is True
    assert ranges_overlap((1.0, 3.0), (3.0, 5.0)) is True
    assert ranges_overlap((0.0, 1.0), (3.0, 5.0)) is False


def test_salary_band_ignores_daily_wages():
    """日薪与"期望月薪"不是一个单位——返回 None 交给调用方按"判断不了"处理。"""
    assert salary_band({"salary_low": 20000, "salary_high": 30000}) == (20000.0, 30000.0)
    assert salary_band({"salary_low": 300, "salary_high": 500}) is None
    assert salary_band({}) is None
    assert salary_band({"salary_low": None, "salary_high": None}) is None


# ===== 组合判据 =====


def test_education_direction_is_job_requirement_at_most_my_level():
    """**方向**：岗位要求的学历**高于**我的学历 → 筛掉；低于或持平 → 保留。

    写反了不会报错，只会把投得了的岗位筛掉、把投不了的留下。
    """
    # 我是本科（4）：要求硕士(5)/博士(6) 的投不了
    assert evaluate_filters(education="本科", extra={"degree": "硕士"}).keep is False
    assert evaluate_filters(education="本科", extra={"degree": "博士"}).keep is False
    # 要求大专(3)/本科(4) 的可以投
    assert evaluate_filters(education="本科", extra={"degree": "大专"}).keep is True
    assert evaluate_filters(education="本科", extra={"degree": "本科"}).keep is True
    # 岗位不限学历 → 当然可以投
    assert evaluate_filters(education="本科", extra={"degree": "学历不限"}).keep is True


def test_education_rejection_names_the_condition():
    decision = evaluate_filters(education="本科", extra={"degree": "硕士"})

    assert decision.rejected_by == ("学历",)
    assert decision.undecided == ()


def test_missing_job_fields_keep_the_job_but_are_reported():
    """岗位没给字段 → **保留**，但如实计入 undecided（不能假装筛过了）。"""
    decision = evaluate_filters(education="本科", experience="3-5年", extra={})

    assert decision.keep is True
    assert decision.undecided == ("学历", "经验")
    assert decision.decided is False


def test_experience_uses_overlap():
    # 我 3 年：岗位要求 5-10 年 → 不重叠 → 筛掉
    assert evaluate_filters(experience="3年", extra={"experience": "5-10年"}).keep is False
    # 我 3-5 年：岗位要求 5-10 年 → 在 5 处重叠 → 保留
    assert evaluate_filters(experience="3-5年", extra={"experience": "5-10年"}).keep is True
    # 岗位经验不限 → 保留
    assert evaluate_filters(experience="3-5年", extra={"experience": "经验不限"}).keep is True


def test_salary_keeps_jobs_that_can_reach_my_minimum():
    # 期望 ≥20K：岗位 15-25K 能达到 → 保留
    assert evaluate_filters(salary_min=20, extra={"salary_low": 15000, "salary_high": 25000}).keep
    # 期望 ≥20K：岗位 10-12K 的上限都不到 → 筛掉
    assert not evaluate_filters(
        salary_min=20, extra={"salary_low": 10000, "salary_high": 12000}
    ).keep


def test_unparsable_user_input_is_reported_as_unapplied():
    """用户填了读不懂的条件时必须报出来——否则他以为筛过了，实际这条筛选根本没执行。

    这正是本项目反复出现的"静默失效"：界面标着生效，代码里什么也没做。
    """
    decision = evaluate_filters(education="管培生", experience="看情况", extra={})

    assert decision.keep is True
    assert decision.unapplied == ("学历", "经验")


def test_filling_unlimited_is_not_treated_as_unapplied():
    """「不限」是用户能填的合法值（等于不筛），不该报成"没被采纳"。"""
    decision = evaluate_filters(education="不限", experience="经验不限", extra={})

    assert decision.unapplied == ()
    assert decision.undecided == ()
    assert decision.keep is True


def test_no_conditions_means_everything_is_kept():
    decision = evaluate_filters(extra={})

    assert decision.keep is True
    assert decision.rejected_by == ()
    assert decision.decided is True


def test_all_three_conditions_are_evaluated_together():
    decision = evaluate_filters(
        salary_min=20,
        experience="1-2年",
        education="本科",
        extra={"degree": "硕士", "experience": "5-10年", "salary_low": 8000, "salary_high": 12000},
    )

    # 三条都不满足，但每条都会被记下来（用户能看出是"哪几条"把他筛掉的）。
    assert decision.keep is False
    assert set(decision.rejected_by) == {"学历", "经验", "薪资"}


# ===== 岗位类型（2026-09-20 真实实测的接口编码：0=全职/社招、4=实习、5=校招、6=兼职）=====


@pytest.mark.parametrize(
    ("job_type", "code", "kept"),
    [
        ("实习", 4, True),
        ("实习", 0, False),  # 全职岗混进结果时被本地筛选拦住
        ("社招", 0, True),
        ("社招", 4, False),
        ("校招", 5, True),
        ("校招", 0, False),
    ],
)
def test_job_type_filters_by_verified_code(job_type, code, kept):
    decision = evaluate_filters(job_type=job_type, extra={"job_type_code": code})

    assert decision.keep is kept
    if not kept:
        assert decision.rejected_by == ("岗位类型",)
    else:
        assert decision.undecided == ()


def test_job_type_missing_code_is_kept_and_counted():
    """DOM 兜底路径没有编码字段：判断不了就保留，但要如实计数——绝不凭标题猜类型。"""
    decision = evaluate_filters(job_type="实习", extra={})

    assert decision.keep is True
    assert decision.undecided == ("岗位类型",)


def test_unknown_job_type_word_is_reported_as_unapplied():
    decision = evaluate_filters(job_type="外包", extra={"job_type_code": 0})

    assert decision.keep is True
    assert decision.unapplied == ("岗位类型",)


def test_job_type_with_other_conditions_together():
    decision = evaluate_filters(
        salary_min=20,
        education="本科",
        job_type="实习",
        extra={"job_type_code": 4, "salary_low": 200, "salary_high": 400, "degree": "本科"},
    )

    # 薪资：日薪（≤3000）判断不了 → 保留并计数；岗位类型匹配 → 留。
    assert decision.keep is True
    assert decision.undecided == ("薪资",)
