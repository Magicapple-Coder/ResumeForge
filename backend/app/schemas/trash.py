"""回收站接口的出入参。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TrashItemOut(BaseModel):
    """回收站里的一条内容（十类共用一个形状，界面用一张表混排）。"""

    model_config = ConfigDict(from_attributes=True)

    type: str
    # 中文类型名由**后端**给：前端的筛选器直接用它渲染，不必在界面里再抄一份"job→岗位"的映射
    # （抄一份就会漂移，新增一类内容时前端忘改就显示成英文 key）。
    type_label: str
    id: int
    title: str = ""
    subtitle: str = ""
    deleted_at: datetime | None = None


class TrashSummaryOut(BaseModel):
    total: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    # 类型 key → 中文名，用于渲染筛选项（含"全部"由前端自己加）。
    labels: dict[str, str] = Field(default_factory=dict)
    items: list[TrashItemOut] = Field(default_factory=list)


class TrashEmptyOut(BaseModel):
    """清空回收站的结果。

    返回**真正删掉了多少条**：用户点"清空"时最想知道的就是这个数，
    只回一个 204 等于让他自己数。
    """

    removed: int = 0


# 一次批量操作的上限：回收站不是归档区，批量也应有限度。
MAX_TRASH_BATCH = 500


class TrashBatchItemIn(BaseModel):
    """批量操作里的一条（``type_key`` = 类型 key，``id`` = 该类型下的记录主键）。"""

    type_key: str
    id: int = Field(ge=1)


class TrashBatchRequest(BaseModel):
    """批量恢复 / 批量彻底删除的请求体。"""

    items: list[TrashBatchItemIn] = Field(min_length=1, max_length=MAX_TRASH_BATCH)


class TrashBatchResultItem(BaseModel):
    """逐条结果：哪一条成了、哪一条没成（用户需要知道是**哪几条**）。"""

    type_key: str
    id: int
    ok: bool


class TrashRestoreBatchOut(BaseModel):
    """批量恢复的结果（恢复是安全的，无需二次确认）。"""

    restored: int = 0
    results: list[TrashBatchResultItem] = Field(default_factory=list)


class TrashPurgeBatchOut(BaseModel):
    """批量彻底删除的结果（不可恢复；二次确认由前端负责）。"""

    purged: int = 0
    results: list[TrashBatchResultItem] = Field(default_factory=list)
