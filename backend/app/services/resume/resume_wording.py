"""措辞的确定性门槛：简历里不该出现的空话与互联网黑话。

提示词已经点名禁掉这些词，但模型是概率系统——真机实测里它仍然写出过「闭环」。这里做的是
**确定性检查**，把结果交给生成器已有的"一次质量重试"去改写；重试后仍然命中时以 warning
告知用户。刻意不在代码里机械替换词语：替换会写出语义不通的句子，比留着黑话更糟。

只应在**启用美化拓展**时使用：关闭美化时正文是用户资料原文，改它就是篡改用户自己的表述。
"""

from __future__ import annotations

from ...schemas.resume import ResumeContent

# 高置信度的互联网黑话。宁可漏检也不扩大名单：误判会让一次生成多花一次模型调用，
# 还可能把用户原本通顺的句子改坏。提示词里列的"落地""推动""梳理"等是正当的简历动词，
# 不在名单内。
CLICHE_WORDS = (
    "赋能",
    "抓手",
    "闭环",
    "颗粒度",
    "拉通",
    "组合拳",
    "打法",
    "心智",
    "体感",
    "飞轮",
)

# 提示词里点名的空话套话。按整句匹配，避免把正常的"……能力强"一律判成套话。
CLICHE_PHRASES = (
    "团队协作能力强",
    "结果导向",
)

# 与提示词的"篇幅与粒度""分模块呈现要求"覆盖同一批描述性字段。
_SECTIONS = ("education", "experience", "campus_experience", "projects")
_FIELDS = ("achievements", "description", "highlights")


def _descriptive_points(resume: ResumeContent) -> list[str]:
    """收集会被写进简历的描述性文本。"""
    points: list[str] = []
    if resume.summary and resume.summary.strip():
        points.append(resume.summary.strip())
    for section in _SECTIONS:
        for item in getattr(resume, section, []) or []:
            for field in _FIELDS:
                for value in getattr(item, field, None) or []:
                    text = str(value).strip()
                    if text:
                        points.append(text)
    return points


def find_cliches(resume: ResumeContent) -> list[str]:
    """返回命中的黑话/空话，顺序稳定（便于测试与提示词渲染）。"""
    text = "\n".join(_descriptive_points(resume))
    hits = [word for word in CLICHE_WORDS if word in text]
    hits.extend(phrase for phrase in CLICHE_PHRASES if phrase in text)
    return hits


def cliche_shortfalls(resume: ResumeContent) -> list[str]:
    """把命中的词写成质量重试可用的短板说明；没有命中时返回空列表。"""
    hits = find_cliches(resume)
    if not hits:
        return []
    return [
        "要点里出现了空话或互联网黑话："
        + "、".join(hits)
        + "。请改成具体的做法与结果，不要使用这类词。"
    ]


__all__ = [
    "CLICHE_PHRASES",
    "CLICHE_WORDS",
    "cliche_shortfalls",
    "find_cliches",
]
