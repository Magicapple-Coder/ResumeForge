"""从页面内嵌的 schema.org ``JobPosting`` 里读岗位。

这一级是通用路径里**唯一有公开规范**的：字段名与嵌套结构由 schema.org 定义，不依赖任何站点
的私有格式。用例因此按规范的各种合法写法逐个覆盖，重点在**容器形态与 `@type` 写法**——
少支持一种就会让整个站在这一级失败（而这三种在真实页面里都很常见）。

另一半用例守的是"拿不准就留空，不猜"：``FULL_TIME`` **不能**被映射成本项目的岗位类型，
因为它回答的是"是不是全职"，而不是"校招还是社招"。
"""
from __future__ import annotations

import json

from app.services.sites.official.generic.jsonld import (
    extract_job_postings,
    iter_nodes,
    parse_job_posting,
    script_payloads,
)


def _page(*payloads: object) -> str:
    """把若干 JSON-LD 负载包成一个页面。"""
    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps(p, ensure_ascii=False)}</script>'
        for p in payloads
    )
    return f"<html><head>{blocks}</head><body></body></html>"


def _posting(**overrides) -> dict:
    base = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "大模型应用开发工程师",
        "description": "<p>负责大模型应用的落地</p>",
        "hiringOrganization": {"@type": "Organization", "name": "示例科技"},
        "jobLocation": {
            "@type": "Place",
            "address": {"@type": "PostalAddress", "addressLocality": "北京"},
        },
    }
    base.update(overrides)
    return base


# ===== 容器形态 =====


def test_bare_object_form():
    jobs = extract_job_postings(_page(_posting()))
    assert len(jobs) == 1
    assert jobs[0].title == "大模型应用开发工程师"


def test_array_form():
    jobs = extract_job_postings(_page([_posting(title="岗位甲"), _posting(title="岗位乙")]))
    assert {job.title for job in jobs} == {"岗位甲", "岗位乙"}


def test_graph_form():
    payload = {"@context": "https://schema.org", "@graph": [_posting(title="图里的岗位")]}
    jobs = extract_job_postings(_page(payload))
    assert [job.title for job in jobs] == ["图里的岗位"]


def test_graph_mixed_with_other_types():
    """一个 ``@graph`` 里混着多种类型是常态，不能因为第一条不是岗位就整块放弃。"""
    payload = {
        "@graph": [
            {"@type": "Organization", "name": "示例科技"},
            _posting(title="夹在中间的岗位"),
            {"@type": "WebSite", "name": "招聘站"},
        ]
    }
    assert [job.title for job in extract_job_postings(_page(payload))] == ["夹在中间的岗位"]


def test_title_only_page_without_jsonld():
    assert extract_job_postings("<html><body>没有结构化数据</body></html>") == []


def test_plain_script_is_not_treated_as_data():
    """没有 ``type="application/ld+json"`` 的 script 是代码，不是数据。"""
    html = '<html><script>var x = {"@type": "JobPosting", "title": "假的"};</script></html>'
    assert extract_job_postings(html) == []


# ===== @type 的写法 =====


def test_type_as_full_iri():
    jobs = extract_job_postings(_page(_posting(**{"@type": "https://schema.org/JobPosting"})))
    assert len(jobs) == 1


def test_type_as_schema_prefix():
    jobs = extract_job_postings(_page(_posting(**{"@type": "schema:JobPosting"})))
    assert len(jobs) == 1


def test_type_as_array():
    jobs = extract_job_postings(_page(_posting(**{"@type": ["JobPosting", "Thing"]})))
    assert len(jobs) == 1


def test_other_types_are_ignored():
    assert extract_job_postings(_page({"@type": "BlogPosting", "title": "不是岗位"})) == []


def test_type_matching_is_case_insensitive():
    assert len(extract_job_postings(_page(_posting(**{"@type": "jobposting"})))) == 1


# ===== 字段映射 =====


def test_missing_title_is_dropped():
    """标题缺就丢掉这一条：没有标题的岗位在下游无法使用（去重判据与列表展示都依赖它）。"""
    assert parse_job_posting(_posting(title="")) is None
    assert parse_job_posting({"@type": "JobPosting", "description": "只有描述"}) is None


def test_missing_description_still_kept():
    """描述缺则照收——标题、公司、链接、发布时间仍然有价值。"""
    job = parse_job_posting(_posting(description=""))
    assert job is not None
    assert job.description == ""


def test_description_html_is_converted_to_text():
    job = parse_job_posting(_posting(description="<p>职责一</p><ul><li>要求一</li></ul>"))
    assert "职责一" in job.description
    assert "要求一" in job.description
    assert "<p>" not in job.description


def test_hiring_organization_variants():
    for value in ({"name": "对象形式"}, "字符串形式", [{"name": "数组形式"}], {"@value": "值形式"}):
        job = parse_job_posting(_posting(hiringOrganization=value))
        assert job is not None
        assert job.company, value


def test_location_from_place_address():
    job = parse_job_posting(
        _posting(
            jobLocation={
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "上海",
                    "addressRegion": "上海市",
                    "addressCountry": {"@type": "Country", "name": "CN"},
                },
            }
        )
    )
    assert job is not None
    # "上海" 与 "上海市" 同时给出是常态，按前缀去重后只留一个。
    assert job.location == "上海 CN"
    assert job.location.count("上海") == 1


def test_location_variants():
    for value, expected in (
        ("深圳", "深圳"),
        ({"@type": "Place", "name": "远程"}, "远程"),
        ([{"@type": "Place", "name": "北京"}, {"@type": "Place", "name": "上海"}], "北京 / 上海"),
    ):
        job = parse_job_posting(_posting(jobLocation=value))
        assert job is not None
        assert job.location == expected, value


def test_salary_monetary_amount():
    job = parse_job_posting(
        _posting(
            baseSalary={
                "@type": "MonetaryAmount",
                "currency": "CNY",
                "value": {"@type": "QuantitativeValue", "minValue": 20000, "maxValue": 35000,
                          "unitText": "MONTH"},
            }
        )
    )
    assert job is not None
    assert "CNY" in job.salary
    assert "20000-35000" in job.salary
    assert "MONTH" in job.salary


def test_salary_price_specification():
    job = parse_job_posting(_posting(baseSalary={"minValue": 300, "maxValue": 500, "unitText": "DAY"}))
    assert job is not None
    assert "300-500" in job.salary


def test_salary_single_value_has_no_dash():
    job = parse_job_posting(
        _posting(baseSalary={"currency": "USD", "value": {"value": 100000, "unitText": "YEAR"}})
    )
    assert job is not None
    assert "100000" in job.salary
    assert "-" not in job.salary


def test_employment_type_intern_is_mapped():
    job = parse_job_posting(_posting(employmentType="INTERN"))
    assert job is not None
    assert job.job_type == "实习"


def test_employment_type_as_array_is_handled():
    """规范允许数组形态，真实页面也确实这么写。"""
    job = parse_job_posting(_posting(employmentType=["FULL_TIME", "INTERN"]))
    assert job is not None
    assert job.job_type == "实习", "数组里有一个能映射的就该用上"


def test_employment_type_array_without_a_mappable_value_stays_empty():
    job = parse_job_posting(_posting(employmentType=["FULL_TIME", "CONTRACTOR"]))
    assert job is not None
    assert job.job_type == ""


def test_salary_as_a_plain_string():
    job = parse_job_posting(_posting(baseSalary="月薪 20-30K"))
    assert job is not None
    assert job.salary == "月薪 20-30K"


def test_salary_with_a_plain_numeric_value():
    job = parse_job_posting(_posting(baseSalary={"currency": "EUR", "value": 60000}))
    assert job is not None
    assert "60000" in job.salary


def test_salary_without_an_amount_yields_empty():
    """结构认识但里面没金额时留空，不编一个出来。"""
    job = parse_job_posting(_posting(baseSalary={"@type": "MonetaryAmount", "currency": "CNY"}))
    assert job is not None
    assert job.salary == ""


def test_address_given_as_a_plain_string():
    """有的站点把 ``address`` 直接写成一行地址，而不是 PostalAddress 对象。"""
    job = parse_job_posting(_posting(jobLocation={"@type": "Place", "address": "北京市海淀区"}))
    assert job is not None
    assert job.location == "北京市海淀区"


def test_employment_type_full_time_is_not_guessed():
    """``FULL_TIME`` 说的是"是不是全职"，不是"校招还是社招"。

    硬映射成"社招"会把校招岗位标错——而项目既有取向是"规则无法确认的字段宁可留空也不猜"。
    原始值留在 extra 里，需要时可以自己看。
    """
    job = parse_job_posting(_posting(employmentType="FULL_TIME"))
    assert job is not None
    assert job.job_type == ""
    assert job.extra["employment_type"] == "FULL_TIME"


def test_identifier_variants():
    for value, expected in (
        ("JOB-1", "JOB-1"),
        ({"@type": "PropertyValue", "value": "JOB-2"}, "JOB-2"),
        ([{"value": "JOB-3"}], "JOB-3"),
    ):
        job = parse_job_posting(_posting(identifier=value))
        assert job is not None
        assert job.external_id == expected


def test_date_posted_is_kept_verbatim():
    """发布时间保持原始语义——不加工、不用本地时间替代（项目既有决策）。"""
    job = parse_job_posting(_posting(datePosted="2026-09-01T00:00:00+08:00"))
    assert job is not None
    assert job.posted_at == "2026-09-01T00:00:00+08:00"


# ===== 链接与去重 =====


def test_relative_url_is_resolved_against_the_page():
    jobs = extract_job_postings(
        _page(_posting(url="/jobs/123")), base_url="https://careers.example.com/list"
    )
    assert jobs[0].url == "https://careers.example.com/jobs/123"


def test_absolute_url_is_untouched():
    jobs = extract_job_postings(
        _page(_posting(url="https://careers.example.com/jobs/9")),
        base_url="https://careers.example.com/list",
    )
    assert jobs[0].url == "https://careers.example.com/jobs/9"


def test_duplicate_declarations_keep_the_richer_one():
    """同一条岗位常被两个脚本块重复声明（一个摘要版、一个完整版）。

    保留描述更长的那个，否则"页面上明明有完整 JD、库里却是摘要"会成为一个查不出来的静默降级。
    """
    summary = _posting(description="<p>短</p>", url="https://x.example/1")
    full = _posting(description="<p>" + "详细的职责说明。" * 30 + "</p>", url="https://x.example/1")

    jobs = extract_job_postings(_page(summary, full))

    assert len(jobs) == 1
    assert len(jobs[0].description) > 100


# ===== 容错 =====


def test_broken_block_does_not_lose_the_others():
    html = (
        '<script type="application/ld+json">{ 这不是合法 JSON </script>'
        f'<script type="application/ld+json">{json.dumps(_posting(title="幸存岗位"), ensure_ascii=False)}</script>'
    )
    assert [job.title for job in extract_job_postings(html)] == ["幸存岗位"]


def test_malformed_node_does_not_lose_the_others():
    html = _page({"@type": "JobPosting", "title": "正常岗位"}, {"@type": "JobPosting",
                                                                 "title": ["不是字符串"]})
    titles = [job.title for job in extract_job_postings(html)]
    assert "正常岗位" in titles


def test_script_payloads_returns_raw_blocks():
    blocks = script_payloads(_page(_posting()))
    assert len(blocks) == 1
    assert json.loads(blocks[0])["@type"] == "JobPosting"


def test_iter_nodes_flattens_mixed_nesting():
    payload = {"@graph": [{"@type": "A"}, [{"@type": "B"}]]}
    types = [node.get("@type") for node in iter_nodes(payload)]
    assert "A" in types and "B" in types
