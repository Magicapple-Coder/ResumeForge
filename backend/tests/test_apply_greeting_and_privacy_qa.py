"""对抗性测试：招呼语截断、空招呼语处理、凭据不落库、投递数据脱敏。

对应 P0-4（招呼语必须能预览且为空即拦截）与 P0-11（不保存任何招聘站点凭据、不记录完整资料）。
"""
from __future__ import annotations

from pathlib import Path

from app.database import Base
from app.models.apply import (
    FAILURE_GREETING_MISSING,
    ApplyQueueItem,
    ApplyTask,
    ApplyTaskItem,
    JobMatchAnalysis,
)
from app.models.job import Job
from app.models.resume import ResumeRecord
from app.schemas.apply import ApplyConfigIn, ApplyQueueAddRequest, GREETING_RECORD_MAX_CHARS
from app.services.apply import apply_service
from app.services.apply.apply_service import _clip_greeting
from app.services.browser.cdp_client import CdpClient
from app.services.job_match import parse_greeting
from app.services.llm.base import LLMError
from app.services.sites.boss import BossAdapter
from app.services.sites.base import SiteFailure

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ===== 招呼语截断 =====


def test_clip_greeting_truncates_to_the_record_limit():
    assert len(_clip_greeting("字" * 600)) == GREETING_RECORD_MAX_CHARS
    assert GREETING_RECORD_MAX_CHARS == 500
    # 空白被裁掉，避免把只有空格/换行的"招呼语"当成非空。
    assert _clip_greeting("   \n  ") == ""


def test_parse_greeting_truncates_but_rejects_empty_and_overlong():
    assert len(parse_greeting("a" * 800)) == GREETING_RECORD_MAX_CHARS
    with pytest.raises(LLMError):
        parse_greeting("")
    with pytest.raises(LLMError):
        parse_greeting("a" * 5000)


def test_queue_greeting_is_clipped_on_write(db_session):
    job = Job(title="后端开发", company="A公司", source="BOSS直聘", source_url="u")
    db_session.add(job)
    db_session.commit()

    created = apply_service.add_to_queue(
        db_session,
        ApplyQueueAddRequest(
            items=[{"job_id": job.id, "confirm_unanalyzed": True, "greeting": "x" * 900}]
        ),
    )
    stored = db_session.get(ApplyQueueItem, created[0].id)
    assert len(stored.greeting) == GREETING_RECORD_MAX_CHARS


def test_resolve_greeting_falls_back_to_default_when_item_is_empty():
    config = ApplyConfigIn(default_greeting="您好，我对该岗位很感兴趣。")
    item = ApplyQueueItem(job_id=1, greeting="   ")
    assert apply_service.resolve_greeting(item, config) == "您好，我对该岗位很感兴趣。"


def test_resolve_greeting_returns_empty_when_default_is_empty():
    config = ApplyConfigIn(default_greeting="")
    item = ApplyQueueItem(job_id=1, greeting="")
    assert apply_service.resolve_greeting(item, config) == ""


# ===== 招呼语必填但为空 → 明确失败分类（不静默失败） =====


class _ScriptedCdp(CdpClient):
    """按调用顺序返回脚本化页面状态，模拟 BOSS 适配器的几次 evaluate。"""

    def __init__(self, results: list) -> None:
        self._results = list(results)
        self._i = 0

    def _next(self):
        if self._i < len(self._results):
            value = self._results[self._i]
            self._i += 1
            return value
        return None

    def list_targets(self):
        return []

    def new_tab(self, url: str = "about:blank") -> str:
        return "t1"

    def send(self, method, params=None, *, timeout=None):
        return {}

    def evaluate(self, expression, *, timeout=None):
        return self._next()

    def set_file_input(self, selector, files, *, timeout=None):
        return None

    def navigate(self, url, *, timeout=None):
        return {}

    def close(self):
        return None


def test_required_but_empty_greeting_raises_greeting_missing():
    # 调用顺序：entry 状态（found）→ click-apply → form controls（[]）→ greeting_state（required & 未填）
    import json

    entry = json.dumps({"found": True, "url": "u", "title": "t", "matched": 1})
    controls = json.dumps({"url": "u", "title": "t", "controls": []})
    greeting_state = json.dumps({"found": True, "required": True, "url": "u", "title": "t"})
    client = _ScriptedCdp([entry, entry, controls, greeting_state])
    adapter = BossAdapter()
    with pytest.raises(SiteFailure) as exc:
        adapter.fill_and_submit(client, {}, "")
    assert exc.value.category == FAILURE_GREETING_MISSING
    assert "招呼语" in exc.value.detail


def test_non_required_empty_greeting_does_not_block_greeting_step():
    import json

    entry = json.dumps({"found": True, "url": "u", "title": "t", "matched": 1})
    controls = json.dumps({"url": "u", "title": "t", "controls": []})
    greeting_state = json.dumps({"found": True, "required": False, "url": "u", "title": "t"})
    submit_state = json.dumps({"success": True, "url": "u", "title": "t"})
    # entry → click-apply → controls → greeting_state → click-submit → submit-state
    client = _ScriptedCdp([entry, entry, controls, greeting_state, "{}", submit_state])
    adapter = BossAdapter()
    outcome = adapter.fill_and_submit(client, {}, "")
    assert outcome.success is True


# ===== 凭据不落库 =====


def _column_names() -> dict[str, set[str]]:
    columns: dict[str, set[str]] = {}
    for table in Base.metadata.sorted_tables:
        columns[table.name] = {column.name for column in table.columns}
    return columns


def test_no_credential_like_column_anywhere():
    """投递相关的表不得出现密码 / Cookie / 令牌 / 验证码字段。

    只针对本次新增的 apply / job_match 表做严格检查（``max_tokens`` 这类合法列名会被
    误伤，所以不在这里用裸 ``token`` 做全局匹配）。
    """
    forbidden = (
        "password",
        "passwd",
        "cookie",
        "secret",
        "credential",
        "captcha",
        "session_key",
        "api_key",
        "access_token",
        "refresh_token",
        "auth_token",
        "verify_code",
    )
    columns = _column_names()
    apply_tables = {"job_match_analysis", "apply_queue_item", "apply_task", "apply_task_item"}
    for table in apply_tables:
        for column in columns[table]:
            lowered = column.lower()
            assert not any(bad in lowered for bad in forbidden), f"{table}.{column} 疑似凭据字段"


def test_apply_tables_match_the_design_contract():
    columns = _column_names()
    assert set(columns["apply_task_item"]) == {
        "id",
        "task_id",
        "job_id",
        "job_title",
        "company",
        "resume_id",
        "resume_title",
        "greeting",
        "status",
        "failure_category",
        "failure_detail",
        "attempt",
        "sort_order",
        "started_at",
        "finished_at",
        "created_at",
    }
    # 投递表只保留展示快照，不留完整资料 blob。
    assert "profile" not in columns["apply_task_item"]
    assert "content" not in columns["apply_task_item"]


def test_browser_profile_dir_is_gitignored():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "backend/data/browser-profile/" in gitignore


# ===== 投递数据只取必需字段，不含完整资料 =====


def test_build_apply_data_excludes_sensitive_profile_fields(db_session):
    from app.models.profile import UserProfile

    profile = UserProfile(
        name="张三",
        phone="13800000000",
        email="a@b.com",
        city="上海",
        target_city="北京",
        job_intent="后端工程师",
        summary="简介",
        photo="BASE64-IMAGE-DATA",
    )
    db_session.add(profile)
    db_session.commit()

    data = apply_service.build_apply_data(db_session, None)
    assert set(data) <= {"name", "phone", "email", "city", "job_intent", "summary"}
    assert "photo" not in data
    assert "BASE64" not in str(data)


def test_build_apply_data_does_not_leak_resume_content(db_session):
    resume = ResumeRecord(
        title="后端版", job_id=None, job_title="后端", content={"secret": "fULL-RESUME-BODY"}
    )
    db_session.add(resume)
    db_session.commit()

    data = apply_service.build_apply_data(db_session, resume)
    assert "FULL-RESUME-BODY" not in str(data)
    assert "secret" not in data


def test_apply_models_are_the_four_expected_tables():
    for model in (JobMatchAnalysis, ApplyQueueItem, ApplyTask, ApplyTaskItem):
        assert model.__tablename__ in Base.metadata.tables
