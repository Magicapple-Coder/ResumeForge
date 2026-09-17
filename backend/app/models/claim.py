"""事实台账：把"写进简历的每一句话"沉淀成可核对、可复核的条目。

个人资料库记录的是**发生过什么**（在哪家公司、做了什么项目）；台账记录的是一条条
**可对外表达的主张**——它对应哪份原始事实、依据是什么、当时承担到什么程度、能不能
进正式简历。两者是叠加关系而不是替代关系：台账为空时，整套生成链路的行为与以前
完全一致；用户开始维护台账后，「已确认」的条目才会作为事实基线进入生成提示词。

设计要点：

- **状态决定用途**，不是决定好坏。``已确认`` 可以进正式材料；``待确认`` 只能进草稿
  并必须带占位符；``已过期`` 需要先更新；``不采用`` 保留原因供复盘，但不对外。
- **两个闸门函数**（:func:`can_enter_final` / :func:`has_placeholder`）是这套规则的
  唯一实现处，服务层、导出接口和前端都从这里取结论，避免各处各判一次、判得不一致。
- **承担程度与个人边界分开**：前者是枚举（便于排序与筛选），后者是自由文本，用来
  写清"团队做了什么、我做了什么"的分界——恰恰是最容易被追问的地方。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow

# ===== ① 承担程度：个人在其中的位置，用于防止把团队成果写成本人主导 =====
RESPONSIBILITY_PARTICIPATED = "参与"
RESPONSIBILITY_MODULE = "负责模块"
RESPONSIBILITY_LED = "主导方案或交付"
RESPONSIBILITY_OWNER = "项目负责人"
RESPONSIBILITY_LEVELS = (
    RESPONSIBILITY_PARTICIPATED,
    RESPONSIBILITY_MODULE,
    RESPONSIBILITY_LED,
    RESPONSIBILITY_OWNER,
)

# 强主张的判定：出现这些承担程度时，必须能回答追问，因此要求填面试细节。
STRONG_RESPONSIBILITY_LEVELS = frozenset({RESPONSIBILITY_LED, RESPONSIBILITY_OWNER})

# ===== ② 核实状态：决定这条主张能出现在哪一版材料里 =====
VERIFICATION_CONFIRMED = "已确认"
VERIFICATION_PENDING = "待确认"
VERIFICATION_EXPIRED = "已过期"
VERIFICATION_REJECTED = "不采用"
VERIFICATION_STATUSES = (
    VERIFICATION_CONFIRMED,
    VERIFICATION_PENDING,
    VERIFICATION_EXPIRED,
    VERIFICATION_REJECTED,
)

# 状态说明直接展示给用户，所以要写清"能用在哪、不能用在哪"。
VERIFICATION_STATUS_LABELS = {
    VERIFICATION_CONFIRMED: "已确认：可以作为事实写进正式简历",
    VERIFICATION_PENDING: "待确认：只能进草稿，必须保留【待补】占位符",
    VERIFICATION_EXPIRED: "已过期：内容会随时间变化，更新前不作为最新事实",
    VERIFICATION_REJECTED: "不采用：保留原因供复盘，不进入对外材料",
}

_VERIFICATION_ICONS = {
    VERIFICATION_CONFIRMED: "✔",
    VERIFICATION_PENDING: "○",
    VERIFICATION_EXPIRED: "⏳",
    VERIFICATION_REJECTED: "✕",
}

# ===== ③ 分类：与个人资料库的区块对齐，便于把资料一键转成台账草稿 =====
CLAIM_CATEGORY_EDUCATION = "教育经历"
CLAIM_CATEGORY_EXPERIENCE = "实习/工作"
CLAIM_CATEGORY_PROJECT = "项目经历"
CLAIM_CATEGORY_CAMPUS = "校园经历"
CLAIM_CATEGORY_SKILL = "专业技能"
CLAIM_CATEGORY_AWARD = "荣誉奖项"
CLAIM_CATEGORY_OTHER = "其他"
CLAIM_CATEGORIES = (
    CLAIM_CATEGORY_EDUCATION,
    CLAIM_CATEGORY_EXPERIENCE,
    CLAIM_CATEGORY_PROJECT,
    CLAIM_CATEGORY_CAMPUS,
    CLAIM_CATEGORY_SKILL,
    CLAIM_CATEGORY_AWARD,
    CLAIM_CATEGORY_OTHER,
)

# ===== ④ 未完成标记：全仓库统一的可检索标记，且被禁止进入最终导出 =====
# 用中括号【】而不是 Markdown 语法，一是中文语境下更醒目，二是能安全地出现在
# HTML/Markdown/JSON 三种导出格式里而不破坏结构。
PLACEHOLDER_PREFIX = "【待补"
PLACEHOLDER_MARKERS = (PLACEHOLDER_PREFIX, "【待确认", "【待补充", "【待核实")


def has_placeholder(text: str) -> bool:
    """文本里是否含未完成标记（决定它能不能进最终导出）。"""
    return any(marker in (text or "") for marker in PLACEHOLDER_MARKERS)


def placeholder_hit(text: str) -> str:
    """返回文本里命中的第一个未完成标记，便于在错误信息里指出具体位置。"""
    for marker in PLACEHOLDER_MARKERS:
        if marker in (text or ""):
            return marker
    return ""


def can_enter_final(status: str) -> bool:
    """该核实状态的主张能否进入最终导出。

    只有 ``已确认`` 可以。未知取值一律按"不可进入"处理——绝不因为读到一个没见过的
    状态就把它当成确认过的。
    """
    return status == VERIFICATION_CONFIRMED


def verification_label(status: str) -> str:
    """面向用户的状态说明；未知状态给出中性且不误导的描述。"""
    return VERIFICATION_STATUS_LABELS.get(status, "状态未知：请重新选择")


def verification_icon(status: str) -> str:
    return _VERIFICATION_ICONS.get(status, "?")


class ClaimRecord(Base):
    """一条可核对的主张。"""

    __tablename__ = "claim_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 列表里显示什么，用户自己起名即可（默认取主体名）。
    title: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(32), default=CLAIM_CATEGORY_OTHER, index=True)
    # 这条主张是关于谁的：公司名 / 项目名 / 学校名 / 技能名。用于按主体检索，
    # 也是"生成后把简历条目回指到台账"的匹配依据。
    subject: Mapped[str] = mapped_column(String(200), default="", index=True)

    # 原始事实：用户照实写，不做包装。候选表述是"准备写进简历的版本"。
    # 两者必须都在，否则改措辞时会把原始事实一起改掉。
    source_fact: Mapped[str] = mapped_column(Text, default="")
    candidate_wording: Mapped[str] = mapped_column(Text, default="")

    # [{"type": "pull_request", "location": "...", "public": true, "note": ""}]
    # 只存定位证据所需的信息；密码、验证码、邮件全文一律不入库（见 AGENTS.md 安全边界）。
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    responsibility_level: Mapped[str] = mapped_column(
        String(32), default=RESPONSIBILITY_PARTICIPATED, index=True
    )
    verification_status: Mapped[str] = mapped_column(
        String(16), default=VERIFICATION_PENDING, index=True
    )
    # 可用范围：这条主张能用在哪些材料里（某岗位版本 / 开场白 / 自我介绍）。空表示不限。
    allowed_uses: Mapped[list[str]] = mapped_column(JSON, default=list)
    # {"decisions": [], "difficulties": [], "verification": [], "result": null}
    # 面试时能被追问下去的那部分：做过什么决策、卡在哪、怎么验证、结果如何。
    interview_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # 团队成果与个人贡献的分界。写成一句话，面试时直接照着说。
    boundary: Mapped[str] = mapped_column(Text, default="")
    risk_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    # YYYY-MM-DD；未知为空串（用字符串与资料库既有的日期字段保持一致）。
    last_verified: Mapped[str] = mapped_column(String(10), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


__all__ = [
    "CLAIM_CATEGORIES",
    "CLAIM_CATEGORY_AWARD",
    "CLAIM_CATEGORY_CAMPUS",
    "CLAIM_CATEGORY_EDUCATION",
    "CLAIM_CATEGORY_EXPERIENCE",
    "CLAIM_CATEGORY_OTHER",
    "CLAIM_CATEGORY_PROJECT",
    "CLAIM_CATEGORY_SKILL",
    "ClaimRecord",
    "PLACEHOLDER_MARKERS",
    "PLACEHOLDER_PREFIX",
    "RESPONSIBILITY_LEVELS",
    "RESPONSIBILITY_LED",
    "RESPONSIBILITY_MODULE",
    "RESPONSIBILITY_OWNER",
    "RESPONSIBILITY_PARTICIPATED",
    "STRONG_RESPONSIBILITY_LEVELS",
    "VERIFICATION_CONFIRMED",
    "VERIFICATION_EXPIRED",
    "VERIFICATION_PENDING",
    "VERIFICATION_REJECTED",
    "VERIFICATION_STATUSES",
    "can_enter_final",
    "has_placeholder",
    "placeholder_hit",
    "verification_icon",
    "verification_label",
]
