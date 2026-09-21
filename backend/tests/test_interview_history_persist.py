"""D5 题库/复盘历史的局部更新（PATCH 写回）接口。

历史记录富还原要求：打开一条历史记录后，新生成的参考答案/复盘结果能写回同一条记录，
重新打开时仍在。这里验证更新逻辑只更新提供的字段并持久化（含参考答案嵌套字段）。
"""
from app.schemas.interview_history import (
    InterviewReviewRecordCreate,
    InterviewReviewRecordUpdate,
    QuestionBankRecordCreate,
    QuestionBankRecordUpdate,
)
from app.services.interview.interview_history import (
    create_question_bank,
    create_review,
    update_question_bank,
    update_review,
)


def _bank_payload():
    return QuestionBankRecordCreate(
        job_title="后端开发",
        company="示例",
        resume_title="我的简历",
        groups=[
            {
                "type": "基础题",
                "questions": [
                    {"question": "请自我介绍", "purpose": "表达", "answer_hint": "STAR"}
                ],
            }
        ],
        model="",
    )


def _review_payload():
    return InterviewReviewRecordCreate(
        resume_title="我的简历",
        questions=["这个项目难点？"],
        analysis={
            "question": "这个项目难点？",
            "framework": "先讲背景",
            "key_points": [],
            "follow_up": [],
            "pitfalls": [],
        },
        suggestions=[],
        model="",
    )


def test_patch_question_bank_writes_back_answer(db_session):
    record = create_question_bank(db_session, _bank_payload())
    updated = update_question_bank(
        db_session,
        record.id,
        QuestionBankRecordUpdate(
            groups=[
                {
                    "type": "基础题",
                    "questions": [
                        {
                            "question": "请自我介绍",
                            "purpose": "表达",
                            "answer_hint": "STAR",
                            "answer": "围绕经历用 STAR 讲。",
                            "key_points": ["先结论"],
                            "sample_phrasing": "我在上份工作……",
                        }
                    ],
                }
            ]
        ),
    )
    assert updated is not None
    item = updated.groups[0]["questions"][0]
    assert item["answer"] == "围绕经历用 STAR 讲。"
    assert item["key_points"] == ["先结论"]
    assert item["sample_phrasing"] == "我在上份工作……"
    # 未提供的快照字段保持原值。
    assert updated.job_title == "后端开发"


def test_patch_question_bank_unknown_returns_none(db_session):
    assert update_question_bank(db_session, 9999, QuestionBankRecordUpdate(groups=[])) is None


def test_patch_review_writes_back_suggestions(db_session):
    record = create_review(db_session, _review_payload())
    updated = update_review(
        db_session,
        record.id,
        InterviewReviewRecordUpdate(
            suggestions=[
                {
                    "priority": "high",
                    "section": "项目经历",
                    "issue": "难点不量化",
                    "suggestion": "补指标",
                }
            ]
        ),
    )
    assert updated is not None
    assert updated.suggestions[0]["suggestion"] == "补指标"
    # 未提供的字段保持原值。
    assert updated.questions == ["这个项目难点？"]
    assert updated.analysis["framework"] == "先讲背景"
