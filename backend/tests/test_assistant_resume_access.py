"""P8 · 求职助手对简历（及其它内容）的读取边界与完整性。

两件事一起验：

1. **读得全**：``get_resume`` 以前只返回 ``id / title / content``，把模板、版式覆盖、页数上限、
   字号档位全丢了——可助手手里就有 ``update_resume_layout``，等于让它闭着眼睛改版式。
   正文过长时也**不是**从中间截断字符串，而是整段省略并明说省略了哪几段。
2. **读不到回收站里的东西**：助手工具里那几处**单条读取**原本用的是 ``db.get``，它绕过查询
   过滤——列表里看不到的岗位/简历/资料，只要知道 id 就能被助手读出来、甚至继续改。
   这与 P5 承诺的"回收站里的内容不会出现在其它任何地方"直接冲突。
"""
import json

import pytest

from app.models.job import Job
from app.models.material import Material
from app.models.resume import ResumeRecord
from app.services import trash
from app.services.assistant_tools import execute_tool


def _resume(db_session, **overrides) -> ResumeRecord:
    data = {
        "title": "后端版简历",
        "job_title": "后端开发工程师",
        "company": "某科技",
        "source": "ai",
        "template": "modern",
        "format_name": "紧凑版式",
        "format_config": {"accent": "#0f766e"},
        "page_limit": 2,
        "font_scale": "small",
        "custom_instruction": "多写并发经验",
        "model": "gpt-4o-mini",
        "tone": "standard",
        "warnings": ["第 2 段经历缺少量化结果"],
        "parse_error": "",
        "content": {"name": "张三", "summary": "后端开发", "photo": "data:image/png;base64,AAAA"},
    }
    data.update(overrides)
    record = ResumeRecord(**data)
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


def _payload(db_session, name: str, arguments: dict) -> dict:
    return json.loads(execute_tool(db_session, name, arguments).text)


# ===== 读得全 =====


def test_get_resume_returns_the_layout_and_source_fields(db_session):
    """助手能调 ``update_resume_layout``，就必须先看得见当前版式。

    缺了这些字段，模型只能凭猜测填参数——它多半会把用户的模板或页数改掉，
    而用户看到的是一句"已按你的要求调整版式"。
    """
    record = _resume(db_session)

    payload = _payload(db_session, "get_resume", {"resume_id": record.id})

    assert payload["layout"] == {
        "template": "modern",
        "format_name": "紧凑版式",
        "format_config": {"accent": "#0f766e"},
        "page_limit": 2,
        "font_scale": "small",
    }
    assert payload["target_job"] == "后端开发工程师"
    assert payload["company"] == "某科技"
    assert payload["source"] == "ai"
    assert payload["custom_instruction"] == "多写并发经验"
    # 生成留下的警告要给到模型，它才能如实说"有几处需要你确认"。
    assert payload["warnings"] == ["第 2 段经历缺少量化结果"]
    # 正文里的照片不进上下文（既有隐私取舍）。
    assert "photo" not in payload["content"]
    assert payload["content"]["name"] == "张三"


def test_a_normal_resume_is_not_reported_as_omitted(db_session):
    """没超长时不能出现"已省略"的说明——那是误报，会让模型以为内容不全。"""
    record = _resume(db_session)

    payload = _payload(db_session, "get_resume", {"resume_id": record.id})

    assert "content_omitted_sections" not in payload
    assert "note" not in payload
    assert payload["content"]["summary"] == "后端开发"


def test_oversized_resume_content_is_omitted_by_section_not_cut_in_the_middle(db_session):
    """正文过长时**整段省略**并说明省略了哪些，而不是从中间截断字符串。

    从中间切 JSON 会让模型收到一段缺了结尾的内容，它会以为简历就这么多东西、答话时漏掉
    后面的经历——而用户完全看不出来。整段省略 + 明说，模型至少知道自己没看全。
    """
    filler = [{"detail": "字" * 300} for _ in range(6)]
    record = _resume(
        db_session,
        content={
            "name": "张三",
            "experience": filler,
            "projects": filler,
            "skills": filler,
        },
    )

    payload = _payload(db_session, "get_resume", {"resume_id": record.id})

    assert payload["content_omitted_sections"], "超长时必须说明省略了哪些段落"
    assert "note" in payload
    for section in payload["content_omitted_sections"]:
        assert section not in payload["content"]
    # 最能回答"这个人做过什么"的经历要留到最后才丢。
    assert "experience" in payload["content"]


# ===== 回收站边界：助手也不能翻出已删除的内容 =====


def test_get_resume_cannot_read_a_trashed_record(db_session):
    record = _resume(db_session)
    trash.soft_delete(db_session, "resume", record)
    db_session.commit()

    with pytest.raises(ValueError):
        execute_tool(db_session, "get_resume", {"resume_id": record.id})


def test_update_resume_layout_cannot_touch_a_trashed_record(db_session):
    """已删除的简历不能还被助手改版式——那是在改用户看不见的东西。"""
    record = _resume(db_session)
    trash.soft_delete(db_session, "resume", record)
    db_session.commit()

    with pytest.raises(ValueError):
        execute_tool(db_session, "update_resume_layout", {"resume_id": record.id, "page_limit": 3})


@pytest.mark.parametrize(
    ("tool", "trash_type", "model_factory", "argument"),
    [
        ("get_job", "job", lambda db: Job(title="已删岗位"), "job_id"),
        ("get_material", "material", lambda db: Material(title="已删资料"), "material_id"),
    ],
)
def test_single_item_tools_cannot_read_trashed_content(
    db_session, tool, trash_type, model_factory, argument
):
    """岗位与资料同理：``db.get`` 绕过查询过滤，等于给回收站开了个后门。"""
    item = model_factory(db_session)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    trash.soft_delete(db_session, trash_type, item)
    db_session.commit()

    with pytest.raises(ValueError):
        execute_tool(db_session, tool, {argument: item.id})


def test_update_job_cannot_modify_a_trashed_job(db_session):
    job = Job(title="已删岗位")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    trash.soft_delete(db_session, "job", job)
    db_session.commit()

    with pytest.raises(ValueError):
        execute_tool(db_session, "update_job", {"job_id": job.id, "note": "改一下"})
