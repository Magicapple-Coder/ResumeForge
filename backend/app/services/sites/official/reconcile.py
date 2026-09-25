"""完整度对账：给一次采集下"到底抓全了没有"的结论。

这是本功能与"普通爬虫"的区别所在。普通爬虫的成功标准是"没报错"，而没报错与抓全是两件事——
一次被 429 截断的采集同样是"没报错"，只是少了一半岗位。

**结论只有三态，不出百分比分数**（与「投递进度不显示百分比」「匹配度分析不显示百分比」
同一取向）：百分比会给出虚假的精确感，而三态各自都有可核对的依据，并且**总是附带依据是什么**。
``无法确认`` 不是含糊其辞，它是一条与"抓全了""没抓全"并列的、有信息量的结论。

两个最容易做错的地方，都在下面的实现里显式处理了：

1. **对总数要用"去重后的取回条数"，不是入库条数。** 已经存在于岗位广场或暂存区的岗位会被
   跳过，但它们**确实被这一次采集抓到了**。用入库条数对总数，会把"命中大量重复"误报成
   "漏抓了大量岗位"——一个会让用户白跑一趟的假警报。
2. **翻页终止是双信号判定。** "没有下一页了"（内容侧）和"被限流了"（传输侧）必须分流：
   前者是"确认到底"，后者是"我们不知道那边还有什么"。把后者读成前者，就是这份报告里最坏的
   那个 bug——它会**自信地报告已确认为全量**。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ....models.official import (
    BLOCK_NOT_FOUND,
    VERDICT_COMPLETE,
    VERDICT_INCOMPLETE,
    VERDICT_UNKNOWN,
    is_transport_failure,
)

# ===== 翻页终止状态 =====

# 内容侧证据表明列表已经走完。
TERMINATION_EXHAUSTED = "exhausted"
# 传输侧失败（限流 / 拒绝 / 超时…）：我们不知道后面还有什么。
TERMINATION_BLOCKED = "blocked"
# 达到页数上限而停下来：**没走完**，不是走完了。
TERMINATION_LIMIT = "limit"
# 达到**用户自己设的条数上限**而停下来。与上面那条同样是"没走完"，单独一个状态只为**让措辞
# 分流**（与 ``TERMINATION_EXHAUSTED_NO_PAGING`` 同一个做法，不改变任何判定）：说成"页数上限"
# 会让设了 20 条的用户去翻一个他根本没碰过的设置——而那个设置确实存在，所以他多半会真去翻。
TERMINATION_JOB_LIMIT = "job_limit"
# 用户手动停止。与"达到上限"分开：一个是工具的边界，一个是用户的决定，
# 报告里必须说清是哪一个，否则用户会以为是自己点错了才少抓的。
TERMINATION_CANCELLED = "cancelled"
# 信号自相矛盾（例如翻页途中接口突然 404，既可能是没有了、也可能是接口改了）。
TERMINATION_CONFLICTED = "conflicted"
# 与 ``TERMINATION_EXHAUSTED`` 是**同一个状态**（都表示"没有更多了"），只是停下来那一级的
# 机制不同：它没有"翻页"这回事，所以说明文字也不同。分成两个常量是为了让措辞能分流，
# **不改变任何判定**。
TERMINATION_EXHAUSTED_NO_PAGING = "exhausted_no_paging"

TERMINATION_DETAILS = {
    TERMINATION_EXHAUSTED: "已翻到列表最后一页",
    # 不翻页的那一级（通用路径）不能照抄上面那句：它从来没有"第几页"的概念，
    # "队列走空"只说明我们跟进完了所有认得出来的链接。说成"已翻到列表最后一页"会让用户
    # 以为这个列表就是全部——那是我们并不知道的事。
    TERMINATION_EXHAUSTED_NO_PAGING: "已跟进完所有认得出来的链接（这一级不翻页，站点也没有声明还有下一页）",
    TERMINATION_BLOCKED: "采集过程中被站点阻断，后面还有什么无从得知",
    TERMINATION_LIMIT: "达到本次采集的页数上限，列表尚未走完",
    # 用户自己设的条数上限。**必须与上面那句分开**：一个是工具的边界、一个是用户的决定，
    # 说成"页数上限"会让设了 20 条的用户去翻一个他根本没碰过的设置——而那个设置确实存在，
    # 所以他多半会真去翻。
    # **这一条是模板**（别处都是成品句子）：条数是用户当场填的，只能现拼。
    TERMINATION_JOB_LIMIT: "达到你设定的条数上限（{limit} 条），列表尚未走完",
    TERMINATION_CANCELLED: "你停止了这次采集，列表尚未走完",
    TERMINATION_CONFLICTED: "翻页信号自相矛盾，无法判断是否已经到底",
}

# ===== 结论依据（决定"已确认为全量"这份把握有多硬）=====

# 站点给出了总数契约（接口的 total 字段），且账目相符——**硬结论**。
EVIDENCE_TOTAL = "total"
# 存在可枚举全集（站点地图），且实抓集合覆盖了它——**硬结论**。
EVIDENCE_ENUMERATED = "enumerated"
# 无总数契约，靠"每页解析出的条数与列表页自称条数一致 + 已翻到最后一页"——**软结论**。
EVIDENCE_LIST = "list"
# 没有任何可比对的依据。
EVIDENCE_NONE = "none"

EVIDENCE_LABELS = {
    EVIDENCE_TOTAL: "站点接口给出的总数",
    EVIDENCE_ENUMERATED: "站点地图可枚举的岗位页（差额需逐条核实）",
    EVIDENCE_LIST: "列表页自称条数与翻页终止",
    EVIDENCE_NONE: "无",
}

# 报告里最多列出多少条待核实地址。站点地图的差额可能上千条，全列出来既撑爆响应也没人看得完；
# 但**计数是完整的**（``missing``），只是明细截断——两者分开才能既不误导也不爆炸。
MAX_CANDIDATE_URLS = 200


@dataclass(frozen=True)
class Termination:
    state: str
    detail: str


def classify_termination(
    *,
    blocks: tuple[str, ...],
    reached_page_limit: bool = False,
    job_limit: int = 0,
    last_has_more: bool = False,
    cancelled: bool = False,
    paginates: bool = True,
) -> Termination:
    """判定翻页为什么停下来。

    顺序即优先级：**传输侧失败排在最前**。一次采集既被限流又恰好翻到最后一页时，必须先说
    "被阻断"，否则后面那条"到底了"会把结论带偏。
    """
    if any(is_transport_failure(block) for block in blocks):
        return Termination(TERMINATION_BLOCKED, TERMINATION_DETAILS[TERMINATION_BLOCKED])

    if cancelled:
        return Termination(TERMINATION_CANCELLED, TERMINATION_DETAILS[TERMINATION_CANCELLED])

    # 第 2 页起出现 404：可能是"没有下一页"，也可能是"接口改了"。两种含义的后果差别极大
    # （前者说明抓完了，后者说明从这一页起全丢了），所以不猜，报矛盾。
    if any(block == BLOCK_NOT_FOUND for block in blocks[1:]):
        return Termination(TERMINATION_CONFLICTED, TERMINATION_DETAILS[TERMINATION_CONFLICTED])

    # 用户设的条数上限**排在页数上限前面**：两个都命中时（正好抓够最后一条、同时翻到页数顶），
    # 说实话的那个是"你设的条数到了"——页数上限只是恰好也到顶，不是这次停下来的原因。
    if job_limit > 0:
        return Termination(
            TERMINATION_JOB_LIMIT,
            TERMINATION_DETAILS[TERMINATION_JOB_LIMIT].format(limit=job_limit),
        )

    if reached_page_limit:
        return Termination(TERMINATION_LIMIT, TERMINATION_DETAILS[TERMINATION_LIMIT])

    if last_has_more:
        # 站点说还有下一页，而我们没继续取——同样属于"没走完"。
        return Termination(TERMINATION_LIMIT, TERMINATION_DETAILS[TERMINATION_LIMIT])

    if not paginates:
        # 这一级没有"翻页"这回事（见 ``JobFeed.paginates``）：说"已翻到列表最后一页"会让用户
        # 以为这个列表就是全部，而我们其实只知道自己跟进完了所有认得出来的链接。
        return Termination(
            TERMINATION_EXHAUSTED_NO_PAGING,
            TERMINATION_DETAILS[TERMINATION_EXHAUSTED_NO_PAGING],
        )
    return Termination(TERMINATION_EXHAUSTED, TERMINATION_DETAILS[TERMINATION_EXHAUSTED])


@dataclass
class ReconcileInput:
    """对账的输入账目。由采集编排层填写。"""

    # 站点接口给出的总数锚点；None = 该站点没有这个契约。
    total_hint: int | None = None
    # **去重后的取回条数**——对总数比的是它，不是入库条数（见模块说明第 1 条）。
    collected: int = 0
    # 其中新入库 / 因重复跳过 / 因在回收站而跳过。
    stored: int = 0
    skipped: int = 0
    # 每次取回的阻断分类，按发生顺序。
    blocks: tuple[str, ...] = ()
    reached_page_limit: bool = False
    # 用户这次设的条数上限（0 = 没设）。**它的值本身要进这份账目**：结论的措辞里带着这个数，
    # 而存活校验之后是拿这份账目**原样重算**的——不存下来的话，重算出来的话会变成另一句。
    job_limit: int = 0
    last_has_more: bool = False
    # 用户手动停止。与 reached_page_limit 分开，报告里要能区分"工具的边界"和"你的决定"。
    cancelled: bool = False
    # 中止的具体原因（例如"接口不存在（HTTP 404）"）。**一条都没抓到时用它当结论**：
    # 那种情况下"站点既没有总数、列表页也没有条数可比对"虽然是事实，却答非所问——
    # 用户要的是"为什么什么都没拿到"。
    stop_detail: str = ""
    # 每页的 ``(实际解析出的条数, 列表页自称条数)``；自称条数拿不到时为 None。
    page_counts: tuple[tuple[int, int | None], ...] = ()
    # ===== 集合对账的输入 =====
    #
    # 这一层要的其实只有"差额"这一个量，所以输入就是差额本身，而不是那两个集合。
    # **这样活着校验之后可以直接用存储的输入重算结论**，不必在别处再写一遍判定逻辑——
    # 两处判定必然漂移，而漂移在这里的表现是"同一份账目，两次算出不同结论"。
    #
    # ``enumerated_total`` 是可枚举全集的规模（0 = 这一层不参与对账）；
    # ``candidates`` 是其中**实抓没有**的那些地址。
    enumerated_total: int = 0
    candidates: frozenset[str] = frozenset()
    # 差额是否被截断到上限。**截断时永远给不出"已确认为全量"**：看不见的候选没法核实，
    # 而"没法核实"正是不能下硬结论的原因。
    enumerated_truncated: bool = False
    # 采集那一级有没有"翻页"这回事。**只影响措辞，不影响任何判定**——它决定「翻页终止」
    # 那一行是说"已翻到列表最后一页"还是"已跟进完所有认得出来的链接"。
    paginates: bool = True
    # 本次是否按用户给的关键词筛选。筛选后的数量不能与站点全站总数对账。
    job_filter: str = ""
    # 逐条**核实过**的候选地址（存活校验的产物）。
    #
    # **这是把"待核实"变成硬结论的唯一途径**：``verified_gone`` 里的地址确实已下架，
    # ``verified_live`` 里的确实还在招。没核实过的候选只能让结论停在"无法确认"——
    # 因为"地图里有而我们没抓到"这句话本身分不出漏抓与已下架。
    verified_gone: frozenset[str] = frozenset()
    verified_live: frozenset[str] = frozenset()


def input_to_dict(data: ReconcileInput) -> dict[str, Any]:
    """把对账输入序列化下来，供**事后重放**。

    存活校验之后要重算结论，而重算必须用**原来的账目**——从运行记录里反推
    （"终止状态是 limit，所以 reached_page_limit 应该是 True"）既脆弱又会悄悄偏离原值。
    存下来原样重放是唯一不会漂移的做法。

    集合字段统一转成**排序后的列表**：JSON 没有集合，而顺序不定的列表会让同一份输入产生
    两次不同的序列化结果，既影响可读性，也让"输入没变"这件事无法比对。
    """
    return {
        "total_hint": data.total_hint,
        "collected": data.collected,
        "stored": data.stored,
        "skipped": data.skipped,
        "blocks": list(data.blocks),
        "reached_page_limit": data.reached_page_limit,
        "job_limit": data.job_limit,
        "last_has_more": data.last_has_more,
        "page_counts": [list(item) for item in data.page_counts],
        "cancelled": data.cancelled,
        "stop_detail": data.stop_detail,
        "enumerated_total": data.enumerated_total,
        "candidates": sorted(data.candidates),
        "enumerated_truncated": data.enumerated_truncated,
        "paginates": data.paginates,
        "job_filter": data.job_filter,
        "verified_gone": sorted(data.verified_gone),
        "verified_live": sorted(data.verified_live),
    }


def input_from_dict(payload: dict[str, Any]) -> ReconcileInput:
    """``input_to_dict`` 的逆操作。缺字段一律按默认值处理，不抛异常。

    容错是必需的：运行记录可能是**旧版本**写下的，那时还没有某个字段。让存量数据读不出来，
    比让结论保守一点糟得多。
    """
    raw_counts = payload.get("page_counts") or []
    counts: list[tuple[int, int | None]] = []
    for item in raw_counts:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            counts.append((int(item[0]), item[1] if item[1] is None else int(item[1])))
    return ReconcileInput(
        total_hint=payload.get("total_hint"),
        collected=int(payload.get("collected") or 0),
        stored=int(payload.get("stored") or 0),
        skipped=int(payload.get("skipped") or 0),
        blocks=tuple(payload.get("blocks") or ()),
        reached_page_limit=bool(payload.get("reached_page_limit")),
        # 旧记录没有这个字段：按 0（"没设上限"）恢复，措辞与加它之前一致。
        job_limit=int(payload.get("job_limit") or 0),
        last_has_more=bool(payload.get("last_has_more")),
        page_counts=tuple(counts),
        cancelled=bool(payload.get("cancelled")),
        stop_detail=str(payload.get("stop_detail") or ""),
        enumerated_total=int(payload.get("enumerated_total") or 0),
        candidates=frozenset(payload.get("candidates") or ()),
        enumerated_truncated=bool(payload.get("enumerated_truncated")),
        # 旧记录没有这个字段：按 ``True``（"有翻页"）恢复，措辞与加它之前一致。
        paginates=bool(payload.get("paginates", True)),
        job_filter=str(payload.get("job_filter") or ""),
        verified_gone=frozenset(payload.get("verified_gone") or ()),
        verified_live=frozenset(payload.get("verified_live") or ()),
    )


@dataclass
class ReconcileReport:
    verdict: str
    evidence: str
    # 一句话结论，直接展示给用户。
    headline: str
    # 依据说明：为什么是这个结论。
    basis: str = ""
    # 已确认的差额条数（结论为"已确认不全"时有值）。
    missing: int = 0
    # **待核实的候选**（站点地图里有、我们没抓到的岗位页地址）。
    #
    # 与 ``missing`` 的区别就是"已确认"与"待核实"的区别：``missing`` 是账目上确凿的差额
    # （站点声明 47、我们只有 20），而这里是**含义尚未确定**的一批地址——可能是漏抓，
    # 也可能是站点地图里早就招满、URL 还在的历史岗位。逐个访问才能区分。
    candidates: list[str] = field(default_factory=list)
    termination: Termination | None = None
    # 逐层明细，供报告页展开。
    layers: list[dict[str, object]] = field(default_factory=list)


def _drift_pages(page_counts: tuple[tuple[int, int | None], ...]) -> list[int]:
    """返回"解析出的条数与列表页自称不符"的页码（从 1 开始）。

    有自称条数的页**必须**逐页核对：一整页只解析出 3 条而页面写着 20 条，说明选择器已经开始
    失效。这类漂移不会报错，只会静默少数据——正是对账要抓的东西。
    """
    drifted: list[int] = []
    for index, (parsed, claimed) in enumerate(page_counts, start=1):
        if claimed is not None and claimed != parsed:
            drifted.append(index)
    return drifted


def reconcile(data: ReconcileInput) -> ReconcileReport:
    """给一次采集下对账结论。"""
    termination = classify_termination(
        blocks=data.blocks,
        reached_page_limit=data.reached_page_limit,
        job_limit=data.job_limit,
        last_has_more=data.last_has_more,
        cancelled=data.cancelled,
        paginates=data.paginates,
    )
    layers: list[dict[str, object]] = [
        {
            "layer": "termination",
            "label": "翻页终止",
            "detail": termination.detail,
        }
    ]

    # 关键词筛选改变了分母：站点接口/站点地图给的是全站岗位，而用户只要求其中一部分。
    # 这时即便翻完了所有列表页，也只能证明"筛选路径走完了"，不能把筛选结果冒充全站完整度。
    if data.job_filter:
        layers.append(
            {
                "layer": "filter",
                "label": "岗位筛选",
                "detail": (
                    f"本次按关键词「{data.job_filter}」筛选；站点总数是全站口径，"
                    "不能与筛选后的条数直接比较"
                ),
            }
        )
        return ReconcileReport(
            verdict=VERDICT_UNKNOWN,
            evidence=EVIDENCE_NONE,
            headline=(
                f"无法确认：本次按关键词「{data.job_filter}」筛选，"
                "筛选结果不能证明全站岗位已经抓全"
            ),
            basis=EVIDENCE_LABELS[EVIDENCE_NONE],
            termination=termination,
            layers=layers,
        )

    # ===== 集合对账（有可枚举全集时）=====
    #
    # **这一层的差额不是确凿的漏抓数，这一点必须说清楚**：站点地图里会有早就招满、URL 却还
    # 留着的岗位。所以"地图里有 N 个没抓到"既可能是我们漏了，也可能是那些岗位已经下架——
    # **不逐个访问就无法区分**。把它报成"已确认不全：差 N 条"就是把不确定说成了确定，
    # 而那正是本模块最不能犯的错。
    #
    # 因此这里的产出是「无法确认 + 一批待核实的候选地址」，逐条核实（下架 / 仍在招）之后
    # 才能升级成硬结论——那是存活校验那一层的活。
    if data.enumerated_total > 0:
        missing_urls = data.candidates
        still_live = missing_urls & data.verified_live
        gone = missing_urls & data.verified_gone
        unverified = missing_urls - still_live - gone
        layers.append(
            {
                "layer": "enumerated",
                "label": "集合对账",
                "detail": (
                    f"站点地图可枚举 {data.enumerated_total} 个岗位页，"
                    f"其中 {len(missing_urls)} 个没有抓到"
                    + ("（明细已截断）" if data.enumerated_truncated else "")
                    + (f"；已核实：{len(gone)} 个已下架、{len(still_live)} 个仍在招"
                       if gone or still_live else "")
                ),
            }
        )

        # ① 核实出**仍在招**却没抓到的：这是确凿的漏抓，可以给出硬结论。
        if still_live:
            return ReconcileReport(
                verdict=VERDICT_INCOMPLETE,
                evidence=EVIDENCE_ENUMERATED,
                headline=(
                    f"已确认不全：核实到 {len(still_live)} 个岗位页仍在招聘，但这次没有抓到"
                ),
                basis=EVIDENCE_LABELS[EVIDENCE_ENUMERATED],
                missing=len(still_live),
                candidates=sorted(still_live)[:MAX_CANDIDATE_URLS],
                termination=termination,
                layers=layers,
            )

        # ② 差额**全部**核实为已下架：差额被完全解释掉了，这才是硬结论。
        # **截断时不给这个结论**——看不见的候选没法核实，"没核实"正是不能下硬结论的原因。
        if missing_urls and not unverified and not data.enumerated_truncated:
            # **但集合层不能压过总量层。** 站点声明的总数是另一份硬证据，两者对不上时
            # 至少有一份是错的：集合层只解释了它自己看得见的那批差额，而总量层说还差
            # ``total_hint - collected`` 条。这时报"已确认为全量"就是把用户往最危险的方向引
            # ——他会以为没有漏掉岗位。
            #
            # 这一条是被审查找出来的：源同时有总数契约与一批早已失效的站点地图地址时，
            # "差额全部核实为已下架"会让报告宣称抓全了，而账目明明是 2/200。
            if data.total_hint is not None and data.collected != data.total_hint:
                layers.append(
                    {
                        "layer": "conflict",
                        "label": "两层证据冲突",
                        "detail": (
                            f"站点声明 {data.total_hint} 条、实际抓到 {data.collected} 条，"
                            f"而站点地图里的差额（{len(missing_urls)} 个）已核实为全部下架；"
                            "两份硬证据对不上，无法判断哪一份更准"
                        ),
                    }
                )
                return ReconcileReport(
                    verdict=VERDICT_UNKNOWN,
                    evidence=EVIDENCE_ENUMERATED,
                    headline=(
                        f"无法确认：站点声明 {data.total_hint} 条、只抓到 {data.collected} 条，"
                        "而站点地图里的差额都已下架——两份证据对不上"
                    ),
                    basis=EVIDENCE_LABELS[EVIDENCE_ENUMERATED],
                    termination=termination,
                    layers=layers,
                )
            return ReconcileReport(
                verdict=VERDICT_COMPLETE,
                evidence=EVIDENCE_ENUMERATED,
                headline=(
                    f"已确认为全量：站点地图里的 {len(missing_urls)} 个差额都是已下架的岗位"
                ),
                basis=EVIDENCE_LABELS[EVIDENCE_ENUMERATED],
                termination=termination,
                layers=layers,
            )

        # ③ 还有没核实的差额：结论停在"无法确认"，并把它列为待核实候选。
        if unverified:
            layers.append(
                {
                    "layer": "verification",
                    "label": "存活校验",
                    "detail": (
                        f"已核实 {len(gone) + len(still_live)} 个，"
                        f"仍有 {len(unverified)} 个未核实；未核实的差额分不出漏抓与已下架"
                    ),
                }
            )
            return ReconcileReport(
                verdict=VERDICT_UNKNOWN,
                evidence=EVIDENCE_ENUMERATED,
                headline=(
                    f"无法确认：站点地图里有 {len(unverified)} 个岗位页没抓到，"
                    "需要核实它们是漏抓还是已经下架"
                ),
                basis=EVIDENCE_LABELS[EVIDENCE_ENUMERATED],
                missing=len(unverified),
                candidates=sorted(unverified)[:MAX_CANDIDATE_URLS],
                termination=termination,
                layers=layers,
            )

        # ④ 差额明细被截断，而看得见的那些都核实过了：**仍然不能下硬结论**。
        # 看不见的候选没法核实，"没核实"正是不能下硬结论的原因——这里最容易顺手写成
        # "已确认为全量"，而那是拿不确定冒充确定。
        if data.enumerated_truncated and missing_urls:
            layers.append(
                {
                    "layer": "verification",
                    "label": "存活校验",
                    "detail": (
                        f"已核实 {len(gone) + len(still_live)} 个，"
                        "但差额明细被截断，仍有未见过的候选未能核实"
                    ),
                }
            )
            return ReconcileReport(
                verdict=VERDICT_UNKNOWN,
                evidence=EVIDENCE_ENUMERATED,
                headline="无法确认：差额明细被截断，未能核实全部候选",
                basis=EVIDENCE_LABELS[EVIDENCE_ENUMERATED],
                termination=termination,
                layers=layers,
            )

        # 覆盖了站点地图全集：这是一条**正向证据**，但不足以单独下"已确认为全量"——
        # 站点地图自己也可能不全。继续往下走其它层。
        layers.append(
            {
                "layer": "enumerated",
                "label": "集合对账",
                "detail": "站点地图里的岗位页一个不落，但站点地图本身未必完整",
            }
        )

    # ===== 总量对账（站点给出总数契约时，这是硬结论）=====
    if data.total_hint is not None:
        layers.append(
            {
                "layer": "total",
                "label": "总量对账",
                "detail": f"站点声明 {data.total_hint} 条，实际抓到 {data.collected} 条",
            }
        )
        if data.collected == data.total_hint:
            return ReconcileReport(
                verdict=VERDICT_COMPLETE,
                evidence=EVIDENCE_TOTAL,
                headline=f"已确认为全量：站点声明的 {data.total_hint} 条岗位全部抓到",
                basis=EVIDENCE_LABELS[EVIDENCE_TOTAL],
                termination=termination,
                layers=layers,
            )
        missing = max(data.total_hint - data.collected, 0)
        # 抓到的比声明的还多：不是"多抓了"，而是总数锚点与列表不是同一口径（例如总数含已关闭
        # 岗位、或列表接口按条件过滤过）。如实说明，不当成正常。
        if missing == 0:
            layers.append(
                {
                    "layer": "total",
                    "label": "口径提示",
                    "detail": "抓到的条数多于站点声明的总数，两者可能不是同一口径",
                }
            )
            return ReconcileReport(
                verdict=VERDICT_UNKNOWN,
                evidence=EVIDENCE_TOTAL,
                headline="无法确认：抓到的条数多于站点声明的总数，两者口径不一致",
                basis=EVIDENCE_LABELS[EVIDENCE_TOTAL],
                termination=termination,
                layers=layers,
            )
        return ReconcileReport(
            verdict=VERDICT_INCOMPLETE,
            evidence=EVIDENCE_TOTAL,
            headline=f"已确认不全：站点声明 {data.total_hint} 条，实际只抓到 {data.collected} 条",
            basis=EVIDENCE_LABELS[EVIDENCE_TOTAL],
            missing=missing,
            termination=termination,
            layers=layers,
        )

    # ===== 列表对账（软结论：只在与翻页终止一致时才敢下结论）=====
    drifted = _drift_pages(data.page_counts)
    if drifted:
        layers.append(
            {
                "layer": "list",
                "label": "列表对账",
                "detail": f"第 {', '.join(str(page) for page in drifted)} 页解析出的条数与页面自称不符",
            }
        )
        return ReconcileReport(
            verdict=VERDICT_UNKNOWN,
            evidence=EVIDENCE_LIST,
            headline="无法确认：部分页解析出的条数与页面自称不符，可能有岗位没解析出来",
            basis=EVIDENCE_LABELS[EVIDENCE_LIST],
            termination=termination,
            layers=layers,
        )

    has_claimed = any(claimed is not None for _, claimed in data.page_counts)
    if (
        termination.state == TERMINATION_EXHAUSTED
        and has_claimed
        and data.paginates
    ):
        layers.append(
            {
                "layer": "list",
                "label": "列表对账",
                "detail": "每页解析出的条数与页面自称一致，且已翻到最后一页",
            }
        )
        return ReconcileReport(
            verdict=VERDICT_COMPLETE,
            evidence=EVIDENCE_LIST,
            headline=f"已确认为全量：翻到最后一页，{data.collected} 条岗位每页都对得上",
            basis=EVIDENCE_LABELS[EVIDENCE_LIST],
            termination=termination,
            layers=layers,
        )

    # ===== 没有可比对的依据 =====
    if data.collected == 0 and data.stop_detail:
        # 一条都没拿到时，最有用的结论是**为什么**，而不是"没有依据可比对"。
        headline = f"无法确认：{data.stop_detail}"
    elif termination.state != TERMINATION_EXHAUSTED:
        headline = f"无法确认：{termination.detail}"
    elif not has_claimed:
        headline = "无法确认：站点既没有总数，列表页也没有条数可比对"
    else:
        headline = "无法确认：缺少可核对的依据"

    return ReconcileReport(
        verdict=VERDICT_UNKNOWN,
        evidence=EVIDENCE_NONE,
        headline=headline,
        basis=EVIDENCE_LABELS[EVIDENCE_NONE],
        termination=termination,
        layers=layers,
    )


__all__ = [
    "EVIDENCE_ENUMERATED",
    "EVIDENCE_LABELS",
    "MAX_CANDIDATE_URLS",
    "EVIDENCE_LIST",
    "EVIDENCE_NONE",
    "EVIDENCE_TOTAL",
    "TERMINATION_BLOCKED",
    "TERMINATION_CANCELLED",
    "TERMINATION_CONFLICTED",
    "TERMINATION_DETAILS",
    "TERMINATION_EXHAUSTED",
    "TERMINATION_LIMIT",
    "ReconcileInput",
    "ReconcileReport",
    "Termination",
    "classify_termination",
    "input_from_dict",
    "input_to_dict",
    "reconcile",
]
