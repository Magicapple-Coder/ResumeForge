"""回收站：软删除、恢复、彻底删除，以及"删掉之后到处都看不到"。

**为什么这条测试比平常重要**：软删除的成本全在"每一条读取路径都要排除它"。少排除一处，
用户就会看到"删了但首页统计里还有一条"，而这类半成品对删除功能的信任是毁灭性的
（下次他就不敢删了）。所以这里**逐入口**验，而不是抽查一个列表接口。
"""
import pytest

from app.models.assistant import ChatConversation
from app.models.claim import ClaimRecord
from app.models.job import Job
from app.models.material import Material
from app.models.question_bank_record import QuestionBankRecord
from app.models.resume import ResumeRecord
from app.models.tracker import ApplicationTrack
from app.services import trash


def _count(payload) -> int:
    """从各种列表响应里取条数（Page / 裸列表 / 带 items 的自定义结构）。"""
    if isinstance(payload, list):
        return len(payload)
    for key in ("items", "tracks", "claims", "records"):
        if isinstance(payload.get(key), list):
            return len(payload[key])
    raise AssertionError(f"看不懂的列表响应：{list(payload)[:8]}")


MAKERS = {
    "job": lambda db: Job(title="待删岗位", company="某公司"),
    "resume": lambda db: ResumeRecord(title="待删简历"),
    "track": lambda db: ApplicationTrack(title="待删投递", company="某公司"),
    "claim": lambda db: ClaimRecord(title="待删台账", source_fact="负责过服务端开发"),
    "material": lambda db: Material(title="待删资料"),
    "conversation": lambda db: ChatConversation(title="待删会话"),
}

LIST_URLS = {
    "job": "/api/jobs",
    "resume": "/api/resumes",
    "track": "/api/tracker",
    "claim": "/api/claims",
    "material": "/api/materials",
    "conversation": "/api/assistant/conversations",
}

DELETE_URLS = {
    "job": "/api/jobs/{id}",
    "resume": "/api/resumes/{id}",
    "track": "/api/tracker/{id}",
    "claim": "/api/claims/{id}",
    "material": "/api/materials/{id}",
    "conversation": "/api/assistant/conversations/{id}",
}


def _create(db_session, type_key: str):
    row = MAKERS[type_key](db_session)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


# ===== 逐入口：删掉之后列表里必须没有它 =====


@pytest.mark.parametrize("type_key", sorted(MAKERS))
def test_deleting_moves_it_out_of_the_list_into_the_trash(db_session, client, type_key):
    row = _create(db_session, type_key)

    before = client.get(LIST_URLS[type_key]).json()
    assert _count(before) == 1

    response = client.delete(DELETE_URLS[type_key].format(id=row.id))
    assert response.status_code == 204

    # ① 列表里没有了
    after = client.get(LIST_URLS[type_key]).json()
    assert _count(after) == 0, f"{type_key} 删除后仍出现在 {LIST_URLS[type_key]}"

    # ② 但回收站里能看到，而且带类型标签
    summary = client.get("/api/trash").json()
    mine = [item for item in summary["items"] if item["type"] == type_key]
    assert [item["id"] for item in mine] == [row.id]
    assert mine[0]["type_label"] == summary["labels"][type_key]
    assert mine[0]["title"]


@pytest.mark.parametrize("type_key", sorted(MAKERS))
def test_deleting_twice_is_rejected(db_session, client, type_key):
    """已经在回收站里的内容不该还能被"再删一次"——那会让它在回收站里不断上浮。"""
    row = _create(db_session, type_key)
    assert client.delete(DELETE_URLS[type_key].format(id=row.id)).status_code == 204

    assert client.delete(DELETE_URLS[type_key].format(id=row.id)).status_code == 404


# ===== 首页统计与全局搜索：最容易漏的两处 =====


def test_deleted_rows_are_gone_from_the_home_stats(db_session, client):
    """首页统计必须排除回收站内容。

    这是最容易漏的一处：删了岗位但首页还显示"岗位 3"，用户会以为删除没生效，
    于是去删第二遍——而第二遍已经 404 了。
    """
    db_session.add_all([Job(title="岗位A"), Job(title="岗位B"), ResumeRecord(title="简历A")])
    db_session.commit()
    job_a = db_session.query(Job).filter(Job.title == "岗位A").one()

    assert client.get("/api/stats").json()["job_count"] == 2

    client.delete(f"/api/jobs/{job_a.id}")

    stats = client.get("/api/stats").json()
    assert stats["job_count"] == 1
    assert all(item["title"] != "岗位A" for item in stats["latest_jobs"])


def test_deleted_rows_are_gone_from_the_global_search(db_session, client):
    job = _create(db_session, "job")

    assert client.get("/api/search", params={"q": "待删岗位"}).json()["jobs"]
    client.delete(f"/api/jobs/{job.id}")
    assert client.get("/api/search", params={"q": "待删岗位"}).json()["jobs"] == []


# ===== 恢复与彻底删除 =====


def test_restore_brings_it_back_unchanged(db_session, client):
    """恢复之后要"原样回来"——包括它和岗位的关联关系（简历记录挂在岗位上）。"""
    job = _create(db_session, "job")
    resume = ResumeRecord(title="关联简历", job_id=job.id)
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(resume)

    client.delete(f"/api/resumes/{resume.id}")
    assert _count(client.get("/api/resumes").json()) == 0

    assert client.post(f"/api/trash/resume/{resume.id}/restore").status_code == 204

    assert _count(client.get("/api/resumes").json()) == 1
    # 关联关系（外键）与内容都还在，没有被软删除过程破坏。
    db_session.refresh(resume)
    assert resume.job_id == job.id
    assert resume.deleted_at is None


def test_restore_is_rejected_for_something_not_in_the_trash(db_session, client):
    job = _create(db_session, "job")

    response = client.post(f"/api/trash/job/{job.id}/restore")

    assert response.status_code == 404


def test_purge_removes_it_for_good(db_session, client):
    job = _create(db_session, "job")
    client.delete(f"/api/jobs/{job.id}")

    assert client.delete(f"/api/trash/job/{job.id}").status_code == 204

    # 彻底删除发生在**另一个 session**（API 的那一个）里。用 expunge_all 把本地对象彻底
    # 摘出去再查：只用 expire_all 的话，身份映射里那个"已过期但存在"的实例刷新时会抛
    # ObjectDeletedError（而不是干净地返回 None），测试就变成在断言 SQLAlchemy 的细节。
    db_session.expunge_all()
    assert db_session.query(Job).filter(Job.id == job.id).first() is None
    assert client.get("/api/trash").json()["items"] == []
    # 已经彻底删掉的东西不能再"恢复"——否则会造出一条 id 对不上的幽灵记录。
    assert client.post(f"/api/trash/job/{job.id}/restore").status_code == 404


def test_purge_refuses_items_that_are_not_in_the_trash(db_session, client):
    """**必须先删（进回收站）才能彻底删**：界面上因此不存在"点一下就没了"的路径。"""
    job = _create(db_session, "job")

    assert client.delete(f"/api/trash/job/{job.id}").status_code == 404
    # 而且它确实还在
    assert db_session.get(Job, job.id) is not None


# ===== 批量恢复 / 批量彻底删除 =====


def test_batch_restore_brings_back_every_selected_item(db_session, client):
    a = _create(db_session, "job")
    b = _create(db_session, "job")
    c = _create(db_session, "claim")
    client.delete(f"/api/jobs/{a.id}")
    client.delete(f"/api/jobs/{b.id}")
    client.delete(f"/api/claims/{c.id}")

    response = client.post(
        "/api/trash/restore",
        json={"items": [{"type_key": "job", "id": a.id}, {"type_key": "claim", "id": c.id}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["restored"] == 2
    assert {r["id"] for r in body["results"] if r["ok"]} == {a.id, c.id}
    # 恢复的回到列表；没被选中的 b 仍在回收站里。
    assert _count(client.get("/api/jobs").json()) == 1
    assert b.id in {item["id"] for item in client.get("/api/trash").json()["items"]}


def test_batch_restore_reports_failures_per_item(db_session, client):
    a = _create(db_session, "job")
    client.delete(f"/api/jobs/{a.id}")

    body = client.post(
        "/api/trash/restore",
        json={
            "items": [
                {"type_key": "job", "id": a.id},
                {"type_key": "job", "id": 999999},
                {"type_key": "不存在", "id": 1},
            ]
        },
    ).json()

    assert body["restored"] == 1
    outcomes = {(r["type_key"], r["id"]): r["ok"] for r in body["results"]}
    assert outcomes[("job", a.id)] is True
    assert outcomes[("job", 999999)] is False
    assert outcomes[("不存在", 1)] is False


def test_batch_purge_removes_selected_items_for_good(db_session, client):
    a = _create(db_session, "job")
    b = _create(db_session, "job")
    client.delete(f"/api/jobs/{a.id}")
    client.delete(f"/api/jobs/{b.id}")

    body = client.post(
        "/api/trash/purge", json={"items": [{"type_key": "job", "id": a.id}]}
    ).json()

    assert body["purged"] == 1
    assert body["results"][0]["ok"] is True
    db_session.expunge_all()
    assert db_session.get(Job, a.id) is None
    # 没被选中的 b 仍在回收站里，不受影响。
    assert db_session.get(Job, b.id) is not None


def test_batch_purge_refuses_items_not_in_the_trash(db_session, client):
    a = _create(db_session, "job")

    body = client.post(
        "/api/trash/purge", json={"items": [{"type_key": "job", "id": a.id}]}
    ).json()

    assert body["purged"] == 0
    assert body["results"][0]["ok"] is False
    assert db_session.get(Job, a.id) is not None


def test_empty_trash_reports_how_many_were_removed(db_session, client):
    """清空要回报**真正删掉多少条**——用户点"清空"时最想知道的就是这个数。"""
    for _ in range(2):
        item = _create(db_session, "claim")
        client.delete(f"/api/claims/{item.id}")
    assert client.get("/api/trash").json()["total"] == 2

    response = client.request("DELETE", "/api/trash")

    assert response.status_code == 200
    assert response.json()["removed"] == 2
    assert client.get("/api/trash").json()["total"] == 0


def test_trash_can_be_filtered_by_type(db_session, client):
    job = _create(db_session, "job")
    claim = _create(db_session, "claim")
    client.delete(f"/api/jobs/{job.id}")
    client.delete(f"/api/claims/{claim.id}")

    only_jobs = client.get("/api/trash", params={"type": "job"}).json()

    assert [item["type"] for item in only_jobs["items"]] == ["job"]
    # 计数仍然给出全量，这样界面上的角标不会因为筛选而变小。
    assert only_jobs["counts"]["job"] == 1
    assert only_jobs["counts"]["claim"] == 1


def test_unknown_type_is_rejected(client):
    assert client.get("/api/trash", params={"type": "不存在"}).status_code == 404


# ===== 与去重的接合点（最容易出错的业务逻辑）=====


def test_dedupe_still_recognises_a_trashed_job(db_session):
    """去重**必须**把回收站里的岗位视为"已存在"。

    否则"删掉 → 再采集一次"会造出第二条同一岗位，而用户以为自己只是删了一条；
    调用方据此给「在回收站里」的提示。
    """
    from app.services.job.job_service import find_job_by_identity

    job = Job(title="已删岗位", company="某公司", source_url="https://example.com/x")
    db_session.add(job)
    db_session.commit()
    trash.soft_delete(db_session, "job", job)
    db_session.commit()

    found = find_job_by_identity(
        db_session, title="已删岗位", company="某公司", source_url="https://example.com/x"
    )

    assert found is not None and found.id == job.id
    assert trash.is_deleted(found)


def test_every_deleted_at_table_is_registered():
    """含 ``deleted_at`` 列的表必须与回收站注册表**一一对应**。

    只比迁移 0016 的清单会漏掉 0018 新建的 4 张表（它们建表时就带 ``deleted_at``，而不是后来
    ALTER 加的），于是"半软删"这种漂移不会变红。这里改用 ``Base.metadata`` 扫全库，任何一张
    带 ``deleted_at`` 的表漏登记（或登记了却没有该列）都会直接变红。
    """
    from app import models  # noqa: F401 - 确保全部模型注册到 Base.metadata
    from app.database import Base

    soft_deleted = {
        name for name, table in Base.metadata.tables.items() if "deleted_at" in table.columns
    }
    assert soft_deleted == set(trash.TRASHED_TABLES)
    # 6（0016）+ 4（0018）+ 3（0019）= 13 类。
    assert len(trash.TRASHED_TABLES) == 13
    assert "job" in trash.TRASHED_TABLES and "chat_conversation" in trash.TRASHED_TABLES
    assert {
        "interview_experience",
        "referral",
        "reminder",
        "share_package",
    } <= set(trash.TRASHED_TABLES)
    assert {
        "question_bank_record",
        "interview_review_record",
        "knowledge_entry",
    } <= set(trash.TRASHED_TABLES)


def test_interview_experience_full_trash_cycle(client):
    """面经走完整闭环：删除 → 进回收站 → 恢复 → 再删 → 彻底删除（防「半软删」回归）。

    这条是 QA 揪出的真实 bug 的回归用例：0018 的 4 张新表带 ``deleted_at`` 却不在回收站注册表，
    删除后面经在列表消失、回收站里也找不到，既不能恢复也无法彻底删除，形成永久僵尸行。
    """
    created = client.post(
        "/api/interview-experiences",
        json={"title": "闭环面经", "company": "某司", "content": "先问八股再深挖项目"},
    )
    assert created.status_code == 201, created.text
    experience_id = created.json()["id"]

    # ① 删除 → 面经列表消失。
    assert client.delete(f"/api/interview-experiences/{experience_id}").status_code == 204
    assert client.get("/api/interview-experiences").json() == []

    # ② 出现在回收站，带「面经」类型标签。
    summary = client.get("/api/trash").json()
    mine = [item for item in summary["items"] if item["type"] == "interview_experience"]
    assert [item["id"] for item in mine] == [experience_id]
    assert mine[0]["type_label"] == "面经"

    # ③ 恢复 → 面经列表回来。
    assert (
        client.post(f"/api/trash/interview_experience/{experience_id}/restore").status_code
        == 204
    )
    assert len(client.get("/api/interview-experiences").json()) == 1

    # ④ 再删 → 彻底删除（不可恢复）。
    assert client.delete(f"/api/interview-experiences/{experience_id}").status_code == 204
    assert (
        client.delete(f"/api/trash/interview_experience/{experience_id}").status_code == 204
    )
    assert client.get("/api/trash").json()["items"] == []
    assert client.get("/api/interview-experiences").json() == []


def test_question_bank_history_full_trash_cycle(db_session):
    """0019 新表走完整闭环：删除 → 进回收站 → 恢复 → 再删 → 彻底删除。

    与 ``test_interview_experience_full_trash_cycle`` 同性质：新表带 ``deleted_at`` 就必须在
    回收站注册表里，否则"删除后列表消失、回收站也找不到"，形成永久僵尸行。
    """
    record = QuestionBankRecord(
        resume_title="后端题库", groups=[{"type": "基础题", "questions": []}]
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    # ① 软删除 → 回收站里能看到，标题用 resume_title。
    trash.soft_delete(db_session, "question_bank_record", record)
    db_session.commit()
    assert trash.is_deleted(record)
    assert [item["type"] for item in trash.list_trashed(db_session, key="question_bank_record")] == [
        "question_bank_record"
    ]

    # ② 恢复 → 回到 live。
    assert trash.restore(db_session, "question_bank_record", record.id)
    db_session.refresh(record)
    assert not trash.is_deleted(record)

    # ③ 再删 → 彻底删除（真删，不可恢复）。
    trash.soft_delete(db_session, "question_bank_record", record)
    db_session.commit()
    assert trash.purge(db_session, "question_bank_record", record.id)
    db_session.expunge_all()
    assert db_session.get(QuestionBankRecord, record.id) is None
