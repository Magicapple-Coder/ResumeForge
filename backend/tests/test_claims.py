"""事实台账：校验规则、改进建议与事实基线。

这一层的价值全在"规则"上，所以测试重点不是增删改查能不能跑，而是：
- 自相矛盾（已确认 + 待补占位符）必须被挡在保存之前；
- 改进建议要在该出现的时候出现、不该出现的时候不出现（否则用户会学会忽略它）；
- 事实基线只喂已确认的内容，未确认的说法必须进"要避开的清单"。
"""
import pytest
from pydantic import ValidationError

from app.models.claim import (
    CLAIM_CATEGORY_PROJECT,
    RESPONSIBILITY_LED,
    RESPONSIBILITY_OWNER,
    RESPONSIBILITY_PARTICIPATED,
    VERIFICATION_CONFIRMED,
    VERIFICATION_EXPIRED,
    VERIFICATION_PENDING,
    VERIFICATION_REJECTED,
    can_enter_final,
    has_placeholder,
    placeholder_hit,
)
from app.schemas.claim import ClaimCreate, ClaimSource
from app.services.claims import (
    build_baseline,
    claim_out,
    claim_warnings,
    create_claim,
    delete_claim,
    list_claims,
    summarize,
    update_claim,
)


def _payload(**overrides) -> dict:
    base = {
        "title": "检索接口",
        "category": CLAIM_CATEGORY_PROJECT,
        "subject": "校园知识检索平台",
        "source_fact": "负责检索接口的实现与联调。",
        "candidate_wording": "实现检索接口并联调上线",
        "responsibility_level": RESPONSIBILITY_PARTICIPATED,
        "verification_status": VERIFICATION_PENDING,
    }
    base.update(overrides)
    return base


# ===== 占位符与状态闸门 =====


def test_placeholder_helpers_cover_all_markers():
    assert has_placeholder("这条还没核实【待补：指标】")
    assert has_placeholder("【待确认】以成绩单为准")
    assert has_placeholder("结果【待补充】")
    assert has_placeholder("【待核实】上线时间")
    assert not has_placeholder("正常的一句话")
    assert not has_placeholder("")
    assert placeholder_hit("前置【待确认】后缀") == "【待确认"


def test_only_confirmed_can_enter_final():
    assert can_enter_final(VERIFICATION_CONFIRMED)
    for status in (VERIFICATION_PENDING, VERIFICATION_EXPIRED, VERIFICATION_REJECTED):
        assert not can_enter_final(status)
    # 读到一个没见过的状态时必须保守：宁可不让它进终稿。
    assert not can_enter_final("未来版本的新状态")


def test_confirmed_claim_cannot_carry_a_placeholder():
    """已确认却还带占位符是自相矛盾，必须在保存前挡住。"""
    with pytest.raises(ValidationError) as excinfo:
        ClaimCreate(**_payload(verification_status=VERIFICATION_CONFIRMED,
                               candidate_wording="优化了检索速度【待补：具体倍数】"))
    message = str(excinfo.value)
    assert "待补" in message
    assert "已确认" in message


@pytest.mark.parametrize("field", ["source_fact", "boundary"])
def test_confirmed_claim_cannot_carry_a_placeholder_in_any_field(field):
    """占位符藏在原始事实或个人边界里同样要被挡住，不能只看候选表述。"""
    with pytest.raises(ValidationError):
        ClaimCreate(**_payload(verification_status=VERIFICATION_CONFIRMED, **{field: "【待补：口径】"}))


def test_pending_claim_may_carry_a_placeholder():
    claim = ClaimCreate(**_payload(candidate_wording="【待补：以成绩单确认】"))
    assert claim.verification_status == VERIFICATION_PENDING


# ===== 枚举与格式校验 =====


def test_unknown_enum_values_are_rejected():
    for field, value in (
        ("category", "不存在的分类"),
        ("responsibility_level", "首席"),
        ("verification_status", "大概吧"),
    ):
        with pytest.raises(ValidationError):
            ClaimCreate(**_payload(**{field: value}))


def test_last_verified_accepts_real_dates_only():
    assert ClaimCreate(**_payload(last_verified="2026-09-18")).last_verified == "2026-09-18"
    assert ClaimCreate(**_payload(last_verified="")).last_verified == ""
    for bad in ("2026-9-18", "2026/09/18", "2026-02-31", "今天"):
        with pytest.raises(ValidationError):
            ClaimCreate(**_payload(last_verified=bad))


def test_a_claim_must_describe_something():
    with pytest.raises(ValidationError):
        ClaimCreate(**_payload(source_fact="", candidate_wording=""))
    # 只填一边是允许的：先记事实、措辞以后再说，或反过来。
    assert ClaimCreate(**_payload(source_fact="", candidate_wording="做了检索接口")).candidate_wording


def test_interview_details_are_normalised():
    claim = ClaimCreate(
        **_payload(
            interview_details={
                "decisions": ["选了 RRF 融合", "选了 RRF 融合", "  "],
                "result": "  检索成功率提升  ",
            }
        )
    )
    assert claim.interview_details["decisions"] == ["选了 RRF 融合"]
    assert claim.interview_details["result"] == "检索成功率提升"
    # 没提到的分类补齐成空列表，界面就不用到处判 None。
    assert claim.interview_details["difficulties"] == []
    assert claim.interview_details["verification"] == []


def test_interview_details_reject_non_list_values():
    with pytest.raises(ValidationError):
        ClaimCreate(**_payload(interview_details={"decisions": "选了 RRF 融合"}))


def test_source_type_must_be_known_and_public_must_be_bool():
    source = ClaimSource(type="pull_request", location="https://example.com/pr/1", public=True)
    assert source.public is True
    assert ClaimSource(type="", location="x").type == "other"
    with pytest.raises(ValidationError):
        ClaimSource(type="telepathy", location="x")


def test_list_fields_are_deduplicated_and_bounded():
    claim = ClaimCreate(**_payload(allowed_uses=["简历", "简历", "  ", "自我介绍"]))
    assert claim.allowed_uses == ["简历", "自我介绍"]


# ===== 改进建议 =====


def _record(**overrides):
    return ClaimCreate(**_payload(**overrides)).model_dump()


class _Row:
    """把 schema 数据包成带属性的对象，模拟 ORM 记录（建议函数只读属性）。"""

    def __init__(self, data: dict) -> None:
        for key, value in data.items():
            setattr(self, key, value)


def _row(**overrides) -> _Row:
    data = _record(**overrides)
    data.setdefault("id", 1)
    return _Row(data)


def test_strong_claim_without_interview_details_is_flagged():
    warnings = claim_warnings(_row(responsibility_level=RESPONSIBILITY_LED))
    assert any("强主张" in item for item in warnings)
    # 补上细节之后就不再提醒。
    quiet = claim_warnings(
        _row(
            responsibility_level=RESPONSIBILITY_OWNER,
            interview_details={"decisions": ["先做检索再做排序"]},
        )
    )
    assert not any("强主张" in item for item in quiet)


def test_confirmed_claim_missing_evidence_and_boundary_is_flagged():
    warnings = claim_warnings(
        _row(
            verification_status=VERIFICATION_CONFIRMED,
            candidate_wording="实现检索接口并联调上线",
            boundary="",
            sources=[],
        )
    )
    assert any("个人边界" in item for item in warnings)
    assert any("证据来源" in item for item in warnings)


def test_pending_wording_without_placeholder_is_flagged():
    warnings = claim_warnings(
        _row(verification_status=VERIFICATION_PENDING, candidate_wording="实现检索接口")
    )
    assert any("占位符" in item for item in warnings)
    # 加了占位符就不再提醒。
    quiet = claim_warnings(
        _row(verification_status=VERIFICATION_PENDING, candidate_wording="【待补：上线范围】")
    )
    assert not any("占位符" in item for item in quiet)


def test_wording_stronger_than_responsibility_is_flagged():
    warnings = claim_warnings(
        _row(responsibility_level=RESPONSIBILITY_PARTICIPATED, candidate_wording="主导了检索方案设计")
    )
    assert any("强措辞" in item for item in warnings)
    # 承担程度对得上时不提醒。
    quiet = claim_warnings(
        _row(responsibility_level=RESPONSIBILITY_LED, candidate_wording="主导了检索方案设计")
    )
    assert not any("强措辞" in item for item in quiet)


def test_expired_and_rejected_states_are_explained():
    assert any("过期" in item for item in claim_warnings(_row(verification_status=VERIFICATION_EXPIRED)))
    assert any(
        "避开" in item for item in claim_warnings(_row(verification_status=VERIFICATION_REJECTED))
    )


def test_a_clean_claim_produces_no_warnings():
    """干净的一条不该有任何建议——否则用户会学会忽略所有提示。"""
    warnings = claim_warnings(
        _row(
            verification_status=VERIFICATION_CONFIRMED,
            responsibility_level=RESPONSIBILITY_PARTICIPATED,
            candidate_wording="实现检索接口并联调上线",
            boundary="接口由本人实现，检索算法由另一位同学负责。",
            sources=[{"type": "repository", "location": "https://example.com/repo", "public": True, "note": ""}],
        )
    )
    assert warnings == []


# ===== 增删改查与汇总 =====


def test_crud_round_trip(db_session):
    created = create_claim(db_session, ClaimCreate(**_payload()))
    assert created.id
    # 没填标题时退回主体名，列表里至少有个能认出来的名字。
    untitled = create_claim(db_session, ClaimCreate(**_payload(title="", subject="某项目")))
    assert untitled.title == "某项目"

    updated = update_claim(
        db_session,
        created,
        ClaimCreate(**_payload(title="改过的标题", verification_status=VERIFICATION_CONFIRMED,
                               candidate_wording="实现检索接口并联调上线",
                               boundary="接口由本人实现。")),
    )
    assert updated.title == "改过的标题"
    assert updated.verification_status == VERIFICATION_CONFIRMED

    assert delete_claim(db_session, created.id) is True
    assert delete_claim(db_session, created.id) is False


def test_list_filters_by_category_status_and_keyword(db_session):
    create_claim(db_session, ClaimCreate(**_payload(title="检索接口", subject="检索平台")))
    create_claim(
        db_session,
        ClaimCreate(**_payload(title="数据清洗", subject="清洗脚本", category="其他")),
    )
    create_claim(
        db_session,
        ClaimCreate(
            **_payload(
                title="获奖",
                subject="校级奖学金",
                category="荣誉奖项",
                verification_status=VERIFICATION_CONFIRMED,
                candidate_wording="获校级奖学金",
                boundary="个人奖项。",
                sources=[{"type": "certificate", "location": "证书编号 A", "public": False, "note": ""}],
            )
        ),
    )

    assert len(list_claims(db_session)) == 3
    assert [item.title for item in list_claims(db_session, category="荣誉奖项")] == ["获奖"]
    assert [item.title for item in list_claims(db_session, status=VERIFICATION_CONFIRMED)] == ["获奖"]
    assert [item.title for item in list_claims(db_session, keyword="清洗")] == ["数据清洗"]
    # 关键词也搜原始事实，不然用户记不清标题就找不到了。
    assert [item.title for item in list_claims(db_session, keyword="联调")]


def test_summarize_counts_by_status_and_category(db_session):
    records = [
        create_claim(db_session, ClaimCreate(**_payload(title="A"))),
        create_claim(
            db_session,
            ClaimCreate(
                **_payload(
                    title="B",
                    verification_status=VERIFICATION_CONFIRMED,
                    candidate_wording="实现检索接口并联调上线",
                    boundary="接口由本人实现。",
                    sources=[{"type": "link", "location": "x", "public": True, "note": ""}],
                )
            ),
        ),
        create_claim(db_session, ClaimCreate(**_payload(title="C", category="荣誉奖项"))),
    ]
    summary = summarize(records)
    assert summary["total"] == 3
    assert summary["confirmed_count"] == 1
    assert summary["pending_count"] == 2
    assert summary["category_counts"][CLAIM_CATEGORY_PROJECT] == 2
    assert summary["category_counts"]["荣誉奖项"] == 1


def test_claim_out_attaches_warnings(db_session):
    record = create_claim(
        db_session,
        ClaimCreate(**_payload(responsibility_level=RESPONSIBILITY_OWNER, sources=[])),
    )
    payload = claim_out(record)
    assert payload.id == record.id
    assert any("强主张" in item for item in payload.warnings)


# ===== 事实基线 =====


def test_baseline_is_empty_when_the_ledger_is_empty(db_session):
    """没启用台账的用户，生成链路拿到的基线必须是空的（行为与以前完全一致）。"""
    baseline = build_baseline(db_session)
    assert baseline.confirmed_count == 0
    assert baseline.baseline_text == ""
    assert baseline.blocked_wording == []
    assert baseline.warnings == []


def test_baseline_contains_only_confirmed_claims(db_session):
    create_claim(
        db_session,
        ClaimCreate(
            **_payload(
                title="检索接口",
                verification_status=VERIFICATION_CONFIRMED,
                candidate_wording="实现检索接口并联调上线",
                boundary="接口由本人实现。",
                sources=[{"type": "link", "location": "x", "public": True, "note": ""}],
            )
        ),
    )
    create_claim(
        db_session,
        ClaimCreate(
            **_payload(
                title="导师项目",
                verification_status=VERIFICATION_PENDING,
                candidate_wording="【待补：确认参与范围】参与导师项目",
            )
        ),
    )
    create_claim(
        db_session,
        ClaimCreate(
            **_payload(
                title="已作废的说法",
                verification_status=VERIFICATION_REJECTED,
                candidate_wording="独立完成整个平台",
            )
        ),
    )

    baseline = build_baseline(db_session)
    assert baseline.confirmed_count == 1
    assert "检索接口" in baseline.baseline_text
    # 未确认的表述必须进"要避开的清单"，而不是被静默丢掉。
    assert any("参与导师项目" in item for item in baseline.blocked_wording)
    assert any("独立完成整个平台" in item for item in baseline.blocked_wording)
    assert "独立完成整个平台" not in baseline.baseline_text
    assert len(baseline.warnings) == 2


def test_baseline_text_is_bounded(db_session):
    for index in range(60):
        create_claim(
            db_session,
            ClaimCreate(
                **_payload(
                    title=f"主张 {index}",
                    source_fact="X" * 2_000,
                    verification_status=VERIFICATION_CONFIRMED,
                    candidate_wording="凑数",
                    boundary="边界",
                    sources=[{"type": "link", "location": "x", "public": True, "note": ""}],
                )
            ),
        )
    baseline = build_baseline(db_session)
    assert len(baseline.baseline_text) <= 12_000
