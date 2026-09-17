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

logger = logging.getLogger(__name__)

# 接口路径里用来识别"这是岗位列表 / 岗位详情"的片段。
SEARCH_MARKER = "/wapi/zpgeek/search/joblist.json"
DETAIL_MARKER = "/wapi/zpgeek/job/detail.json"

# 接口里的薪资是数字（单位：元/月，或天）。超过这个数就当作"按天"而不是"按月"，
# 因为月薪几十万在实习与校招场景里几乎不存在，而日薪 300~800 很常见。
_DAILY_SALARY_THRESHOLD = 3000
_MAX_TITLE_CHARS = 200
_MAX_TEXT_CHARS = 20_000


def _text(value: Any, limit: int = _MAX_TITLE_CHARS) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _strip_html(value: Any, limit: int = _MAX_TEXT_CHARS) -> str:
    """把接口返回的带标签文本转成纯文本。

    岗位描述在接口里是 HTML 片段（``<br>``、``<p>``）。直接塞进 JD 里会让匹配分析
    与关键词提取读到一堆标签，所以这里把标签换成换行并压掉多余空行。
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
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)[:limit]


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
        tag = _text(item, 40)
        if tag and tag not in result:
            result.append(tag)
    return result[:12]


def _job_items(payload: Any) -> list[dict[str, Any]]:
    """从列表响应里取出岗位数组；结构不认识时返回空列表。"""
    if not isinstance(payload, dict):
        return []
    data = payload.get("zpData")
    if not isinstance(data, dict):
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
    for item in items:
        job_id = _text(item.get("encryptJobId"))
        # BOSS 的详情页地址可以从 encryptJobId 拼出来；拼不出来时留空，
        # 上层会退回"点开卡片拿 href"那条路。
        url = f"https://www.zhipin.com/job_detail/{job_id}.html" if job_id else ""
        results.append(
            {
                "title": _text(item.get("jobName")),
                "company": _text(item.get("brandName")),
                "location": _text(item.get("cityName"))
                or _text(item.get("areaDistrict")),
                # 优先用数字字段拼出来（口径统一），拼不出来时才用接口给的展示文本。
                "salary": format_salary(
                    item.get("lowSalary"), item.get("highSalary"), item.get("salaryMonth")
                )
                or _text(item.get("salaryDesc")),
                "url": url,
                "extra": {
                    "encrypt_job_id": job_id,
                    "encrypt_boss_id": _text(item.get("encryptBossId")),
                    "experience": _text(item.get("jobExperience")),
                    "degree": _text(item.get("jobDegree")),
                    "industry": _text(item.get("brandIndustry")),
                    "scale": _text(item.get("brandScaleName")),
                    "stage": _text(item.get("brandStageName")),
                    "skills": _skill_tags(item.get("skills")),
                    "hr_active": _text(item.get("bossOnline") or "") == "true"
                    or _text(item.get("bossActiveTimeDesc")),
                },
            }
        )
    return results or None


def parse_detail_response(payload: Any) -> dict[str, Any] | None:
    """解析岗位详情响应 → ``{job_title, company, description, requirements, url, extra}``。

    接口详情比 DOM 多出的是**完整的岗位描述**（DOM 只渲染出摘要）以及技能标签、HR 活跃
    时间、学历经验要求。描述会被采集器写进 ``Job.description``，于是岗位匹配读到的 JD
    是全文而不是摘要；其余几项进 ``extra``，等有下游再接（见模块说明）。
    """
    if not isinstance(payload, dict):
        return None
    data = payload.get("zpData")
    if not isinstance(data, dict):
        return None
    detail = data.get("jobInfo")
    if not isinstance(detail, dict):
        detail = data if data.get("jobName") else None
    if not isinstance(detail, dict):
        return None

    description = _strip_html(detail.get("postDescription"))
    if not description:
        return None
    boss = data.get("bossInfo") if isinstance(data.get("bossInfo"), dict) else {}
    brand = data.get("brandInfo") if isinstance(data.get("brandInfo"), dict) else {}

    return {
        "job_title": _text(detail.get("jobName")),
        "company": _text(brand.get("brandName")) or _text(boss.get("brandName")),
        "description": description,
        # 接口没有把"任职要求"单列出来，它在描述里；留空让上层用描述兜底，
        # 不要为了凑字段把描述复制一遍（那会让匹配分析读到两份同样的文本）。
        "requirements": "",
        "url": f"https://www.zhipin.com/job_detail/{_text(detail.get('encryptJobId'))}.html"
        if detail.get("encryptJobId")
        else "",
        "extra": {
            "degree": _text(detail.get("jobDegree")),
            "experience": _text(detail.get("jobExperience")),
            "skills": _skill_tags(detail.get("skills")),
            "hr_active_time": _text(boss.get("activeTimeDesc")),
            "hr_name": _text(boss.get("name")),
            "hr_title": _text(boss.get("title")),
            "industry": _text(brand.get("brandIndustry")),
            "scale": _text(brand.get("brandScaleName")),
            "stage": _text(brand.get("brandStageName")),
        },
    }


def looks_like_search(payload: Any) -> bool:
    """这个响应体是不是岗位列表。给 ``first_json_with`` 当判定函数用。"""
    return bool(_job_items(payload))


def looks_like_detail(payload: Any) -> bool:
    """这个响应体是不是岗位详情。"""
    if not isinstance(payload, dict):
        return False
    data = payload.get("zpData")
    if not isinstance(data, dict):
        return False
    detail = data.get("jobInfo")
    if isinstance(detail, dict) and detail.get("postDescription"):
        return True
    return bool(data.get("jobName") and data.get("postDescription"))


__all__ = [
    "DETAIL_MARKER",
    "SEARCH_MARKER",
    "format_salary",
    "looks_like_detail",
    "looks_like_search",
    "parse_detail_response",
    "parse_search_response",
]
