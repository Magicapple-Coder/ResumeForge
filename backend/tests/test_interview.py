"""模拟面试：提示词构造、解析归一化与接口流程。

重点验证"流程由代码控制"这条设计：轮数到了必须收尾、报告结构不对时要能容错、
模型返回残缺 JSON 时要给出可读的错误，而不是把半成品写进界面。
"""
import json

import pytest

from app.models.interview import InterviewSession
from app.schemas.interview import InterviewCreate
from app.services.interview.interview import (
    answered_rounds,
    build_interview_messages,
    build_report_messages,
    parse_report,
    parse_turn,
)
from app.services.llm.base import LLMError

_DEFAULT_REPORT = {
    "score": 80,
    "dimensions": [{"name": "技术", "score": 80, "comment": "细节到位"}],
    "strengths": ["结构清楚"],
    "improvements": ["补充数据"],
    "summary": "整体不错",
}


def _session(**overrides) -> InterviewSession:
    values = {
        "title": "后端开发 模拟面试",
        "job_title": "后端开发工程师",
        "company": "示例公司",
        "interview_type": "技术面",
        "difficulty": "中级",
        "interviewer_style": "持续追问",
        "rounds": 3,
        "focus": "Go 并发",
        "persona": "",
    }
    values.update(overrides)
    return InterviewSession(**values)


def _turn_jsons(count: int, *, done: bool = False) -> list[str]:
    return [
        json.dumps({"question": f"第 {index} 题", "feedback": "点评", "done": done})
        for index in range(1, count + 1)
    ]


def _configure_provider(monkeypatch, replies: list[str]) -> None:
    """只把 provider 换成按顺序返回预设 JSON 的假实现，其余流程全走真实代码。

    与 `_configure` 的区别很关键：那个把 `_ask_next_question` 整个换掉，连同它里面的
    轮次越界检查一起绕过了，凡是"检查发生在那一层"的用例都会变成假绿。
    """

    class _Provider:
        def __init__(self) -> None:
            self.replies = list(replies)

        async def chat(self, _messages):
            return self.replies.pop(0) if self.replies else json.dumps(
                {"question": "收尾", "feedback": "", "done": True}
            )

    async def build_report(_provider, _session_):
        return _DEFAULT_REPORT

    monkeypatch.setattr(
        "app.api.interview._require_provider", lambda _db: (_Provider(), "test-model")
    )
    monkeypatch.setattr("app.api.interview.generate_report", build_report)


def _configure(monkeypatch, turns: list[dict], report: dict | None = None) -> None:
    """把面试官与报告都换成按顺序返回预设内容的假实现（不联网、不解析模型输出）。"""
    queue = list(turns)

    async def ask(_db, _session_, _provider):
        payload = queue.pop(0) if queue else {"question": "", "feedback": "", "done": True}
        question = str(payload.get("question") or "")
        if not question:
            raise LLMError("面试官没有给出下一个问题")
        return question, str(payload.get("feedback") or ""), bool(payload.get("done"))

    async def build_report(_provider, _session_):
        return report or _DEFAULT_REPORT

    monkeypatch.setattr("app.api.interview._require_provider", lambda _db: (None, "test-model"))
    monkeypatch.setattr("app.api.interview._ask_next_question", ask)
    monkeypatch.setattr("app.api.interview.generate_report", build_report)


def test_parse_turn_requires_a_question():
    question, feedback, done = parse_turn(
        json.dumps({"question": "讲讲你做过的高并发项目", "feedback": "开头不错", "done": False})
    )
    assert question.startswith("讲讲")
    assert feedback == "开头不错"
    assert done is False

    # 没有问题时必须报错：静默通过会让界面停在"等面试官提问"。
    with pytest.raises(LLMError):
        parse_turn(json.dumps({"feedback": "还不错"}))


def test_parse_report_normalizes_messy_output():
    report = parse_report(
        json.dumps(
            {
                "score": "78",  # 字符串分数
                "dimensions": [
                    {"name": "技术", "score": 120, "comment": "超出范围"},  # 夹到 100
                    {"score": 60},  # 缺 name → 丢掉
                    "不是对象",  # 丢掉
                ],
                "strengths": "只写了一条字符串",  # 字符串 → 单元素数组
                "improvements": ["a", "b"],
                "summary": "总评",
            }
        )
    )
    assert report["score"] == 78
    assert [item["name"] for item in report["dimensions"]] == ["技术"]
    assert report["dimensions"][0]["score"] == 100
    assert report["strengths"] == ["只写了一条字符串"]


def test_profile_text_is_json_serializable(client, monkeypatch):
    """真实 E2E 暴露的问题：资料里带 datetime，`model_dump()` 后 json.dumps 会直接抛 TypeError。

    这条测试刻意**不**打桩 ``_ask_next_question``——它要覆盖的正是那段代码路径
    （打桩会把出错的位置一起绕过，这正是当初没测出来的原因）。
    """
    from app.api.interview import _profile_text

    client.put(
        "/api/profile",
        json={"name": "张三", "phone": "13800000000", "city": "上海", "summary": "3 年经验"},
    )

    from app.database import SessionLocal

    with SessionLocal() as db:
        text = _profile_text(db)
    assert "张三" in text
    # 能被 json.loads 解析回来，说明 datetime 已经被转成字符串。
    assert json.loads(text)["name"] == "张三"


def test_messages_include_profile_job_and_rules():
    session = _session()
    messages = build_interview_messages(
        session, index=2, profile_text="张三，3 年经验", job_text="岗位：后端开发"
    )
    system = messages[0]["content"]
    assert "当前是第 2 轮" in system
    assert "持续追问" in system
    assert "Go 并发" in system
    # 占位符必须全部被替换掉：留在提示词里等于把模板语法交给模型。
    assert "{{" not in system
    user = messages[1]["content"]
    assert "不可信" in user
    # 进度同时给模型一份：它需要知道还剩几轮来决定是否收尾。
    assert "第 2 / 3 轮" in user
    assert "张三，3 年经验" in user


def test_report_prompt_carries_rules():
    messages = build_report_messages(_session())
    assert "评分报告" in messages[0]["content"]
    assert "不得" in messages[0]["content"] or "不要" in messages[0]["content"]


def test_rounds_and_choice_validation():
    assert InterviewCreate().rounds == 6
    assert answered_rounds(_session()) == 0
    with pytest.raises(Exception):
        InterviewCreate(interview_type="不存在的类型")
    with pytest.raises(Exception):
        InterviewCreate(rounds=99)


def test_api_flow_finishes_after_planned_rounds(client, monkeypatch):
    """三轮的计划：第三次回答后必须自动收尾并给出报告。"""
    _configure(
        monkeypatch,
        [
            {"question": "第一个问题：介绍一个你做过的项目", "feedback": "", "done": False},
            {"question": "第二个问题：这个项目里最难的地方", "feedback": "讲得清楚", "done": False},
            {"question": "结束语：面试到此结束", "feedback": "可以更具体些", "done": True},
        ],
    )

    created = client.post("/api/interview", json={"interview_type": "技术面", "rounds": 3})
    assert created.status_code == 201, created.text
    session = created.json()
    assert session["messages"][0]["content"].startswith("第一个问题")
    assert session["status"] == "active"

    first = client.post(f"/api/interview/{session['id']}/answers", json={"content": "我做过 A"})
    assert first.status_code == 200
    assert first.json()["finished"] is False
    assert first.json()["feedback"] == "讲得清楚"
    # 进度是代码算出来的，不是模型说的。
    assert first.json()["session"]["answered_rounds"] == 1

    second = client.post(f"/api/interview/{session['id']}/answers", json={"content": "最难的是 B"})
    assert second.status_code == 200
    body = second.json()
    assert body["finished"] is True
    assert body["session"]["status"] == "finished"
    assert body["session"]["report"]["score"] == 80

    # 结束之后再提交回答应被拒绝，而不是静默追加到已完成的面试里。
    again = client.post(f"/api/interview/{session['id']}/answers", json={"content": "再补一句"})
    assert again.status_code == 409


def test_api_finish_early_requires_an_answer(client, monkeypatch):
    _configure(monkeypatch, [{"question": "第一题", "feedback": "", "done": False}])
    session_id = client.post("/api/interview", json={"rounds": 3}).json()["id"]

    # 一题都没答就出报告没有意义。
    assert client.post(f"/api/interview/{session_id}/finish").status_code == 400
    client.post(f"/api/interview/{session_id}/answers", json={"content": "我的回答"})
    finished = client.post(f"/api/interview/{session_id}/finish")
    assert finished.status_code == 200
    assert finished.json()["status"] == "finished"
    # 已经结束的会话再点结束是幂等的。
    assert client.post(f"/api/interview/{session_id}/finish").status_code == 200


def test_report_failure_keeps_the_session_usable(client, monkeypatch):
    """报告生成失败时留下说明，而不是让整场面试不可用或接口 500。"""

    async def broken(_provider, _session_):
        raise LLMError("模型超时")

    _configure(monkeypatch, [{"question": "第一题", "feedback": "", "done": False}])
    monkeypatch.setattr("app.api.interview.generate_report", broken)

    session_id = client.post("/api/interview", json={"rounds": 3}).json()["id"]
    client.post(f"/api/interview/{session_id}/answers", json={"content": "我的回答"})
    finished = client.post(f"/api/interview/{session_id}/finish")

    assert finished.status_code == 200
    report = finished.json()["report"]
    assert report["error"] is True
    assert "报告生成失败" in report["summary"]
    # 记录仍在，可以存进资料箱复盘。
    assert finished.json()["messages"]


def test_api_requires_model_configuration(client):
    # 没有配置模型时不该创建一个空的面试会话。
    assert client.post("/api/interview", json={}).status_code == 400
    assert client.get("/api/interview").json() == []


def test_report_to_material_creates_a_review(client, monkeypatch):
    _configure(monkeypatch, [{"question": "第一题：自我介绍", "feedback": "", "done": False}])
    session_id = client.post("/api/interview", json={"rounds": 3}).json()["id"]
    client.post(f"/api/interview/{session_id}/answers", json={"content": "我是张三"})
    client.post(f"/api/interview/{session_id}/finish")

    created = client.post(f"/api/interview/{session_id}/to-material")
    assert created.status_code == 201
    body = created.json()
    assert body["category"] == "面试复盘"
    assert "面试官" in body["content"] and "我是张三" in body["content"]


def test_delete_and_missing_session(client):
    assert client.get("/api/interview/999").status_code == 404
    assert client.delete("/api/interview/999").status_code == 404
    assert client.post("/api/interview/999/answers", json={"content": "x"}).status_code == 404


def test_the_last_answer_does_not_produce_a_dangling_question(client, monkeypatch):
    """答满轮数后不该再问一道没人会回答的题。

    此前是"先生成下一题、再判断是否满轮"，于是 6 轮的面试会存下 7 道面试官消息，
    多出来的那道还会进报告和存进资料箱的转录里。
    """
    _configure(
        monkeypatch,
        [{"question": f"第 {index} 题", "feedback": "点评", "done": False} for index in range(1, 10)],
    )
    session_id = client.post("/api/interview", json={"rounds": 3}).json()["id"]

    for round_index in range(1, 4):
        response = client.post(f"/api/interview/{session_id}/answers", json={"content": "回答"})
        assert response.status_code == 200

    detail = client.get(f"/api/interview/{session_id}").json()
    questions = [item for item in detail["messages"] if item["role"] == "interviewer"]
    answers = [item for item in detail["messages"] if item["role"] == "user"]
    assert len(answers) == 3
    assert len(questions) == 3, "最后一道题不该存在"
    assert detail["status"] == "finished"


def test_the_maximum_round_count_can_actually_be_finished(client, monkeypatch):
    """轮数取到上限时最后一答不能报错。

    之前 generate_question 的 index 会算成 13 > MAX_INTERVIEW_ROUNDS，最后一答直接 502，
    面试卡在 active 状态：用户只能手动点"结束并出报告"才能脱身。
    """
    from app.schemas.interview import MAX_INTERVIEW_ROUNDS

    # 这里**不能**像别的用例那样替换 _ask_next_question：越界检查就在它调用的
    # generate_question 里面，替换掉就等于把要测的那行代码删了（这个用例第一版
    # 正是这样写的，去掉修复后依然通过）。改成只替换 provider，让真实流程跑起来。
    _configure_provider(monkeypatch, _turn_jsons(30))
    session_id = client.post(
        "/api/interview", json={"rounds": MAX_INTERVIEW_ROUNDS}
    ).json()["id"]

    for _ in range(MAX_INTERVIEW_ROUNDS):
        response = client.post(f"/api/interview/{session_id}/answers", json={"content": "回答"})
        assert response.status_code == 200, response.text

    detail = client.get(f"/api/interview/{session_id}").json()
    assert detail["status"] == "finished"
    assert detail["report"]["score"] == 80


def test_prompt_conditionals_are_actually_rendered():
    """提示词里的 `{% if %}` 必须被渲染掉，不能原样发给模型。

    渲染器原来只替换 `{{ key }}`、不处理条件块，于是人设段落即使为空也会出现，
    首轮与后续轮的两套输出骨架连同 `{% if %}` / `{% else %}` 一起塞给模型——
    "首轮 feedback 必须为空"这条约定实际上从未传达。
    """
    with_persona = _session(persona="你要刻意打断候选人")
    without = _session(persona="")

    rendered_with = build_interview_messages(with_persona, index=1)[0]["content"]
    rendered_without = build_interview_messages(without, index=1)[0]["content"]

    for text in (rendered_with, rendered_without):
        assert "{%" not in text
        assert "{{" not in text
    assert "你要刻意打断候选人" in rendered_with
    # 没填人设时整段不出现，而不是留一个空标题。
    assert "你要刻意打断候选人" not in rendered_without

    # 首轮只给一套骨架（feedback 必须为空），后续轮才给点评那一套。
    later = build_interview_messages(_session(), index=2)[0]["content"]
    assert later.count('"feedback"') >= 1
    assert rendered_with.count('"question"') == 1
