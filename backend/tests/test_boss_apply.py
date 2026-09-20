"""BOSS 沟通流程：语义入口、contenteditable、真实发送与结果确认。"""
from __future__ import annotations

import json

import pytest

from app.models.apply import FAILURE_SELECTOR_INVALID
from app.services.browser.cdp_client import CdpClient
from app.services.browser.page_ready import ReadyWait
from app.services.sites.base import SiteFailure
from app.services.sites.boss import BossAdapter
from app.services.sites.boss_apply import (
    _apply_entry_script,
    _fill_greeting_script,
)

FAST_WAIT = ReadyWait(timeout=0.02, poll_interval=0.001)


class MarkerClient(CdpClient):
    def __init__(self, responses):
        self.responses = {
            marker: list(value) if isinstance(value, list) else [value]
            for marker, value in responses.items()
        }
        self.expressions: list[str] = []

    def list_targets(self):
        return []

    def new_tab(self, url: str = "about:blank") -> str:
        return "tab"

    def navigate(self, url: str, *, timeout=None):
        return {}

    def send(self, method, params=None, *, timeout=None):
        return {}

    def evaluate(self, expression, *, timeout=None):
        self.expressions.append(expression)
        for marker, values in self.responses.items():
            if marker in expression:
                if len(values) > 1:
                    return values.pop(0)
                return values[0]
        return None

    def close(self):
        return None


def _responses(greeting="您好，我很感兴趣"):
    return {
        "rf:apply-entry": {"found": True, "matched": 1, "label": "继续沟通"},
        "rf:click-apply": {"ok": True, "label": "继续沟通"},
        "rf:form-controls": json.dumps({"controls": []}),
        "rf:greeting-state": [
            {"found": False, "matched": 0},
            {"found": True, "matched": 1, "kind": "contenteditable", "required": False},
        ],
        "rf:fill-greeting": {"ok": True, "value": greeting},
        "rf:click-send": {"ok": True, "label": "发送"},
        "rf:submit-state": [
            {"success": False, "matched": 1},
            {"success": True, "sent_message": True, "matched": 1},
        ],
    }


def test_entry_discovery_is_semantic_for_start_and_continue_chat():
    script = _apply_entry_script()
    assert "立即沟通" in script
    assert "继续沟通" in script
    assert "role=\"button\"" in script or "[role='button']" in script


def test_greeting_writer_supports_contenteditable_and_dispatches_input():
    script = _fill_greeting_script("您好")
    assert "isContentEditable" in script
    assert "textContent" in script
    assert "input" in script


def test_open_apply_ignores_a_stale_previous_job_until_the_target_page_appears():
    target = "https://www.zhipin.com/job_detail/new.html"
    client = MarkerClient(
        {
            "rf:url": {"url": "https://www.zhipin.com/job_detail/old.html"},
            "rf:apply-entry": [
                {
                    "found": True,
                    "matched": 1,
                    "url": "https://www.zhipin.com/job_detail/old.html",
                },
                {"found": True, "matched": 1, "url": target},
            ],
        }
    )
    job = type("Job", (), {"source_url": target})()

    BossAdapter(ready_wait=FAST_WAIT).open_apply(client, job)

    assert sum("rf:apply-entry" in item for item in client.expressions) >= 2


def test_fill_and_submit_waits_for_composer_clicks_send_and_waits_for_confirmation():
    greeting = "您好，我很感兴趣"
    client = MarkerClient(_responses(greeting))

    outcome = BossAdapter(ready_wait=FAST_WAIT).fill_and_submit(client, {}, greeting)

    assert outcome.success is True
    assert outcome.greeting_sent == greeting
    assert sum("rf:greeting-state" in item for item in client.expressions) >= 2
    assert any("rf:click-send" in item for item in client.expressions)
    assert sum("rf:submit-state" in item for item in client.expressions) >= 2


def test_missing_real_send_control_is_an_explicit_failure():
    responses = _responses()
    responses["rf:click-send"] = {"ok": False, "matched": 0, "url": "u", "title": "聊天"}
    client = MarkerClient(responses)

    with pytest.raises(SiteFailure) as excinfo:
        BossAdapter(ready_wait=FAST_WAIT).fill_and_submit(client, {}, "您好，我很感兴趣")

    assert excinfo.value.category == FAILURE_SELECTOR_INVALID
    assert "发送" in excinfo.value.detail


def test_clicking_send_without_confirmation_times_out_instead_of_claiming_success():
    responses = _responses()
    responses["rf:submit-state"] = {
        "success": False,
        "matched": 1,
        "url": "u",
        "title": "聊天",
    }
    client = MarkerClient(responses)

    with pytest.raises(SiteFailure) as excinfo:
        BossAdapter(ready_wait=FAST_WAIT).fill_and_submit(client, {}, "您好，我很感兴趣")

    assert excinfo.value.category == FAILURE_SELECTOR_INVALID
    assert "发送结果" in excinfo.value.detail
