"""生成结果的"覆盖度"检查：资料里有、但这份简历里没写的内容。

**为什么要有它**：生成链路里有两道会丢内容的关卡——
1. 岗位相关性筛选（`profile_relevance`）：与岗位关键词没有交集的条目**根本不会**进入
   发给模型的候选资料；
2. 模型自己取舍：同一份候选资料里，它也可能只写与岗位最相关的那几条。

两道关卡都是**有意的设计**（不筛的话，一份简历会塞满与岗位无关的经历）。但它们之前
都是静默的：用户在资料里明明写了项目、台账里也确认了，生成出来却没有——从用户的角度看
这就是"工具把我的内容弄丢了"，而他没有任何办法知道原因，更不知道该怎么办。

这个模块把"丢了什么、为什么丢、怎么办"一次说清。它只做**确定性的集合比对**
（按条目的身份字段：项目名 / 公司名 / 学校名），不做模糊语义判断——宁可少报，也不能
把"写进去了"误报成"没写"。
"""

from __future__ import annotations

import json
from typing import Any

from ...schemas.claim import ClaimDigestOut
from ...schemas.resume import ResumeContent

# 简历字段 ↔ 资料分区的对应关系：
#   (简历上的字段, 资料里的分区, 身份字段, 用户看得见的分区名)
# 身份字段是"这条是不是同一条"的判据（项目名 / 公司名 / 学校名……）。它必须是
# 用户自己填的名字，而不是模型改写过的标题——否则比对就没有意义。
_SECTION_MAP: tuple[tuple[str, str, str, str], ...] = (
    ("projects", "projects", "name", "项目经历"),
    ("experience", "experiences", "company", "实习/工作经历"),
    ("campus_experience", "campus_experiences", "organization", "校园经历"),
    ("awards", "awards", "name", "荣誉奖项"),
    ("education", "educations", "school", "教育经历"),
)

# 一次最多报几条，避免一份资料特别厚的用户收到一面墙的警告。
_MAX_REPORTED = 4


def _entry_names(section: Any, identity_field: str) -> set[str]:
    """取一个分区里所有条目的身份值（去掉空白）。"""
    names: set[str] = set()
    if not isinstance(section, list):
        return names
    for item in section:
        if isinstance(item, dict):
            value = str(item.get(identity_field) or "").strip()
            if value:
                names.add(value)
    return names


def _written_names(resume: ResumeContent, field: str, identity_field: str) -> set[str]:
    section = getattr(resume, field, None) or []
    names: set[str] = set()
    for item in section:
        value = str(getattr(item, identity_field, "") or "").strip()
        if value:
            names.add(value)
    return names


def find_unwritten_items(
    resume: ResumeContent,
    entry_names: dict[str, tuple[str, ...]],
    selection_data: dict[str, Any],
) -> list[str]:
    """对比"资料里有什么"与"简历里写了什么"，返回需要告知用户的条目。

    ``entry_names`` 是筛选前的身份字段清单（见 :class:`ProfileSelection`）；
    ``selection_data`` 是真正发给模型的候选资料。
    """
    warnings: list[str] = []
    for field, section, identity_field, label in _SECTION_MAP:
        original = set(entry_names.get(section) or ())
        if not original:
            continue
        written = _written_names(resume, field, identity_field)
        missing = original - written
        if not missing:
            continue
        # 关键区分：这条内容**有没有进入**发给模型的候选资料。
        # 没进入 → 关卡 1（相关性/预算）拦的；进入了 → 模型自己取舍的。
        in_candidates = original & _entry_names(selection_data.get(section), identity_field)
        dropped_early = sorted(missing - in_candidates)
        dropped_by_model = sorted(missing & in_candidates)

        parts: list[str] = []
        if dropped_early:
            preview = "、".join(f"「{name}」" for name in dropped_early[:_MAX_REPORTED])
            extra = f"（共 {len(dropped_early)} 条）" if len(dropped_early) > _MAX_REPORTED else ""
            parts.append(
                f"{preview}{extra}与这个岗位的关键词交集不足，没有进入本次生成使用的候选资料"
            )
        if dropped_by_model:
            preview = "、".join(f"「{name}」" for name in dropped_by_model[:_MAX_REPORTED])
            extra = f"（共 {len(dropped_by_model)} 条）" if len(dropped_by_model) > _MAX_REPORTED else ""
            parts.append(f"{preview}{extra}在候选资料里，但模型没有把它写进简历")
        if not parts:
            continue
        warnings.append(
            f"{label}中有 {len(missing)} 条没有出现在这份简历里：{'；'.join(parts)}。"
            "如果不是有意省略：把岗位关键词补进该条目的描述后重新生成，"
            "或在「微调内容」里手动补上这一段。"
        )
    return warnings


def all_entry_names(entry_names: dict[str, tuple[str, ...]]) -> set[str]:
    """把各分区的身份名合并成一个集合（给台账主张的包含判断用）。"""
    names: set[str] = set()
    for section_names in (entry_names or {}).values():
        names.update(name for name in section_names if name)
    return names


def claim_subjects(baseline: ClaimDigestOut | None) -> list[str]:
    """从事实基线里取已确认条目的主体（用于与条目名做包含判断）。

    ``baseline`` 为 None 是正常状态：没启用事实台账的用户、以及通用简历路径都传 None。
    """
    if baseline is None:
        return []
    subjects: list[str] = []
    for line in (baseline.baseline_text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        subject = str(entry.get("subject") or "").strip()
        if subject:
            subjects.append(subject)
    return subjects


def confirmed_claims_about(names: set[str], baseline: ClaimDigestOut | None) -> list[str]:
    """找出与给定条目名相关的已确认台账主张（主体里提到该名字）。

    台账条目本身**不会**被直接写进简历（它只是事实来源），所以这里不检查主张是否
    逐字出现——那必然几乎全部"未命中"。有用的是反过来的那条信息：
    用户已经为某个条目确认过事实，但该条目根本没进入候选资料。
    """
    if not names:
        return []
    hits: list[str] = []
    for subject in claim_subjects(baseline):
        for name in names:
            if name and name in subject:
                hits.append(name)
                break
    return sorted(set(hits))
