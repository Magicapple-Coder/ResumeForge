"""BOSS 直聘的接口响应解析：从 XHR 响应体里取出岗位列表与详情。

**为什么值得单独做一条路**：BOSS 的岗位列表是滚动加载的 XHR 渲染出来的，DOM 里能拿到的
只有标题、公司、薪资、地点四个字段（还是渲染后的文本）；接口返回的 JSON 里还有
经验、学历、技能标签、HR 活跃状态、岗位描述全文。同时，DOM 解析要等渲染完成，接口响应则在
数据到达时就有了，不受首屏快慢影响——**今天真正在用的就是这一条**：详情页的完整 JD
（DOM 只给渲染后的摘要）与不受字体反爬影响的薪资文本。

接口多出来的结构化字段走 ``extra``（见 ``base.SearchResult.extra``）。它们**目前还没有
下游消费者**：``Job`` 模型没有对应的列，采集器只取 title/company/location/salary/url。
留在这里是因为这些字段只有接口这条路拿得到，丢掉就再也拿不回来了；接匹配度分析与
HR 活跃过滤时再从 ``extra`` 取。

**失败一律返回 None**：调用方据此**退回 DOM 解析**。接口路径变了、被风控换了、
返回了意料之外的结构——这些都不该让一次采集失败，只是"没走上快路"而已。所以这里
绝不抛异常，只安静地返回 None。
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

from .boss_text import normalize_text, split_job_sections, split_title_salary

logger = logging.getLogger(__name__)

# 接口路径里用来识别"这是岗位列表 / 岗位详情"的片段。
SEARCH_MARKER = "/wapi/zpgeek/search/joblist.json"
DETAIL_MARKER = "/wapi/zpgeek/job/detail.json"

# 宽松候选：站点给接口路径加版本后缀、改一段命名（`joblist.json` → `joblistV2.json`）时，
# 只认整串路径会让网络这条路**整体失效**（而它的失败方式是静默退回 DOM）。
# 因此同时接受几个更短的片段，最终由结构判定（`looks_like_search` / `looks_like_detail`）把关：
# URL 宽松 + 结构严格，比"路径写死"既稳又不至于取错数据。
SEARCH_MARKERS = (SEARCH_MARKER, "/search/joblist", "joblist")
DETAIL_MARKERS = (DETAIL_MARKER, "/job/detail", "job/detail")

# 接口里的薪资是数字（单位：元/月，或天）。超过这个数就当作"按天"而不是"按月"，
# 因为月薪几十万在实习与校招场景里几乎不存在，而日薪 300~800 很常见。
_DAILY_SALARY_THRESHOLD = 3000
_MAX_TITLE_CHARS = 200
_MAX_TEXT_CHARS = 20_000


def _text(value: Any, limit: int = _MAX_TITLE_CHARS) -> str:
    """取一段文本：先还原反爬混淆，再截断。

    **顺序不能反**：混淆字符（``boss`` 水印、康熙部首）也占长度，先截断会把还没还原的内容
    切掉半个，之后无论怎么清洗都补不回来。
    """
    return normalize_text(value)[:limit]


def _strip_html(value: Any, limit: int = _MAX_TEXT_CHARS) -> str:
    """把接口返回的带标签文本转成纯文本。

    岗位描述在接口里是 HTML 片段（``<br>``、``<p>``）。直接塞进 JD 里会让匹配分析
    与关键词提取读到一堆标签，所以这里把标签换成换行并压掉多余空行。
    最后再过一遍反爬还原（水印 token / 部首 / 私用区数字）——真实数据里 JD 正文被塞了
    ``boss`` / ``kanzhun`` / ``直聘`` 三种水印，不清掉会一路进到匹配分析里。
    """
    raw = str(value if value is not None else "")
    if not raw:
        return ""
    # 块级标签当换行，其余标签直接去掉。
    text = re.sub(r"<\s*(br|/p|/div|/li)\s*/?\s*>", "\n", raw, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return normalize_text(text)[:limit]


def format_salary(low: Any, high: Any, months: Any = None) -> str:
    """把接口里的薪资数字格式化成界面上那种可读写法。

    接口给的是月薪元数（``20000``）或日薪（``300``）。这里输出 ``20-40K`` /
    ``300-500元/天`` / ``20-40K·16薪``，与站点上显示的口径一致——用户能一眼对上自己
    在页面上看到的那一条。拿不到数字时返回空串，**不要编一个**。
    """
    try:
        low_value = int(low) if low is not None else 0
        high_value = int(high) if high is not None else 0
    except (TypeError, ValueError):
        return ""
    if low_value <= 0 and high_value <= 0:
        return ""
    if low_value <= 0:
        low_value = high_value
    if high_value <= 0:
        high_value = low_value

    if high_value <= _DAILY_SALARY_THRESHOLD:
        base = f"{low_value}-{high_value}元/天"
    else:
        low_k = round(low_value / 1000)
        high_k = round(high_value / 1000)
        base = f"{low_k}K" if low_k == high_k else f"{low_k}-{high_k}K"
        try:
            month_count = int(months) if months is not None else 0
        except (TypeError, ValueError):
            month_count = 0
        if 12 < month_count <= 24:
            base = f"{base}·{month_count}薪"
    return base


def _skill_tags(values: Any) -> list[str]:
    """技能标签去重并保序。

    接口里同一个技能会出现多次（不同维度命中同一标签），原样存下来会让标签栏重复，
    也会让"技能匹配"重复计数。
    """
    result: list[str] = []
    if not isinstance(values, list):
        return result
    for item in values:
        if isinstance(item, dict):
            item = item.get("name") or item.get("tagName") or item.get("skillName")
        tag = _text(item, 40)
        if tag and tag not in result:
            result.append(tag)
    return result[:12]


def _int_or_none(value: Any) -> int | None:
    """接口里的数字字段：解不出来返回 ``None``，绝不编一个 0（那会被下游当成"月薪 0 元"）。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _data_container(payload: Any) -> dict[str, Any] | None:
    """只认 BOSS 自己的 ``zpData`` 容器。

    **不接受的泛化名字（``data`` / ``result``）是有意的**，不是漏了：这两个词太通用，
    而 `looks_like_search` 是"在页面发出的几十个响应里挑一个"的判据——放宽容器名会让
    无关接口的响应也被判成岗位列表。容器改名时返回 ``None``，上层据此**明确按"抓不到"
    处理并退回 DOM**（DOM 那条路照样能采到岗位，只是字段少些），比赌一个泛化键安全。
    """
    if not isinstance(payload, dict):
        return None
    value = payload.get("zpData")
    return value if isinstance(value, dict) else None


def api_error(payload: Any) -> tuple[str, str] | None:
    """返回 BOSS 明确给出的非零错误码；无错误码或成功响应返回 ``None``。"""
    if not isinstance(payload, dict) or "code" not in payload:
        return None
    code = _text(payload.get("code"), 40)
    if code in {"", "0"}:
        return None
    message = _text(
        payload.get("message") or payload.get("msg") or payload.get("zpMessage"), 500
    )
    return code, message


def _looks_like_job_item(item: dict[str, Any]) -> bool:
    title = _first(item, "jobName", "jobTitle", "positionName", "title")
    if not _text(title):
        return False
    identity_keys = {
        "encryptJobId",
        "encryptId",
        "brandName",
        "companyName",
        "cityName",
        "areaName",
        "lowSalary",
        "salaryMin",
        "salaryDesc",
    }
    return any(key in item for key in identity_keys)


def _job_url(item: dict[str, Any], job_id: str) -> str:
    raw = _text(_first(item, "jobUrl", "jobHref", "detailUrl", "url"), 1000)
    if raw:
        return urljoin("https://www.zhipin.com/", raw)
    return f"https://www.zhipin.com/job_detail/{job_id}.html" if job_id else ""


def _job_items(payload: Any) -> list[dict[str, Any]]:
    """取 ``zpData.jobList`` 这个位置的岗位数组；结构不认识时返回空列表。

    容器与键都**只认 BOSS 自己的名字**：改名即视为"结构不认识"，由调用方返回 ``None``
    并退回 DOM。返回空列表而不是报错是不行的——那会被上层说成"这次真的没搜到"，
    用户于是以为关键词太窄（见 ``parse_search_response`` 的说明）。
    """
    data = _data_container(payload)
    if data is None:
        return []
    items = data.get("jobList")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def parse_search_response(payload: Any) -> list[dict[str, Any]] | None:
    """解析岗位列表响应 → ``[{title, company, location, salary, url, source, extra}]``。

    结构与 DOM 采集脚本的产出**逐字段对齐**（``title`` / ``company`` / ``location`` /
    ``salary`` / ``url``），这样上层拿到哪条路来的结果都一样处理；接口多出来的字段
    放进 ``extra``（见 ``base.SearchResult.extra`` 的说明）。
    """
    items = _job_items(payload)
    if not items:
        # 空列表也可能是真的没搜到——但那由上层结合页面状态判断，这里只说"没解析出东西"。
        return None

    results: list[dict[str, Any]] = []
    untitled = 0
    for item in items:
        job_id = _text(_first(item, "encryptJobId", "encryptId", "jobId"))
        # BOSS 的详情页地址可以从 encryptJobId 拼出来；拼不出来时留空，
        # 上层会退回"点开卡片拿 href"那条路。
        url = _job_url(item, job_id)
        # 岗位名与薪资在**接口里也可能粘在一起**（新版列表把两者放在同一个节点里），
        # 所以统一过一遍拆分：标题只留岗位名；拆出来的薪资只在接口没给数字时兜底。
        title, title_salary = split_title_salary(
            _first(item, "jobName", "jobTitle", "positionName", "title")
        )
        if not title:
            # **读不出岗位名的卡片不算一条结果**。这一条是"站点改版"的报警器：
            # 卡片内字段一旦改名（`jobName` → 别的名字），以前会安静地解析出 `title=""` 的
            # "岗位"——上层看到的是"采到了 N 条"，而数据是废的，用户既不报错也拿不到东西。
            # 全空卡片同理（例如接口把列表多套了一层，每个 item 变成 `{"jobList": [...]}`）。
            untitled += 1
            continue
        results.append(
            {
                "title": title,
                # 公司名**只从 `brandName` 取**。读不出来就留空串，而不是退到别的键或默认值：
                # 这张卡片的价值在岗位名，公司名缺了不该把卡片丢掉，但也不该由一个相似的名字
                # 顶上来（"不为缺失的字段编造内容"，见 test_site_contract_drift 的断言）。
                "company": _text(item.get("brandName")),
                "location": _text(
                    _first(item, "cityName", "areaDistrict", "areaName", "locationName")
                ),
                # 优先用数字字段拼出来（口径统一），拼不出来时才用接口给的展示文本。
                "salary": format_salary(
                    _first(item, "lowSalary", "salaryLow", "salaryMin"),
                    _first(item, "highSalary", "salaryHigh", "salaryMax"),
                    _first(item, "salaryMonth", "salaryMonths"),
                )
                or _text(_first(item, "salaryDesc", "salaryText", "salary"))
                or title_salary,
                "url": url,
                "extra": {
                    "encrypt_job_id": job_id,
                    "encrypt_boss_id": _text(
                        _first(item, "encryptBossId", "encryptRecruiterId")
                    ),
                    "experience": _text(
                        _first(item, "jobExperience", "experienceName", "experience")
                    ),
                    "degree": _text(_first(item, "jobDegree", "degreeName", "education")),
                    "industry": _text(_first(item, "brandIndustry", "industryName")),
                    "scale": _text(_first(item, "brandScaleName", "companyScale")),
                    "stage": _text(_first(item, "brandStageName", "financingStage")),
                    "skills": _skill_tags(_first(item, "skills", "skillList")),
                    "hr_active": _text(_first(item, "bossOnline", "recruiterOnline"))
                    == "true"
                    or _text(_first(item, "bossActiveTimeDesc", "activeDesc")),
                    # 原始数字（元/月）：界面上的"15-25K"是格式化结果，做薪资区间筛选要原始值。
                    "salary_low": _int_or_none(
                        _first(item, "lowSalary", "salaryLow", "salaryMin")
                    ),
                    "salary_high": _int_or_none(
                        _first(item, "highSalary", "salaryHigh", "salaryMax")
                    ),
                },
            }
        )
    if not results:
        # `jobList` 在、但里面的卡片一条也读不出岗位名 → 这是**结构不认识**，不是"真的没搜到"。
        # 返回 None 让上层按"抓不到"处理（会明确报出来、并退回 DOM 那条路），
        # 而不是拿一堆空标题的卡片去假装采到了岗位。
        if untitled:
            logger.warning(
                "岗位列表结构不认识：%s 条卡片都读不出岗位名（字段可能被改名），已按抓不到处理",
                untitled,
            )
        return None
    if untitled:
        # 部分卡片读不出来：保留能用的那部分（宁多勿少），但把丢了几条记下来便于排障。
        logger.warning("岗位列表里有 %s 条卡片没有岗位名，已跳过（可能站点改了字段）", untitled)
    return results


def parse_detail_response(payload: Any) -> dict[str, Any] | None:
    """解析岗位详情响应 → ``{job_title, company, description, requirements, url, extra}``。

    接口详情比 DOM 多出的是**完整的岗位描述**（DOM 只渲染出摘要）以及技能标签、HR 活跃
    时间、学历经验要求。描述会被采集器写进 ``Job.description``，于是岗位匹配读到的 JD
    是全文而不是摘要；其余几项进 ``extra``，等有下游再接（见模块说明）。
    """
    if not isinstance(payload, dict):
        return None
    data = _data_container(payload)
    if data is None:
        return None
    # 内层容器同样**只认 `jobInfo`**。详情侧的宽容体现在下一行：容器没了、但 `zpData` 里
    # 直接带着岗位名与正文时仍按详情处理（详情只有一条记录，靠内容特征就能确认）。
    # 这与列表侧"容器改名即失败"的不对称是有意的，别为了"统一风格"把它收紧。
    detail = data.get("jobInfo")
    if not isinstance(detail, dict):
        detail = data if _first(data, "jobName", "jobTitle", "positionName") else None
    if not isinstance(detail, dict):
        return None

    raw_description = _first(
        detail, "postDescription", "jobDescription", "description", "descriptionHtml"
    )
    if not isinstance(raw_description, str):
        return None
    description_html = _strip_html(raw_description)
    if not description_html:
        return None
    # 接口只给一整段 ``postDescription``，而界面/模型上「职位描述」与「任职要求」是两个字段。
    # 以前一律整段塞进描述、要求留空，用户看到的就是"两件事混在一起"；这里按真实存在的小标题
    # 切分（切不出来就不切，把全文留在描述里，绝不造一个空的描述字段）。
    description, requirements = split_job_sections(description_html)
    boss_value = _first(data, "bossInfo", "recruiterInfo", "hrInfo")
    brand_value = _first(data, "brandInfo", "brandComInfo", "companyInfo")
    boss = boss_value if isinstance(boss_value, dict) else {}
    brand = brand_value if isinstance(brand_value, dict) else {}

    return {
        "job_title": _text(_first(detail, "jobName", "jobTitle", "positionName")),
        "company": _text(_first(brand, "brandName", "companyName", "name"))
        or _text(_first(boss, "brandName", "companyName"))
        or _text(_first(detail, "brandName", "companyName")),
        "description": description,
        # 切不出独立的要求段时留空是**如实**的：接口本来就没有把它单列出来，
        # 该段内容仍然完整地留在描述里，不会丢。
        "requirements": requirements,
        "url": _job_url(
            detail, _text(_first(detail, "encryptJobId", "encryptId", "jobId"))
        ),
        "extra": {
            "degree": _text(_first(detail, "jobDegree", "degreeName", "education")),
            "experience": _text(
                _first(detail, "jobExperience", "experienceName", "experience")
            ),
            "skills": _skill_tags(_first(detail, "skills", "skillList")),
            "hr_active_time": _text(
                _first(boss, "activeTimeDesc", "activeDesc", "lastActiveTime")
            ),
            "hr_name": _text(_first(boss, "name", "recruiterName", "hrName")),
            "hr_title": _text(_first(boss, "title", "position", "hrTitle")),
            "industry": _text(_first(brand, "brandIndustry", "industryName")),
            "scale": _text(_first(brand, "brandScaleName", "companyScale")),
            "stage": _text(_first(brand, "brandStageName", "financingStage")),
        },
    }


def looks_like_search(payload: Any) -> bool:
    """这个响应体是不是岗位列表。给 ``first_json_with`` 当判定函数用。"""
    return bool(_job_items(payload))


def search_has_more(payload: Any) -> bool | None:
    """列表响应里的"还有下一页"标志；结构里没有这个字段时返回 ``None``。

    调用方拿到 ``None`` 才去退回其它来源。**不要**默认让它退回页面探针报的
    ``has_next``：那个探针只回答"页面能不能采集"，根本不报翻页信息，一路取它会让
    分页永远停在第 1 页。
    """
    if not isinstance(payload, dict):
        return None
    data = _data_container(payload)
    if data is None:
        return None
    for key in ("hasMore", "has_more"):
        value = data.get(key)
        if isinstance(value, bool):
            return value
    return None


def looks_like_detail(payload: Any) -> bool:
    """这个响应体是不是岗位详情。"""
    if not isinstance(payload, dict):
        return False
    data = _data_container(payload)
    if data is None:
        return False
    detail = data.get("jobInfo")
    if isinstance(detail, dict) and _first(
        detail, "postDescription", "jobDescription", "description", "descriptionHtml"
    ):
        return True
    return bool(
        _first(data, "jobName", "jobTitle", "positionName")
        and _first(data, "postDescription", "jobDescription", "description")
    )


__all__ = [
    "DETAIL_MARKER",
    "DETAIL_MARKERS",
    "SEARCH_MARKER",
    "SEARCH_MARKERS",
    "api_error",
    "format_salary",
    "looks_like_detail",
    "looks_like_search",
    "parse_detail_response",
    "parse_search_response",
    "search_has_more",
]
