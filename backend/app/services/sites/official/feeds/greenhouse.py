"""海外托管型招聘系统：Greenhouse 公开职位板。

**这套系统为什么值得第一个做**：它的公开接口一次返回**全部**岗位，并且在响应里给出总数。
前者意味着没有翻页终止的不确定性，后者意味着对账能直接给出硬结论——"已确认为全量"在这里
是可以被真的证明的，而不是靠推断。第一条适配器用它，正好把对账链路跑通。

两条实测得到的约束，写在这里免得以后有人踩：

1. **``content=true`` 的响应体极大**：大厂的板子解压后能到 30 MB 量级。默认的 3 MB 上限会把
   它截断，而截断在上层会被判成"不可信"，于是每一次采集都变成"无法确认"。所以本适配器显式
   提高上限（``max_bytes``），并且这件事是适配器的知识——只有它知道自己的响应会长这样。
2. **接口分两个区域**（``boards-api…`` 与 ``boards-api.eu.greenhouse…``），同一家公司只会
   落在其中一个。探测因此对每个 token 产生两个候选，由实际请求筛掉不存在的那一个。
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..base import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    FeedHttp,
    FeedJob,
    FeedPage,
    FeedTarget,
    JobFeed,
    ProbeContext,
    ProbeHit,
)
from ..blocking import looks_like_html
from ..html_text import html_to_text
from ..urls import host_label
from .....models.official import BLOCK_NONE, BLOCK_SOFT

logger = logging.getLogger(__name__)

KEY = "greenhouse"
DISPLAY_NAME = "Greenhouse"

# 用户可能直接给的招聘页主机（新版与旧版两套域名都在用）。
BOARD_HOSTS = ("boards.greenhouse.io", "job-boards.greenhouse.io")
# 接口主机。两个区域都要试——同一家公司只会落在其中一个。
API_HOSTS = ("boards-api.greenhouse.io", "boards-api.eu.greenhouse.io")

_API_PATH = "/v1/boards/{token}/jobs"

# 见模块说明第 1 条：这个值是实测约束，不是随手放的宽裕量。
MAX_BYTES = 40_000_000

# JD 正文的截断长度。职位描述偶有超长（含大量排版标记），封顶是为了不让单条岗位
# 挤爆提示词预算；超出部分对"判断岗位是否匹配"没有增量信息。
_MAX_DESCRIPTION_CHARS = 20_000


def extract_board_token(url: str) -> str:
    """从招聘页地址里取出 board token；不是本系统的地址返回空串。

    接受两种形态：``boards.greenhouse.io/<token>`` 与嵌入式的
    ``boards.greenhouse.io/embed/job_board?for=<token>``——生产环境两种都常见。
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold()
    if host not in BOARD_HOSTS:
        return ""
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return ""
    if segments[0] == "embed":
        return (parse_qs(parsed.query).get("for") or [""])[0].strip()
    return segments[0].strip()


def _strip_html(raw: str) -> str:
    """把接口给的正文转成纯文本。

    正文是**被转义过的 HTML**（``&lt;p&gt;``），必须先 ``html.unescape`` 再交给去标记函数，
    否则它看到的是实体而不是标签，会把标记原样留进岗位描述。

    用 ``html_to_text`` 而不是搜索层的 ``extract_text``：后者带"短段落当导航丢弃"的启发式
    （为在整页里*找*正文而设），套在已知就是职位描述的字段上会吃掉短段落。详见
    ``html_text`` 的模块说明。
    """
    if not raw:
        return ""
    return html_to_text(html.unescape(raw), max_chars=_MAX_DESCRIPTION_CHARS)


def _location_name(raw: Any) -> str:
    if isinstance(raw, dict):
        return str(raw.get("name") or "").strip()
    if isinstance(raw, str):
        return raw.strip()
    return ""


def parse_board_payload(payload: Any) -> tuple[list[FeedJob], int | None] | None:
    """解析职位板响应，返回 ``(岗位列表, 总数)``；结构不对返回 ``None``。

    ``None`` 表示"这不是我们认识的响应"，而不是"这里没有岗位"——这两件事在上层的后果完全
    不同（前者是对账里的不可信，后者是一个合法的空结果），所以不能用同一个返回值表达。
    没有 ``jobs`` 数组**不算**空公司：一个真的没有在招岗位的板子会给出 ``"jobs": []``。
    """
    if not isinstance(payload, dict):
        return None
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        return None

    meta = payload.get("meta")
    total: int | None = None
    if isinstance(meta, dict):
        candidate = meta.get("total")
        if isinstance(candidate, int):
            total = candidate

    parsed: list[FeedJob] = []
    for raw_job in jobs:
        if not isinstance(raw_job, dict):
            continue
        title = str(raw_job.get("title") or "").strip()
        if not title:
            continue  # 没有标题的条目不是岗位，跳过而不是编一个占位标题
        parsed.append(
            FeedJob(
                title=title,
                company=str(raw_job.get("company_name") or "").strip(),
                location=_location_name(raw_job.get("location")),
                url=str(raw_job.get("absolute_url") or "").strip(),
                description=_strip_html(str(raw_job.get("content") or "")),
                # 只用明确的"首次发布"时间。``updated_at`` 是修改时间，拿它当发布时间会
                # 让旧岗位看起来是新的——项目既有决策要求发布时间保持原始语义。
                posted_at=str(raw_job.get("first_published") or "").strip(),
                external_id=str(raw_job.get("id") or ""),
                extra={
                    "requisition_id": raw_job.get("requisition_id"),
                    "departments": raw_job.get("departments"),
                    "offices": raw_job.get("offices"),
                    "updated_at": raw_job.get("updated_at"),
                    "language": raw_job.get("language"),
                },
            )
        )
    return parsed, total


class GreenhouseFeed(JobFeed):
    key = KEY
    display_name = DISPLAY_NAME
    board_hosts = BOARD_HOSTS
    provides_total = True
    # 用户给的 boards.greenhouse.io/<token> 本身就证明了这家公司在这套系统上，
    # 此时"0 个岗位"是真实答案而不是识别失败。
    empty_entry_is_conclusive = True

    def __init__(self, *, max_bytes: int = MAX_BYTES) -> None:
        self._max_bytes = max_bytes

    def probe_candidates(self, ctx: ProbeContext) -> list[ProbeHit]:
        """按置信度从高到低给出候选（**不发请求**）。

        三个线索源，按可信度排序：用户直接给的招聘页地址 > 官网首页里出现的招聘页链接 >
        由域名猜。低置信度的候选仍然值得试——猜错只是多一次 404，而猜对能省掉用户很多事。

        每个 token 产生两个候选（两个区域各一个）：同一家公司只会落在其中一个，另一个必然
        是 404，由验证阶段筛掉。这里不做"先猜哪个区域"的优化，因为猜错要重试、代价比多打
        一次 404 更高。
        """
        tokens: list[tuple[str, str, str]] = []
        seen: set[str] = set()

        def _add(token: str, confidence: str, evidence: str) -> None:
            cleaned = token.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                tokens.append((cleaned, confidence, evidence))

        # ① 用户直接给的招聘页地址——最硬的线索，用户就是在这一页上看到的岗位。
        from_url = extract_board_token(ctx.careers_url)
        if from_url:
            _add(from_url, CONFIDENCE_HIGH, f"你提供的招聘页地址指向该系统的 {from_url} 职位板")

        # ② 官网首页里出现的招聘页链接。
        for token in _tokens_in_html(ctx.homepage_html):
            _add(token, CONFIDENCE_MEDIUM, f"官网首页里有指向该系统的招聘链接（{token}）")

        # ③ 域名推测。
        guessed = host_label(ctx.domain)
        if guessed:
            _add(guessed, CONFIDENCE_LOW, f"按域名推测的职位板标识：{guessed}")

        candidates: list[ProbeHit] = []
        for token, confidence, evidence in tokens:
            for host in API_HOSTS:
                candidates.append(
                    ProbeHit(
                        target=FeedTarget(
                            feed_key=KEY,
                            endpoint=f"https://{host}{_API_PATH.format(token=token)}",
                            params={"content": "true"},
                        ),
                        confidence=confidence,
                        evidence=evidence,
                    )
                )
        return candidates

    def probe_rejection_reason(
        self, ctx: ProbeContext, candidate: ProbeHit, page: FeedPage
    ) -> str:
        """Reject a low-confidence domain guess when the board names another company.

        Greenhouse exposes public demo/test boards. A domain-only guess can therefore return a
        valid board for an unrelated company. A user-provided board URL or a link discovered on
        the company's own homepage is stronger evidence and is not second-guessed here.
        """
        if candidate.confidence != CONFIDENCE_LOW or not page.jobs:
            return ""

        expected = {
            _company_key(ctx.company),
            _company_key(ctx.domain),
            _company_key(_board_token(candidate.target.endpoint)),
        }
        expected.discard("")
        if not expected:
            return ""

        observed = {_company_key(job.company) for job in page.jobs if job.company.strip()}
        # 兼容缺少 company_name 的旧响应：没有反证时保留原有识别能力。
        if not observed:
            return ""
        if any(_company_names_match(wanted, actual) for wanted in expected for actual in observed):
            return ""
        return "岗位接口返回的公司名称与当前公司或域名不一致，已忽略这个低置信度猜测"

    async def fetch_page(
        self, http: FeedHttp, target: FeedTarget, *, cursor: str = ""
    ) -> FeedPage:
        """取回整个职位板。``cursor`` 不被使用——这套接口没有分页。"""
        del cursor
        result = await http.request(
            "GET", target.endpoint, params=target.params, max_bytes=self._max_bytes
        )
        if not result.ok:
            return FeedPage(block=result.block, detail=result.detail, status_code=result.status_code)

        payload = result.json()
        if payload is None:
            # 能拿到正文却解析不出 JSON：多半是被 WAF 换成了错误页，而不是"这里没有岗位"。
            hint = "返回的不是 JSON" if not looks_like_html(result.text) else "返回的是一个网页"
            return FeedPage(
                block=BLOCK_SOFT,
                status_code=result.status_code,
                detail=f"接口 {hint}，可能被拦截或接口已改版",
            )

        parsed = parse_board_payload(payload)
        if parsed is None:
            return FeedPage(
                block=BLOCK_SOFT,
                status_code=result.status_code,
                detail="接口响应里没有 jobs 数组，可能接口已改版",
            )

        jobs, total = parsed
        return FeedPage(
            jobs=jobs,
            total_hint=total,
            # 一次返回全部，所以"没有下一页"是接口契约决定的，不是我们数出来的。
            has_more=False,
            cursor="",
            block=BLOCK_NONE,
            status_code=result.status_code,
        )


_TOKEN_IN_HTML_RE = re.compile(
    r"(?:job-)?boards\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


def _board_token(endpoint: str) -> str:
    match = re.search(r"/boards/([^/]+)/jobs(?:\?|$)", endpoint, re.IGNORECASE)
    return match.group(1) if match else ""


def _company_key(value: str) -> str:
    """Normalize a company/domain label for conservative ownership comparison."""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (value or "").casefold())


def _company_names_match(expected: str, observed: str) -> bool:
    if not expected or not observed:
        return False
    if expected == observed:
        return True
    shorter, longer = sorted((expected, observed), key=len)
    return len(shorter) >= 3 and shorter in longer


def _tokens_in_html(markup: str) -> list[str]:
    """从官网首页里找招聘页链接里的 token。"""
    if not markup:
        return []
    return [match.group(1) for match in _TOKEN_IN_HTML_RE.finditer(markup)]


__all__ = [
    "API_HOSTS",
    "BOARD_HOSTS",
    "GreenhouseFeed",
    "MAX_BYTES",
    "extract_board_token",
    "parse_board_payload",
]
