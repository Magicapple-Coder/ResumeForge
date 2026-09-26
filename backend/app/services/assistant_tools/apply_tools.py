"""助手对「投递台」的只读工具。

**刻意只读**：真正点下"投递"是用户在投递台上做的动作，助手只负责如实报告队列状态——
那一步要填的表单千差万别，代填填错的代价是用户的真实误投。删除类工具本仓库助手一概不提供。

**这个模块是搬出来的**：它原先住在 ``official_tools.py`` 里（官网采集与投递台两个功能的工具
写在同一份文件），而官网采集被移除后，那个文件整份删掉了。投递台的工具与官网采集没有任何
关系，跟着一起删就会**顺手把投递台的一个助手能力干掉**——所以先把它搬到这里，再删那一份。
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ._types import ToolResult

# 与其它列表工具同一档上限，避免把一整页报告塞进上下文。
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def _tool_list_apply_queue(db: Session, arguments: dict) -> ToolResult:
    """投递台的队列（待投递/已投递/失败），只读。"""
    from ..apply import apply_service  # 局部导入：这个模块依赖较重，避免拖慢助手启动

    limit = min(int(arguments.get("limit") or DEFAULT_LIMIT), MAX_LIMIT)
    items = apply_service.list_queue(db)
    rows = [
        {
            "id": item.id,
            "company": item.company,
            "job_title": item.job_title,
            "status": item.status,
            "resume_title": item.resume_title,
            "apply_supported": item.apply_supported,
            "admission": item.admission,
        }
        for item in items[:limit]
    ]
    payload = {
        "总数": len(items),
        "返回": len(rows),
        "队列": rows,
        "说明": "这是「投递台」的队列状态快照。助手不代为发起投递——那一步必须在投递台上由用户点击。",
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了投递队列（{len(items)} 条）",
        link="/apply",
    )


__all__ = [
    "_tool_list_apply_queue",
]
