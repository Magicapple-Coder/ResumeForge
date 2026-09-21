"""投递记录按批次分组的守卫测试。

用户一次性投了好几个岗位时，这几条记录同属一个批次（一次「开始投递」= 一个
``ApplyTask``）。分组展示的语义：

- 分组键是**批次**，分页也按批次计（一页 N 个组）；
- 筛选（关键词 / 结果）作用在**记录**上：组内只出现命中的记录，没有命中记录的
  批次整体不出现；
- 批次头上的统计（成功/失败/跳过）是**批次自己的账**，不因筛选而变。
"""
import pytest

from app.models.apply import (
    TASK_KIND_APPLY,
    ITEM_STATUS_FAILED,
    ITEM_STATUS_SKIPPED,
    ITEM_STATUS_SUCCESS,
    TASK_STATUS_COMPLETED,
    ApplyTask,
    ApplyTaskItem,
)
from app.services.apply import apply_service


@pytest.fixture
def batch_with_items(db_session):
    """两个批次：第一个 3 条（成/败/跳），第二个 1 条（成）。"""
    task_a = ApplyTask(
        kind=TASK_KIND_APPLY,
        status=TASK_STATUS_COMPLETED,
        total=3,
        processed=3,
        succeeded=1,
        failed=1,
        skipped=1,
        message="投递任务已完成",
    )
    task_b = ApplyTask(
        kind=TASK_KIND_APPLY,
        status=TASK_STATUS_COMPLETED,
        total=1,
        processed=1,
        succeeded=1,
    )
    db_session.add_all([task_a, task_b])
    db_session.flush()

    def item(task, sort_order, status, title, company):
        row = ApplyTaskItem(
            task_id=task.id,
            job_id=None,
            job_title=title,
            company=company,
            status=status,
            sort_order=sort_order,
        )
        db_session.add(row)
        return row

    item(task_a, 0, ITEM_STATUS_SUCCESS, "后端开发", "A公司")
    item(task_a, 1, ITEM_STATUS_FAILED, "全栈工程师", "B公司")
    item(task_a, 2, ITEM_STATUS_SKIPPED, "测试工程师", "C公司")
    item(task_b, 0, ITEM_STATUS_SUCCESS, "后端开发", "D公司")
    db_session.commit()
    return task_a, task_b


def test_batches_group_all_items_and_paginate_by_batch(db_session, batch_with_items):
    task_a, task_b = batch_with_items
    batches, total = apply_service.list_record_batches(db_session)
    assert total == 2
    assert [batch.id for batch in batches] == [task_b.id, task_a.id]  # 新批次在前
    first = batches[0]
    assert first.total == 1 and first.succeeded == 1
    assert [record.job_title for record in first.items] == ["后端开发"]
    second = batches[1]
    assert second.succeeded == 1 and second.failed == 1 and second.skipped == 1
    assert [record.status for record in second.items] == ["success", "failed", "skipped"]


def test_batch_page_size_limits_groups_not_records(db_session, batch_with_items):
    task_a, task_b = batch_with_items
    batches, total = apply_service.list_record_batches(db_session, page=1, page_size=1)
    assert total == 2
    assert len(batches) == 1
    assert batches[0].id == task_b.id
    # 第二页是剩下的那个批次，且它带全自己的 3 条记录。
    batches, total = apply_service.list_record_batches(db_session, page=2, page_size=1)
    assert total == 2
    assert [batch.id for batch in batches] == [task_a.id]
    assert len(batches[0].items) == 3


def test_result_filter_hides_records_and_empty_batches(db_session, batch_with_items):
    task_a, task_b = batch_with_items
    batches, total = apply_service.list_record_batches(db_session, result="failed")
    assert total == 1
    assert [batch.id for batch in batches] == [task_a.id]
    assert [record.job_title for record in batches[0].items] == ["全栈工程师"]
    # 批次统计不受筛选影响——它是这次投递自己的账。
    assert batches[0].failed == 1 and batches[0].succeeded == 1 and batches[0].skipped == 1


def test_keyword_filter_matches_title_or_company(db_session, batch_with_items):
    task_a, _ = batch_with_items
    batches, total = apply_service.list_record_batches(db_session, keyword="C公司")
    assert total == 1 and batches[0].id == task_a.id
    assert [record.company for record in batches[0].items] == ["C公司"]
