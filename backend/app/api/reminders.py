"""日历提醒接口（prefix ``/api/reminders``）。

提醒的增删改查：列表 / 待办（upcoming）/ 新增 / 修改（PATCH）/ 删除。删除走软删除
（``trash.live_only`` 列表里不再出现），彻底删除在回收站里另做。

``/upcoming`` 必须注册在 ``/{reminder_id}`` 之前——虽然二者方法不同（GET vs PATCH/DELETE）
不会撞车，但顺序放前面能让"待办"这个更常用的语义不被路径参数抢走语义。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.reminder import REMINDER_KINDS, REMINDER_STATUSES
from ..schemas.reminder import ReminderCreate, ReminderOut, ReminderUpdate, ReminderUpcomingOut
from ..services.reminder_service import (
    create_reminder,
    delete_reminder,
    list_reminders,
    reminder_or_none,
    upcoming_reminders_out,
    update_reminder,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


@router.get("", response_model=list[ReminderOut])
def read_reminders(
    kind: str = Query(default=""),
    status: str = Query(default=""),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if kind and kind not in REMINDER_KINDS:
        raise HTTPException(status_code=422, detail="未知的提醒类型")
    if status and status not in REMINDER_STATUSES:
        raise HTTPException(status_code=422, detail="未知的提醒状态")
    return list_reminders(db, kind=kind, status=status, limit=limit)


@router.get("/upcoming", response_model=list[ReminderUpcomingOut])
def read_upcoming(limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_db)):
    """待办提醒：只返回 pending，按紧急度+提醒时间升序。"""
    return upcoming_reminders_out(db, limit=limit)


@router.post("", response_model=ReminderOut, status_code=201)
def create_reminder_entry(payload: ReminderCreate, db: Session = Depends(get_db)):
    return create_reminder(db, payload)


@router.patch("/{reminder_id}", response_model=ReminderOut)
def patch_reminder(reminder_id: int, payload: ReminderUpdate, db: Session = Depends(get_db)):
    reminder = reminder_or_none(db, reminder_id)
    if reminder is None:
        raise HTTPException(status_code=404, detail="提醒不存在或已被删除")
    return update_reminder(db, reminder, payload)


@router.delete("/{reminder_id}", status_code=204)
def remove_reminder(reminder_id: int, db: Session = Depends(get_db)):
    if not delete_reminder(db, reminder_id):
        raise HTTPException(status_code=404, detail="提醒不存在或已被删除")
