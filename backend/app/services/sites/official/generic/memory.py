"""一个站点攒下来的抽取知识：配方，以及"这一页问过模型了、内容没变"的指纹。

**为什么值得单独一个模块**：它要落进 ``official_site.recipe`` 那个 JSON 列，而 JSON 列的坏处
是形状只存在于代码里——读的地方多一处，就多一处会写错的形状。把"怎么读、怎么写、什么时候
算过期"收在一处，迁移与兼容才有唯一入口。

**只记"什么都没读出来"的那一次**。读出了内容就不该跳过——那些内容正是目的；而读不出内容的
页面在内容未变时再问一次模型，只会得到同样的空结果。这条区分是这一层存在的全部理由。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .llm_extract import page_fingerprint
from .recipe import Recipe

# 记忆格式版本，与 ``Recipe.RECIPE_SCHEMA`` 是两层：这一层描述外面的对象，
# 里面那层描述配方本身。分开是为了改任一层时不必动另一层。
MEMORY_SCHEMA = 1

# 最多记多少个"问过但没读出来"的页面。它是省钱用的备忘，不是账本，满了就丢最早的。
MAX_UNREADABLE = 20


@dataclass
class SiteMemory:
    """从 ``recipe`` 列读出来的东西，以及本次修改的痕迹。"""

    listing: Recipe | None = None
    # 页面地址 → 内容指纹。内容变了就重新问一次模型（页面改版常常意味着有新岗位）。
    unreadable: dict[str, str] = field(default_factory=dict)
    # 本次有没有改动过。为真时调用方把它写回库里。
    changed: bool = False

    @classmethod
    def from_blob(cls, blob: Any) -> SiteMemory:
        """读回记忆。**认不出来就当没有**——半懂的配方比没有配方危险。"""
        if not isinstance(blob, dict) or blob.get("schema") != MEMORY_SCHEMA:
            return cls()
        raw_unreadable = blob.get("unreadable")
        unreadable = {
            str(key): str(value)
            for key, value in (raw_unreadable.items() if isinstance(raw_unreadable, dict) else ())
            if str(key) and str(value)
        }
        return cls(listing=Recipe.from_dict(blob.get("listing")), unreadable=unreadable)

    def to_blob(self) -> dict[str, Any]:
        return {
            "schema": MEMORY_SCHEMA,
            "listing": self.listing.to_dict() if self.listing else None,
            # 按**记录顺序**取最近的那些，而不是按 URL 字典序——字典保序，取末尾即最新。
            "unreadable": dict(list(self.unreadable.items())[-MAX_UNREADABLE:]),
        }

    def remember_unreadable(self, page_url: str, markup: str) -> None:
        """记下"这一页问过模型、什么都没读出来"。见模块说明里为什么只记这一种。"""
        if not page_url:
            return
        fingerprint = page_fingerprint(markup)
        self.unreadable = {**self.unreadable, page_url: fingerprint}
        # 超出上限时丢最早记的那些（字典保序，取末尾即最新）。
        if len(self.unreadable) > MAX_UNREADABLE:
            self.unreadable = dict(list(self.unreadable.items())[-MAX_UNREADABLE:])
        self.changed = True

    def should_skip_model(self, page_url: str, markup: str) -> bool:
        """这一页是不是**已经问过、且内容没变**。"""
        return self.unreadable.get(page_url) == page_fingerprint(markup)

    def remember_recipe(self, recipe: Recipe) -> None:
        self.listing = recipe
        # 配方到手之后，之前的"读不出来"记录就不作数了。
        self.unreadable = {}
        self.changed = True


__all__ = ["MAX_UNREADABLE", "MEMORY_SCHEMA", "SiteMemory"]
