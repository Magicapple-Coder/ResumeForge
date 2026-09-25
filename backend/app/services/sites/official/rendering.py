"""判断一个页面是不是"要靠 JS 才渲染得出内容"。

**它决定要不要为这一页去开一次真实浏览器**，而那是有代价的（慢、且要求用户的浏览器在跑），
所以判据必须两边都不误伤：

- 判成"要渲染"而其实不用 → 白开一次浏览器，慢几秒；
- 判成"不用渲染"而其实要 → **这一页什么都读不出来**，而报告里不会有任何异常迹象
  （空列表是个合法结果），于是漏抓被伪装成"这里没有岗位"。

后者的后果重得多，所以判据是**两条同时成立**才算：

1. **可读文字少得可怜**——渲染确实没发生过；
2. **有"这是个前端渲染页面"的痕迹**——挂载点、框架的数据脚本、或 noscript 的 JS 提示。

只满足第一条就送去渲染，会让每一次**正常的空结果**（真的没有岗位、或一个 404 页）都多花
几秒去开一次浏览器——而它们本来就有结论，不需要渲染。
"""
from __future__ import annotations

import re

from .html_text import html_to_text

# 可读文字少于这个长度才可能"渲染没发生"。真实招聘页（哪怕只有一屏）远超它；
# 而各种错误页、跳转页、空壳页都在这个量级以下。
_MAX_RENDERED_TEXT_CHARS = 400

# 前端框架的**空挂载点**：容器在、里面什么都没有。带内容的不算——那说明已经渲染过了。
#
# 属性值**可以不加引号**（``<div id=app>``）——压缩过的页面全是这种写法，而实测的一个真实
# 招聘站正是这么写的（另一个把 id 起成了 ``bd``，见下面那条兜底判据）。只认带引号的形式，
# 等于把最常见的写法漏掉。
#
# 容器里允许有空白与注释：``<div id="bd"><!--<?- html ?>--></div>`` 是模板占位的常见写法。
_MOUNT_POINT_RE = re.compile(
    r"<(?:div|main|section|body)[^>]*\bid=[\"']?"
    r"(?:root|app|__next|__nuxt|react-root|app-root|main)[\"']?[^>]*>"
    r"(?:\s|<!--.*?-->)*</",
    re.IGNORECASE | re.DOTALL,
)

# ``<script>…</script>`` 整段。用于下面那条"内容还在脚本里"的兜底判据。
_SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.IGNORECASE | re.DOTALL)

# 脚本体积至少要有这么多，才拿"脚本主导"当渲染痕迹。
_MIN_SCRIPT_BYTES = 2_000
# 脚本体积要是可读文字的多少倍。取 10 是留足余量：真正把内容放在脚本里的页面（框架数据、
# 首屏 JSON）远超这个比例，而"文字不多但确实是正文"的页面（公告、错误页）根本没多少脚本。
_SCRIPT_TO_TEXT_RATIO = 10

# 框架把首屏数据塞进这些全局里。它们**存在但内容为空/极短**说明服务端没有预渲染。
_DATA_SCRIPT_MARKERS = (
    "__NEXT_DATA__",
    "__NUXT__",
    "__INITIAL_STATE__",
    "__PRELOADED_STATE__",
    "__APOLLO_STATE__",
)

# noscript 里明确要求 JS 的文案（中英）。与 ``blocking`` 的同名判据刻意分开：那里的用途是
# "这是不是一次软封禁"，这里是"这一页要不要渲染"——同一个现象、两个不同的结论，
# 混用会让一边的调整静默改变另一边的行为。
_JS_REQUIRED_MARKERS = (
    "you need to enable javascript",
    "please enable javascript",
    "requires javascript",
    "enable javascript to continue",
    "请开启 javascript",
    "请启用 javascript",
)


def _has_empty_mount_point(html: str) -> bool:
    return _MOUNT_POINT_RE.search(html) is not None


def _has_empty_data_script(html: str) -> bool:
    """框架的数据脚本在、但里面几乎没数据。

    只判"标记存在"是不够的：预渲染过的页面同样有 ``__NEXT_DATA__``，而它带着完整的首屏数据，
    此时再送去做浏览器渲染纯属浪费。
    """
    for marker in _DATA_SCRIPT_MARKERS:
        index = html.find(marker)
        if index < 0:
            continue
        # 取标记之后的一小段看有没有实际数据。"{}" 或 "null" 是空的典型写法。
        window = html[index : index + 120].replace(" ", "")
        if any(payload in window for payload in ('"{}"', "={}", "=null", ':"{}"')):
            return True
    return False


def _scripts_dominate(html: str, text_chars: int) -> bool:
    """页面体积几乎全在脚本里，而可读文字几乎没有——内容还没被渲染进来。

    **这一条是为了兜住"挂载点认不出来"的页面**：框架的挂载点 id 是站点自己起的
    （实测一个用 ``bd``、一个用没加引号的 ``app``），靠穷举 id 认永远会漏。而"页面很大、
    文字几乎没有、体积都在脚本里"这个特征与具体框架无关。

    它不会误伤那些文字很少的正常页面（错误页、公告、"当前没有在招岗位"）：那些页面根本没有
    脚本，或者脚本只有几 KB 而正文是真话。
    """
    script_bytes = sum(len(match.group(0)) for match in _SCRIPT_RE.finditer(html))
    return script_bytes >= max(_MIN_SCRIPT_BYTES, text_chars * _SCRIPT_TO_TEXT_RATIO)


def needs_rendering(html: str) -> bool:
    """这一页要不要靠浏览器渲染才读得到内容。"""
    if not html:
        return False
    text_chars = len(html_to_text(html, max_chars=_MAX_RENDERED_TEXT_CHARS + 1))
    # 先看文字量：够多就直接排除，不必再看痕迹（这条也让它对绝大多数正常页面都是常数级开销）。
    if text_chars > _MAX_RENDERED_TEXT_CHARS:
        return False

    lowered = html.casefold()
    if any(marker in lowered for marker in _JS_REQUIRED_MARKERS):
        return True
    if _has_empty_mount_point(html) or _has_empty_data_script(html):
        return True
    return _scripts_dominate(html, text_chars)


__all__ = ["needs_rendering"]
