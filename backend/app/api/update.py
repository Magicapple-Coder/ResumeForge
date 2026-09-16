"""软件更新检查接口（只读，不执行任何自动更新）。"""
import logging

from fastapi import APIRouter, Query

from ..schemas.update import UpdateCheckResult
from ..services.update_check import check_for_update

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/update", tags=["update"])


@router.get("/check", response_model=UpdateCheckResult)
async def read_update_status(refresh: bool = Query(default=False)):
    """对比本地版本与 GitHub 最新 Release。

    结果缓存 15 分钟；``refresh=true`` 时强制重新请求（用户点「重新检查」）。
    """
    return await check_for_update(refresh=refresh)
