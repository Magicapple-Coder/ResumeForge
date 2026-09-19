"""ATS 本地检测（R-10）：格式风险 / 关键词覆盖 / 信息位置。

**本地规则估计**：这里用的是通用启发式规则，结果只作参考——**不代表真实 ATS 解析结果**。
所有结论都在输出的 ``disclaimer`` 里声明，前端必须展示。

- 格式风险：关键字段缺失、正文里的特殊符号（可能被 ATS 误解析）。
- 关键词覆盖：对照 ``data/ats_keywords.json`` 词库；提供了 JD 文本时，先抽 JD 命中的
  词库关键词，再检查这些词在简历里的覆盖情况；未提供 JD 时做通用关键词覆盖。
- 信息位置：求职意向 / 个人总结 / 教育 / 技能等关键区块是否就位。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..schemas.ats import ATS_DISCLAIMER, AtsCheckOut, AtsIssue
from ..schemas.resume import ResumeContent

_ATS_KEYWORDS_PATH = Path(__file__).resolve().parent.parent / "data" / "ats_keywords.json"

# 容易被 ATS 误解析、或让版面显得不专业的符号：emoji、方框线、带圈数字、杂项符号。
_SPECIAL_CHAR_RE = re.compile(
    r"[\u2460-\u2473\u2500-\u257F\u2600-\u27BF\uFE00-\uFE0F\uD800-\uDBFF]"
)

_SEVERITY_PENALTY = {"high": 15, "medium": 8, "low": 3}


def load_keywords() -> list[str]:
    """加载 ATS 通用关键词词库，按分类展平并去重（保持大小写原貌）。"""
    data = json.loads(_ATS_KEYWORDS_PATH.read_text(encoding="utf-8"))
    categories = data.get("categories", {})
    words: list[str] = []
    seen: set[str] = set()
    for values in categories.values():
        for word in values:
            if not isinstance(word, str) or not word.strip():
                continue
            key = word.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            words.append(word.strip())
    return words


def _resume_text(resume: ResumeContent) -> str:
    """简历可检索文本（小写，排除 photo）。"""
    return json.dumps(resume.model_dump(exclude={"photo"}), ensure_ascii=False).lower()


def _find_special_chars(resume: ResumeContent) -> list[str]:
    text = json.dumps(resume.model_dump(exclude={"photo"}), ensure_ascii=False)
    found: list[str] = []
    for match in _SPECIAL_CHAR_RE.finditer(text):
        char = match.group(0)
        if char not in found:
            found.append(char)
    return found


def _format_issues(resume: ResumeContent) -> list[AtsIssue]:
    issues: list[AtsIssue] = []
    if not resume.name.strip():
        issues.append(
            AtsIssue(
                category="format",
                severity="high",
                title="缺少姓名",
                detail="姓名缺失会被 ATS 与 HR 直接判为不合格",
            )
        )
    if not resume.phone.strip() and not resume.email.strip():
        issues.append(
            AtsIssue(
                category="format",
                severity="high",
                title="缺少联系方式",
                detail="手机与邮箱至少保留一项，否则无法联系到你",
            )
        )
    special = _find_special_chars(resume)
    if special:
        issues.append(
            AtsIssue(
                category="format",
                severity="medium",
                title="正文含特殊符号",
                detail="特殊符号 / emoji 可能被 ATS 误解析，建议改用纯文本",
                evidence=special[:5],
            )
        )
    return issues


def _position_issues(resume: ResumeContent) -> list[AtsIssue]:
    issues: list[AtsIssue] = []
    if not resume.job_intent.strip():
        issues.append(
            AtsIssue(
                category="position",
                severity="medium",
                title="缺少求职意向",
                detail="求职意向应放在顶部显眼位置，方便 ATS 与 HR 快速定位",
            )
        )
    if not resume.summary.strip():
        issues.append(
            AtsIssue(
                category="position",
                severity="medium",
                title="缺少个人总结",
                detail="个人总结缺失，ATS 难以快速抓取你的核心卖点",
            )
        )
    if not resume.education:
        issues.append(
            AtsIssue(
                category="position",
                severity="medium",
                title="缺少教育经历",
                detail="教育经历缺失；应届生建议把它放在靠前位置",
            )
        )
    if not resume.skills:
        issues.append(
            AtsIssue(
                category="position",
                severity="medium",
                title="缺少技能清单",
                detail="技能应单列成块，便于关键词命中",
            )
        )
    return issues


def _jd_keywords(jd_text: str, library: list[str]) -> list[str]:
    """从词库里挑出 JD 文本中出现的那些词。"""
    jd_lower = jd_text.lower()
    return [word for word in library if word.lower() in jd_lower]


def _keyword_coverage(
    resume: ResumeContent, jd_text: str
) -> tuple[list[str], list[str]]:
    library = load_keywords()
    resume_lower = _resume_text(resume)
    target = _jd_keywords(jd_text, library) if jd_text.strip() else library
    # JD 里没有任何词库关键词时退回通用覆盖，避免一次检查什么都不报。
    if jd_text.strip() and not target:
        target = library
    matched = [word for word in target if word.lower() in resume_lower]
    missing = [word for word in target if word.lower() not in resume_lower]
    return matched, missing


def _keyword_issues(matched: list[str], missing: list[str]) -> list[AtsIssue]:
    if not missing:
        return []
    return [
        AtsIssue(
            category="keyword",
            severity="medium",
            title="关键词覆盖不足",
            detail=f"有 {len(missing)} 个常见关键词未出现在简历中，可能影响 ATS 匹配",
            evidence=missing[:10],
        )
    ]


def _score(issues: list[AtsIssue]) -> int:
    score = 100
    for issue in issues:
        score -= _SEVERITY_PENALTY.get(issue.severity, 0)
    return max(0, min(100, score))


def check_ats(
    resume: ResumeContent, jd_text: str = "", *, resume_id: int = 0
) -> AtsCheckOut:
    """ATS 本地检测：三类结论 + 免责声明。纯本地计算，不调用模型。"""
    issues = _format_issues(resume) + _position_issues(resume)
    matched, missing = _keyword_coverage(resume, jd_text)
    issues.extend(_keyword_issues(matched, missing))
    summary: dict[str, int] = {}
    for issue in issues:
        summary[issue.category] = summary.get(issue.category, 0) + 1
    return AtsCheckOut(
        resume_id=resume_id,
        issues=issues,
        matched_keywords=matched,
        missing_keywords=missing,
        score=_score(issues),
        disclaimer=ATS_DISCLAIMER,
        summary=summary,
    )


__all__ = ["ATS_DISCLAIMER", "check_ats", "load_keywords"]
