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
