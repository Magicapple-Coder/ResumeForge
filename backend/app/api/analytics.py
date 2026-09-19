"""求职数据看板接口（prefix ``/api/analytics``）。

纯本地聚合，不依赖 LLM，离线可用。口径见 ``services/analytics.py`` 的模块 docstring。
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.analytics import DashboardOut
from ..services.analytics import build_dashboard

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/dashboard", response_model=DashboardOut)
def read_dashboard(
    trend_months: int = Query(default=6, ge=1, le=24, description="趋势统计的自然月数（1..24）"),
    db: Session = Depends(get_db),
):
    """投递总量 / 面试率 / 笔试通过率 / Offer 数 / 六阶段漏斗 / 月度趋势。"""
    return DashboardOut(**build_dashboard(db, trend_months=trend_months))
