"""采集条件的本地筛选：**按"我的条件"筛掉我投不了的岗位**。

## 它和「站点筛选栏」是两件事，不要混

2026-09-21 起，采集条件分成**两层**，各有各的语义：

- **站点侧筛选**（``services/sites/boss_filters.py`` + ``BossAdapter.build_search_url``）：
  就是招聘网站筛选栏里的那几格——求职类型 / 薪资待遇 / 工作经验 / 学历要求 / 公司行业 /
  公司规模 / 融资阶段。筛的是**"岗位要求什么"**，网站在搜索时就完成了，更快也更准。
- **本模块**：筛的是**"我的条件够不够得上"**。用户填的是**自己的**学历 / 经验 / 期望薪资，
  用来丢掉自己投不了的岗位（岗位要求「硕士」而我是「本科」→ 投不了 → 筛掉）。

两层可以同时用，互不替代。

## 为什么这一层仍然必要

站点筛选栏筛的是单一岗位的某个字段，而"我够不够得上"这个判断**站点没有对应的筛选项**：
它需要拿用户自身条件和岗位要求做比较（方向性），而站点只提供"岗位要求等于某档"。

另外，这条本地路径是**站点参数失效时的兜底**：历史上 ``jobType=4`` 就不是有效参数，
站点侧的过滤会静默失效，本地这一层仍能按接口编码把不符合的筛掉。

三条贯穿全模块的原则：

1. **判断不了就保留。** 字段缺失、格式不认识时**不排除**该岗位——宁可让用户多看到几条，
   也不能悄悄丢掉他真正想要的那条。这类情况会单独计数（``undecided``）并如实上报。
2. **不猜。** 只做能说清依据的判断，不靠"看起来像"。
3. **方向要对。** 用户填的是**自己的条件**，不是岗位的条件。岗位要求高于用户水平才该筛掉
   （岗位要求「硕士」而用户是「本科」→ 投不了 → 筛掉；反过来则保留）。
4. **只保留有重叠的区间。** 经验/薪资按区间重叠判断，而不是"必须完全落在里面"。

本模块是纯函数（无网络、无数据库、无浏览器），因此可以逐条离线测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 学历档位。用户填的是**自己的学历**，岗位上的 `jobDegree` 是**岗位要求的最低学历**；
# 因此判据是"岗位要求 ≤ 我的学历"。数值越大表示学历越高。
_EDUCATION_LEVELS: tuple[tuple[str, int], ...] = (
    ("博士后", 7),
    ("博士", 6),
    ("硕士", 5),
    ("研究生", 5),
    ("emba", 5),
    ("mba", 5),
    ("本科", 4),
    ("学士", 4),
    ("大学", 4),
    ("大专", 3),
    ("专科", 3),
    ("高职", 3),
    ("中专", 2),
    ("中技", 2),
    ("高中", 2),
    ("初中", 1),
    ("小学", 1),
)
# 「不限 / 无要求」这类写法当作 0 档：任何学历都满足。
_EDUCATION_UNLIMITED = ("不限", "无要求", "无学历要求", "学历不限", "不要求")

# 「不限」「以上」「以内」等修饰词
_RANGE_UNLIMITED = ("不限", "无要求", "经验不限", "不要求", "均可")

# 从"3-5年" / "3年以上" / "1年以内" / "5年" 里把区间抠出来。
_NUMBER = r"(\d+(?:\.\d+)?)"
_RANGE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(rf"{_NUMBER}\s*[-~–—至]\s*{_NUMBER}"), "range"),
    (re.compile(rf"{_NUMBER}\s*年?\s*(?:及)?以上"), "at_least"),
    (re.compile(rf"{_NUMBER}\s*年?\s*(?:及)?以内|{_NUMBER}\s*年?以下"), "at_most"),
    (re.compile(rf"^{_NUMBER}\s*年?$"), "exact"),
)

NumberRange = tuple[float, float]
_INFINITY = float("inf")


def education_level(text: Any) -> int | None:
    """把一段学历文本折成档位；认不出返回 ``None``（**不是** 0——那是"不限"的意思）。

    取文本里**最高**的那一档：「大专及以上」命中「大专」，
    「高中/中专」命中两者（同档），「本科」只命中一档。
    """
    value = str(text or "").strip().lower()
    if not value:
        return None
    if any(word in value for word in _EDUCATION_UNLIMITED):
        return 0
    levels = [level for word, level in _EDUCATION_LEVELS if word in value]
    return max(levels) if levels else None


def number_range(text: Any) -> NumberRange | None:
    """把"3-5年" / "3年以上" / "1年以内" / "5年"折成区间；认不出返回 ``None``。

    「不限」返回 ``(0, inf)``——它是个**确定的**答案（都不限），不是"认不出"。
    """
    value = str(text or "").strip()
    if not value:
        return None
    if any(word in value for word in _RANGE_UNLIMITED):
        return (0.0, _INFINITY)
    if "应届" in value or "在校" in value:
        # 应届/在校在招聘文案里普遍等价于"1 年以内"。
        return (0.0, 1.0)
    for pattern, kind in _RANGE_PATTERNS:
        match = pattern.search(value)
        if match is None:
            continue
        if kind == "range":
            low, high = float(match.group(1)), float(match.group(2))
            return (min(low, high), max(low, high))
        if kind == "at_least":
            return (float(match.group(1)), _INFINITY)
        if kind == "at_most":
            # 这条模式里有两个可选的捕获组，取非空的那个。
            bound = next(
                (float(group) for group in match.groups() if group is not None),
                0.0,
            )
            return (0.0, bound)
        return (float(match.group(1)), float(match.group(1)))
    return None


def ranges_overlap(left: NumberRange, right: NumberRange) -> bool:
    """两个区间是否有重叠（**含端点**：岗位要求 3-5 年、我有 5 年 → 重叠）。"""
    return left[0] <= right[1] and right[0] <= left[1]


def salary_band(extra: dict[str, Any]) -> NumberRange | None:
    """从接口字段里取薪资区间（元/月）。**日薪不参与判断**（单位不同，比不了）。

    日薪的判据是 ``salary_high`` 明显偏小（BOSS 的日薪在几百元量级），这里用
    ``_DAILY_SALARY_CEILING`` 区分；分不清时返回 ``None``，由调用方按"判断不了"处理。
    """
    low = extra.get("salary_low")
    high = extra.get("salary_high")
    if not isinstance(low, int) or not isinstance(high, int):
        return None
    if low <= 0 and high <= 0:
        return None
    low = low or high
    high = high or low
    if high <= _DAILY_SALARY_CEILING:
        # 日薪：与"我的期望月薪"不是一个单位，判断不了。
        return None
    return (float(low), float(high))


_DAILY_SALARY_CEILING = 3000


# 岗位类型的原始编码（BOSS 接口字段 `jobType`）与用户可选岗位类型的对应关系。
# 2026-09-20 用真实登录会话实测（`/wapi/zpgeek/search/joblist.json` 响应 + 三个筛选参数
# 各返回 15 条逐条核对）：0=全职（社招）、4=实习、5=校招（两条校招岗均为 5，且
# `jobExperience="在校/应届"`）、6=兼职；站点官方筛选参数只有 全职=1901 / 兼职=1903 /
# 实习=1902（无校招档，校招是独立专区）。
JOB_TYPE_CODE_FULL_TIME = 0
JOB_TYPE_CODE_INTERNSHIP = 4
JOB_TYPE_CODE_CAMPUS = 5
# 用户岗位类型 → 期望的接口编码；None = 该类型没有可靠判据（不在字典里即如此）。
JOB_TYPE_EXPECTED_CODES: dict[str, int] = {
    "社招": JOB_TYPE_CODE_FULL_TIME,
    "实习": JOB_TYPE_CODE_INTERNSHIP,
    "校招": JOB_TYPE_CODE_CAMPUS,
}


@dataclass(frozen=True)
class FilterDecision:
    """一次筛选的结论。**区分"明确不符合"、"判断不了"与"我的条件没被用上"**。

    这三者的处理完全不同，混在一起报就是又一次静默失效：
    ``rejected_by`` 是筛掉的正当理由；``undecided`` 是岗位没给字段（已保留）；
    ``unapplied`` 是**用户自己填的条件没被采纳**（例如填了「管培生」这种认不出的学历）——
    这种情况必须报出来，否则用户以为筛过了，实际这条筛选根本没执行。
    """

    keep: bool
    # 明确判定为不符合的条件名（如 ("学历",)）；用于告诉用户"筛掉它是按哪一条"。
    rejected_by: tuple[str, ...] = ()
    # 因为岗位没给这个字段（或格式认不出）而**没能判断**的条件名；岗位已保留。
    undecided: tuple[str, ...] = ()
    # 用户填了、但认不出因而没有执行的条件名。
    unapplied: tuple[str, ...] = ()

    @property
    def decided(self) -> bool:
        return not self.undecided


def evaluate_filters(
    *,
    salary_min: int | None = None,
    experience: str = "",
    education: str = "",
    job_type: str = "",
    extra: dict[str, Any] | None = None,
) -> FilterDecision:
    """按用户填的条件判断这条岗位该不该留。

    - **学历**：岗位要求 ≤ 用户学历才留（岗位要求「硕士」而用户「本科」→ 筛掉）。
      岗位写「学历不限」按满足处理。
    - **经验**：岗位要求的区间与用户的区间**有重叠**才留。
    - **薪资**：岗位**能达到**用户期望的下限才留（岗位 10-20K、期望 ≥15K → 有交集 → 留；
      岗位 10-12K、期望 ≥15K → 筛掉）。比较的是月薪，日薪岗位判断不了。
    - **岗位类型**：按接口返回的岗位类型编码判定（``extra["job_type_code"]``，编码表见
      ``JOB_TYPE_EXPECTED_CODES``）。接口没给这个字段（DOM 兜底路径）时**保留**并计入
      "未能判断"——绝不凭标题猜类型，那是"看起来像"式的误杀。
    """
    payload = extra or {}
    rejected: list[str] = []
    undecided: list[str] = []
    unapplied: list[str] = []

    if str(education or "").strip():
        wanted_education = education_level(education)
        if wanted_education is None:
            # 用户填了读不懂的学历词：**不能假装筛过了**。
            unapplied.append("学历")
        elif wanted_education > 0:
            job_education = education_level(payload.get("degree"))
            if job_education is None:
                undecided.append("学历")
            elif job_education > wanted_education:
                rejected.append("学历")

    if str(experience or "").strip():
        wanted_experience = number_range(experience)
        if wanted_experience is None:
            unapplied.append("经验")
        elif wanted_experience != (0.0, _INFINITY):
            job_experience = number_range(payload.get("experience"))
            if job_experience is None:
                undecided.append("经验")
            elif not ranges_overlap(job_experience, wanted_experience):
                rejected.append("经验")

    if salary_min is not None and salary_min > 0:
        band = salary_band(payload)
        if band is None:
            undecided.append("薪资")
        elif band[1] < salary_min * 1000:
            # 岗位的**上限**都到不了我的期望下限 → 没得谈。
            rejected.append("薪资")

    wanted_job_type = str(job_type or "").strip()
    if wanted_job_type:
        expected_code = JOB_TYPE_EXPECTED_CODES.get(wanted_job_type)
        if expected_code is None:
            # 认不出的岗位类型词：如实报出来，绝不假装筛过了。
            unapplied.append("岗位类型")
        else:
            job_type_code = payload.get("job_type_code")
            if not isinstance(job_type_code, int) or job_type_code < 0:
                # 接口没给编码（DOM 路径 / 结构变化）→ 判断不了 → 保留并计数。
                undecided.append("岗位类型")
            elif job_type_code != expected_code:
                rejected.append("岗位类型")

    return FilterDecision(
        keep=not rejected,
        rejected_by=tuple(rejected),
        undecided=tuple(undecided),
        unapplied=tuple(unapplied),
    )


@dataclass
class FilterTally:
    """一次采集里筛选的汇总（写给界面看）。"""

    filtered: int = 0
    reasons: set[str] = field(default_factory=set)
    undecided: set[str] = field(default_factory=set)
    unapplied: set[str] = field(default_factory=set)
    undecided_count: int = 0


__all__ = [
    "JOB_TYPE_EXPECTED_CODES",
    "FilterDecision",
    "FilterTally",
    "education_level",
    "evaluate_filters",
    "number_range",
    "ranges_overlap",
    "salary_band",
]
