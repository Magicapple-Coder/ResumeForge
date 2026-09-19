"""简历版本三态差异：行级 + 词级，唯一实现于 services/resume_diff.py。"""
from app.models.resume import ResumeRecord
from app.services.resume_diff import (
    _to_lines,
    _word_pair_diff,
    build_resume_diff,
    diff_lines,
)


def test_to_lines_is_deterministic_and_key_sorted():
    content_a = {"name": "张三", "skills": [{"name": "Python", "level": "熟练"}]}
    content_b = {"skills": [{"name": "Python", "level": "熟练"}], "name": "张三"}
    assert _to_lines(content_a) == _to_lines(content_b)
    # 空 dict 序列化成一行 "{}"；非 dict 输入安全返回空行序列。
    assert _to_lines({}) == ["{}"]
    assert _to_lines(None) == []


def test_diff_lines_marks_added_removed_and_unchanged():
    lines = diff_lines(["a", "b", "c"], ["a", "x", "c"])
    assert [line.type for line in lines] == ["unchanged", "removed", "added", "unchanged"]
    assert lines[1].text == "b"
    assert lines[2].text == "x"


def test_word_level_diff_marks_changed_words():
    base_tokens, target_tokens = _word_pair_diff("负责 后端 服务 开发", "负责 前端 服务 开发")
    assert [token.type for token in base_tokens] == ["unchanged", "removed", "unchanged", "unchanged"]
    assert [token.type for token in target_tokens] == ["unchanged", "added", "unchanged", "unchanged"]
    assert base_tokens[1].text == "后端"
    assert target_tokens[1].text == "前端"


def test_build_resume_diff_computes_stats():
    diff = build_resume_diff(
        1, "版本 A", {"name": "张三"}, 2, "版本 B", {"name": "李四"}
    )
    assert diff.base_id == 1
    assert diff.against_id == 2
    assert diff.base_title == "版本 A"
    assert diff.against_title == "版本 B"
    assert diff.stats.added >= 1
    assert diff.stats.removed >= 1
    assert diff.stats.added == diff.stats.removed  # name 行改写：成对 added + removed
    assert any(line.type == "unchanged" for line in diff.lines)


def test_diff_endpoint_returns_three_states(client, db_session):
    base = ResumeRecord(title="版本 A", job_title="后端", company="示例", content={"name": "张三"})
    against = ResumeRecord(title="版本 B", job_title="后端", company="示例", content={"name": "李四"})
    db_session.add_all([base, against])
    db_session.commit()
    db_session.refresh(base)
    db_session.refresh(against)

    response = client.post(f"/api/resumes/{base.id}/diff", json={"against_id": against.id})

    assert response.status_code == 200
    body = response.json()
    assert body["base_id"] == base.id
    assert body["against_id"] == against.id
    assert body["stats"]["added"] >= 1
    assert body["stats"]["removed"] >= 1
    types = {line["type"] for line in body["lines"]}
    assert types <= {"added", "removed", "unchanged"}


def test_diff_endpoint_rejects_same_resume(client, db_session):
    record = ResumeRecord(title="版本 A", job_title="后端", company="示例", content={"name": "张三"})
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    response = client.post(f"/api/resumes/{record.id}/diff", json={"against_id": record.id})

    assert response.status_code == 400
    assert "同一份" in response.json()["detail"]
