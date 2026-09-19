"""回收站接口：查看、恢复、彻底删除、清空。

薄路由：只做校验、调 service、返回 schema。

**为什么恢复与彻底删除是两个不同的接口**：它们对用户是两件风险完全不同的事——恢复是安全的、
彻底删除不可逆。合成一个"删除"接口（用参数区分）会让前端某次传错参数就变成不可逆操作，
而这种错误在界面上完全看不出来。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.trash import TrashEmptyOut, TrashItemOut, TrashSummaryOut
from ..services import trash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trash", tags=["trash"])


def _require_spec(type_key: str) -> trash.TrashSpec:
    spec = trash.spec_or_none(type_key)
    if spec is None:
        raise HTTPException(status_code=404, detail="未知的内容类型")
    return spec


@router.get("", response_model=TrashSummaryOut)
def read_trash(
    type: str = Query(default="", description="按类型筛选；留空表示全部"),
    db: Session = Depends(get_db),
):
    """回收站内容：总量、按类型的计数、类型名，以及条目列表（按删除时间倒序）。"""
    if type:
        _require_spec(type)
    counted = trash.counts(db)
    return TrashSummaryOut(
        counts=counted,
        labels={spec.key: spec.label for spec in trash.TRASH_SPECS},
        items=[TrashItemOut(**item) for item in trash.list_trashed(db, key=type)],
        total=sum(counted.values()),
    )


@router.post("/{type_key}/{item_id}/restore", status_code=204)
def restore_item(type_key: str, item_id: int, db: Session = Depends(get_db)):
    """把一条内容从回收站恢复。"""
    _require_spec(type_key)
    if not trash.restore(db, type_key, item_id):
        raise HTTPException(status_code=404, detail="回收站里没有这条内容（可能已被恢复或彻底删除）")


@router.delete("/{type_key}/{item_id}", status_code=204)
def purge_item(type_key: str, item_id: int, db: Session = Depends(get_db)):
    """**彻底删除**一条内容——不可恢复。

    只接受**已经在回收站里**的记录：这样"删除"永远先经过可恢复的一步，
    界面上也就不存在"点一下就没了"的路径。
    """
    _require_spec(type_key)
    if not trash.purge(db, type_key, item_id):
        raise HTTPException(status_code=404, detail="回收站里没有这条内容（可能已被恢复或彻底删除）")


@router.delete("", response_model=TrashEmptyOut)
def empty_trash(
    type: str = Query(default="", description="只清空某一类；留空表示全部清空"),
    db: Session = Depends(get_db),
):
    """清空回收站（**不可恢复**）。返回真正删掉的条数。"""
    if type:
        _require_spec(type)
    return TrashEmptyOut(removed=trash.empty(db, key=type))
