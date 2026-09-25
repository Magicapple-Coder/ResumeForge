"""官网采集的通用路径：没有专用适配器时按"页面里有什么"逐级降级。

三级各有独立的命中证据，越靠前越确定：

1. ``jsonld`` —— 页面内嵌的 schema.org ``JobPosting`` 结构化数据。**有公开规范，零猜测**
   （零模型、零选择器）；
2. 配方（阶段 2）—— 从一次归纳得到的选择器，之后纯复用；
3. 单页模型兜底（阶段 2）—— 前两级都失败才把页面交给模型。

**导航永远由确定性代码执行**：模型只做"这一页 → 结构化岗位"的抽取，不决定点哪里、翻到第几页。
"""
from .jsonld import extract_job_postings, parse_job_posting, script_payloads

__all__ = ["extract_job_postings", "parse_job_posting", "script_payloads"]
