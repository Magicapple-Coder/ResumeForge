"""简历风险扫描的响应 schema（R-08 查重/敏感词/夸大/深挖风险点 + R-09 合规校验）。

风险扫描**只提示、不改写**：没有任何请求体，POST 即对已保存简历做一次体检。响应里的
``points`` 是扁平列表，前端按 ``category`` 分组展示；``summary`` 是各类命中数，``llm_used``
标记是否启用了可选模型增强（未配置时本地规则照常生效）。
"""
from typing import Literal

from pydantic import BaseModel, Field

# 五类风险：查重 / 敏感词 / 夸大 / 深挖风险点 / 合规。取值与前端 types/resumeRisk.ts
# 逐字一致（共享知识第 15 条）。
RiskCategory = Literal["duplicate", "sensitive", "exaggeration", "deep_dive", "compliance"]
RiskSeverity = Literal["high", "medium", "low"]


class RiskPoint(BaseModel):
    """一条风险点。所有字段都只是「提示」，绝不触发正文改写。"""

    category: RiskCategory
    severity: RiskSeverity = "medium"
    # 命中的原文片段，便于前端定位与高亮。
    text: str = Field(default="", max_length=20_000)
    # 命中位置说明，如「项目经历「xx」」或「个人总结」。
    location: str = Field(default="", max_length=256)
    # 给用户的建议（只提示，不自动改写）。
    suggestion: str = Field(default="", max_length=20_000)
    # 深挖风险点联动事实台账时回填的条目 id（只读，不修改台账）。
    claim_id: int | None = None
    # 强主张联动时，把「这条会被追问什么」回填成追问清单。
    follow_up: list[str] = Field(default_factory=list, max_length=20)


class RiskScanOut(BaseModel):
    resume_id: int
    points: list[RiskPoint] = Field(default_factory=list)
    # 各类风险点计数（category -> 命中条数）。
    summary: dict[str, int] = Field(default_factory=dict)
    # 是否使用了可选模型增强；未配置时为 False，本地规则结果仍完整可用。
    llm_used: bool = False
    # 降级 / 提示信息，例如「模型增强未生效，已使用本地规则」。
    notes: list[str] = Field(default_factory=list)


__all__ = ["RiskCategory", "RiskPoint", "RiskScanOut", "RiskSeverity"]
