"""站点契约漂移（改版）回归：把"站点悄悄改了结构"这件事固化成断言。

**为什么要这份测试**：仓库里**一份真实抓取样例都没有**（`tests/fixtures/` 是空的），现有
`test_boss_network.py` 用的全是**手写 payload**。手写 payload 只能证明"解析器能解析我们
想象出来的结构"，**证明不了"站点的真实结构还能被解析"**。而站点改版恰恰是采集最先坏掉的原因。

所以这里换一个角度：在**已知的合法形状**上做**变异**（字段改名、字段消失、列表多套一层），
断言"改版之后我们到底是明确失败，还是安静地产出垃圾"。后者是最危险的形态——用户看到的是
"采集成功"，而数据是废的，既不报错也拿不到东西。

顺带把**哪些字段是承重的、哪些允许缺失**写成断言（见最后一组），避免以后有人"顺手"把
承重字段判空的条件删掉。
"""
import json

import pytest

from app.services.sites.boss_network import (
    looks_like_search,
    parse_detail_response,
    parse_search_response,
)


def _card(**overrides) -> dict:
    card = {
        "jobName": "后端开发实习生",
        "brandName": "示例科技",
        "cityName": "天津",
        "encryptJobId": "abc123",
        "lowSalary": 200,
        "highSalary": 300,
        "jobExperience": "在校/应届",
        "jobDegree": "本科",
    }
    card.update(overrides)
    for key in [key for key, value in card.items() if value is None]:
        del card[key]
    return card


def _search_payload(*cards: dict) -> dict:
    return {"code": 0, "zpData": {"jobList": list(cards) or [_card()]}}


def _detail_payload(**info_overrides) -> dict:
    info = {
        "jobName": "后端开发实习生",
        "encryptJobId": "abc123",
        "postDescription": "<p>负责接口开发<br>参与联调</p>",
    }
    info.update(info_overrides)
    for key in [key for key, value in info.items() if value is None]:
        del info[key]
    return {
        "zpData": {
            "jobInfo": info,
            "bossInfo": {"activeTimeDesc": "今日活跃"},
            "brandInfo": {"brandName": "示例科技"},
        }
    }


# ===== 列表：容器级改版 → 必须明确失败（这几条本来就对，钉住防退） =====


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("外层键改名 jobList→jobs", {"zpData": {"jobs": [_card()]}}),
        ("外层容器改名 zpData→data", {"data": {"jobList": [_card()]}}),
        ("外层容器消失", {"jobList": [_card()]}),
        ("列表不是数组", {"zpData": {"jobList": {"0": _card()}}}),
        ("整页不是 JSON 对象", [{"jobName": "岗位"}]),
    ],
)
def test_a_container_level_rename_is_reported_as_unrecognised(name, payload):
    """容器/键变了 → 返回 None，让上层按"抓不到"处理并退回 DOM 那条路。

    返回空列表是不行的：那会被上层说成"这次真的没搜到"，用户于是以为关键词太窄。
    """
    assert parse_search_response(json.loads(json.dumps(payload))) is None, name


# ===== 列表：卡片级改版 → 必须明确失败（这是本轮修掉的行为） =====


@pytest.mark.parametrize(
    ("name", "card"),
    [
        ("标题字段改名 jobName→job_name", _card(job_name="后端开发实习生", jobName=None)),
        ("标题字段整个消失", _card(jobName=None)),
        ("标题与公司都消失", _card(jobName=None, brandName=None)),
        ("卡片被包了一层（列表多套一层）", {"jobList": [_card()]}),
    ],
)
def test_a_card_level_rename_is_not_silently_turned_into_an_empty_job(name, card):
    """**卡片里读不出岗位名 → 这页就是"结构不认识"，必须返回 None。**

    修之前的行为是静默产出 `title=""` 的"岗位"：上层看到"采到了 N 条"，用户拿到一堆空名字，
    而且**什么错都不报**。站点把 `jobName` 改个名字就会触发这个形态——这是最该报警的一种改版，
    却偏偏是最安静的一种。
    """
    assert parse_search_response(_search_payload(card)) is None, name


def test_a_wholly_unreadable_page_is_logged_for_troubleshooting(caplog):
    """全页读不出岗位名时要留一条日志：排障时得能看出"这次是结构不认识"，而不是猜。"""
    with caplog.at_level("WARNING"):
        assert parse_search_response(_search_payload(_card(jobName=None))) is None

    assert any("结构不认识" in record.message for record in caplog.records)


# ===== 列表：允许降级的部分——刻意保留，不因为一块脏就丢一整页 =====


def test_one_broken_card_does_not_throw_away_the_whole_page():
    """一页里只有个别卡片读不出来时，保留能用的那部分。

    刻意**不**让一条脏数据否掉整页：宁可少一条，也不要因为一条异常把这一页的有效岗位全丢掉
    （这也是采集筛选一贯的取向：判断不了就不误杀）。
    """
    items = parse_search_response(_search_payload(_card(), _card(jobName=None), _card()))

    assert items is not None
    assert len(items) == 2
    assert all(item["title"] == "后端开发实习生" for item in items)


def test_a_missing_company_keeps_the_card_instead_of_dropping_it():
    """公司名读不出来时**保留**这张卡片——岗位名才是承重字段。

    取舍写在这里以免被"顺手"改成一律丢弃：岗位名在，卡片就有价值（公司名后续补详情时还能拿到，
    或者用户自己看得出来）；而丢掉它，用户就少看到一个岗位，且不会知道为什么。
    这里同时钉住"不为缺失的字段编造内容"：company 是空串，不是某个默认值。
    """
    items = parse_search_response(_search_payload(_card(companyName="示例科技", brandName=None)))

    assert items is not None and len(items) == 1
    assert items[0]["title"] == "后端开发实习生"
    assert items[0]["company"] == ""


def test_a_missing_link_still_keeps_the_card():
    """链接不是判据：拿不到详情页地址时仍然保留（上层会退回"点开卡片拿 href"）。"""
    items = parse_search_response(_search_payload(_card(encryptJobId=None)))

    assert items is not None and len(items) == 1
    assert items[0]["title"] == "后端开发实习生"
    assert items[0]["url"] == ""


def test_looks_like_search_agrees_with_the_parser():
    """`looks_like_search` 是"要不要走接口这条路"的判据，不能与解析器给出相反的结论。"""
    assert looks_like_search(_search_payload()) is True
    # 卡片级改版后：结构还在，所以"看起来像搜索响应"依然为真——解析结果才是判据。
    assert looks_like_search(_search_payload(_card(jobName=None))) is True
    assert looks_like_search({"zpData": {"jobs": []}}) is False


# ===== 详情：正文是承重字段 =====


@pytest.mark.parametrize(
    ("name", "info"),
    [
        ("正文字段改名 postDescription→job_detail", {"job_detail": "<p>正文</p>", "postDescription": None}),
        ("正文字段整个消失", {"postDescription": None}),
        ("正文是空的 HTML", {"postDescription": "<p></p>"}),
        ("详情容器改名 jobInfo→jobDetail", {}),
    ],
)
def test_a_detail_without_a_readable_body_is_not_a_detail(name, info):
    """详情里读不出正文 → 返回 None（"没有正文就不算详情"）。

    详情这条路的价值就是**完整正文**；正文没了却还返回一个对象，会让上层把空 JD 写进岗位，
    于是"补详情"看起来成功、实际什么都没补上。
    """
    payload = _detail_payload(**info)
    if name == "详情容器改名 jobInfo→jobDetail":
        payload["zpData"]["jobDetail"] = payload["zpData"].pop("jobInfo")

    assert parse_detail_response(payload) is None, name


def test_a_detail_missing_only_the_title_still_counts():
    """岗位名读不出来但正文在 → 仍然算一条详情。

    与列表侧相反：列表里岗位名是"这条能不能用"的判据，详情里**正文**才是承重字段
    （岗位名上层本来就有，详情是去补正文的）。所以这里的降级是刻意的。
    """
    parsed = parse_detail_response(_detail_payload(jobName=None))

    assert parsed is not None
    assert parsed["job_title"] == ""
    assert "负责接口开发" in parsed["description"]


def test_the_detail_parser_tolerates_a_flattened_container():
    """详情容器换个名字但字段还在时应当仍能解析（详情侧已经做了这层兜底）。

    与列表侧的"容器改名就失败"不同——这是有意为之：详情响应只有一条记录，靠 `jobName` 之类
    的**内容特征**就足以确认它是详情对象，不需要把结构写死。把这种宽容写进测试，免得
    以后有人以"统一风格"为名把它收紧，反而把站点的一次小改版变成不可用。
    """
    payload = _detail_payload()
    payload["zpData"] = {"jobName": "后端开发实习生", "postDescription": "<p>正文</p>"}

    assert parse_detail_response(payload) is not None
