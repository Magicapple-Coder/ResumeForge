"""联网来源在「一次回答」内的全局编号。

编号必须**全局单调递增**：自动预搜（``assistant_stream`` 里那次）与模型自主发起的
``web_search`` 工具共用同一个计数器。若两个入口各自从 1 重新编号，模型看到的
``[来源N]`` 会指到不同的 URL，前端据此渲染的链接就会跳错来源——"一个能点却跳错
地方的链接，比没有链接更糟"。所以这里把"首次收集时分配编号"收敛成单一事实来源。
"""

from __future__ import annotations

from typing import Any


class SourceNumberer:
    """给一次回答里的来源分配全局唯一编号，并记录「编号 → url」映射。

    实例跨自动预搜与所有 ``web_search`` 工具调用共享，保证编号在**这一次回答**内
    单调递增、互不重号。映射**不做去重**：同一条 URL 被搜到两次会占两个编号，两个
    编号仍指向同一个 URL——去重只发生在"参考来源"展示面板，编号必须忠实于模型当时
    看到的那份列表，否则前端按编号解析会对不上号。
    """

    def __init__(self) -> None:
        self._next_number = 1
        self.by_number: dict[int, str] = {}

    def assign(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """给一批结果打上全局编号，返回带 ``number`` 字段的副本，并记录映射。"""
        numbered: list[dict[str, Any]] = []
        for result in results:
            numbered.append({**result, "number": self._next_number})
            self.by_number[self._next_number] = str(result.get("url") or "")
            self._next_number += 1
        return numbered

    def mapping(self) -> list[dict[str, Any]]:
        """序列化成可写进消息 ``context`` 的「编号 → url」列表（按编号升序）。"""
        return [{"number": number, "url": url} for number, url in self.by_number.items()]
