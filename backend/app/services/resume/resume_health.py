"""简历与事实台账的健康度聚合（求职统计页「简历与健康度」区块）。

回答的是"我手上这些材料里有多少份需要再看一眼"，不重复任何判定逻辑：

- **一致性提醒**读 ``ResumeRecord.warnings``——那是生成时校验留下的原样记录。
- **【待补】标记**走 :func:`resume_completeness.find_incomplete`（占位符判定只此一处），
  把它的返回**当布尔用**：这里只数"有几份还不完整"，完整清单属于简历编辑页。
- **待确认主张**读 ``VERIFICATION_PENDING``，不写字面量。

实测 22 份简历约 4.5ms（每份 0.2ms），所以正常规模下是全量精确计数；仍设
:data:`MAX_RESUME_SCAN` 上限并把 ``resume_scanned_count`` 一并下发，万一简历库涨到几百份，
看板也能如实说明"这个数是最近扫过的那批"，而不是让一个抽样值冒充全量。
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .. import trash
from .resume_completeness import find_incomplete
from ...models.claim import VERIFICATION_PENDING, ClaimRecord
from ...models.resume import ResumeRecord
from ...schemas.resume import ResumeContent

logger = logging.getLogger(__name__)

# 扫描上限：按创建时间倒序取最近这么多份。超出时 resume_scanned_count < resume_count，
# 调用方据此知道待补份数是"最近这批里"的。
MAX_RESUME_SCAN = 200


def resume_health(db: Session) -> dict:
    """简历库与台账的健康度计数（全部来自未软删除的行）。"""
    live = db.query(ResumeRecord).filter(trash.live_only(ResumeRecord))
    resume_count = live.count()
    rows = (
        live.order_by(ResumeRecord.created_at.desc(), ResumeRecord.id.desc())
        .limit(MAX_RESUME_SCAN)
        .all()
    )

    with_warnings = 0
    with_placeholders = 0
    for record in rows:
        if record.warnings:
            with_warnings += 1
        try:
            content = ResumeContent.model_validate(record.content)
        except Exception:  # noqa: BLE001 - 脏数据不能拖垮整个看板
            # 解析不了的简历不计入待补（宁少算也不猜），但要留一条日志。
            logger.warning("简历 #%s 的 content 无法解析，健康度统计已跳过", record.id)
            continue
        if find_incomplete(content):
            with_placeholders += 1

    unverified_claims = (
        db.query(ClaimRecord)
        .filter(
            trash.live_only(ClaimRecord),
            ClaimRecord.verification_status == VERIFICATION_PENDING,
        )
        .count()
    )

    return {
        "resume_count": resume_count,
        "resume_scanned_count": len(rows),
        "resume_with_warnings_count": with_warnings,
        "resume_with_placeholders_count": with_placeholders,
        "unverified_claim_count": unverified_claims,
    }


__all__ = ["MAX_RESUME_SCAN", "resume_health"]
