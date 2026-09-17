"""联网搜索：多引擎聚合 + 可选正文抓取。

分工：
- ``duckduckgo`` / ``searxng`` 各自实现一个公开搜索源，只负责"拿到候选结果"；
- ``page_reader`` 负责把某条结果页的正文读回来（受限大小与超时）；
- ``aggregate`` 负责并发调度、去重、相关性过滤、官网优先排序与正文补全。

原有的 Bing RSS 实现留在 ``services/assistant_web_search.py``（它同时承担查询改写与
相关性过滤，且被既有测试钉着），这里通过依赖注入调用它，不重复实现。
"""
from .aggregate import aggregate_search

__all__ = ["aggregate_search"]
