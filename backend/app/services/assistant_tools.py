"""求职助手可调用的工具：读项目数据，以及新增/修改。

**边界（用户已确认）**：助手能新增和修改，但**不提供任何删除类工具**——模型无论
如何都造不成不可逆损失。设置里的模型配置与数据集管理也不在工具里：那两个端点有
回环强制校验，工具化等于绕过它。

写工具的参数一律交给现成的 Pydantic schema 校验（`JobCreate` / `JobUpdate` /
`ProfileUpdate`），与 HTTP 接口共用同一套约束，不另写一份。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session, selectinload

from ..models.job import JOB_STATUSES, Job
from ..models.profile import UserProfile
from ..models.resume import ResumeRecord
from ..schemas.job import JobCreate, JobOut, JobUpdate
from ..schemas.profile import ProfileOut, ProfileUpdate
from .job_service import create_job_record, update_job_record
from .profile_relevance import build_job_prompt_text
from .profile_service import get_profile_detail, update_profile

logger = logging.getLogger(__name__)

MAX_JOB_RESULT_CHARS = 6_000
MAX_PROFILE_RESULT_CHARS = 8_000
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 50

# 助手能改的基础资料字段。经历、教育、项目等结构化条目刻意不在其中：合并语义
# 复杂（列表跨条目改动容易误删），v1 交给用户在界面上编辑。
PROFILE_EDITABLE_FIELDS = (
    "name",
    "gender",
    "birth_year",
    "phone",
    "email",
    "city",
    "target_city",
    "job_intent",
    "personal_website",
    "github",
    "summary",
)


@dataclass
class ToolResult:
    """工具执行结果。

    ``text`` 回给模型；``summary``/``link`` 只用于界面上那张"助手做了什么"的卡片。
    """

    text: str
    summary: str = ""
    link: str = ""
    changed: bool = False


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[Session, dict], ToolResult] = field(repr=False)


def _trim(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[:limit].rstrip()}…"


def _job_brief(job: Job) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "status": job.status,
        "favorite": job.favorite,
        "posted_at": job.posted_at,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _load_profile(db: Session) -> UserProfile | None:
    # 必须 selectinload：异步/延迟加载会在会话外炸掉。
    return (
        db.query(UserProfile)
        .options(
            selectinload(UserProfile.educations),
            selectinload(UserProfile.experiences),
            selectinload(UserProfile.campus_experiences),
            selectinload(UserProfile.projects),
            selectinload(UserProfile.skills),
            selectinload(UserProfile.awards),
        )
        .first()
    )


def _profile_snapshot(db: Session) -> ProfileOut | None:
    profile = get_profile_detail(db)
    return ProfileOut.model_validate(profile) if profile is not None else None


# ===== 读工具 =====


def _tool_get_overview(db: Session, _arguments: dict) -> ToolResult:
    """给"分析我已经填过的信息"用的概览。"""
    counts = {
        "岗位": db.query(Job).count(),
        "简历": db.query(ResumeRecord).count(),
    }
    recent_jobs = [
        _job_brief(job)
        for job in db.query(Job).order_by(Job.updated_at.desc()).limit(5).all()
    ]
    profile = _profile_snapshot(db)
    filled = []
    if profile is not None:
        data = profile.model_dump()
        for name in PROFILE_EDITABLE_FIELDS:
            if data.get(name):
                filled.append(name)
        for section in ("educations", "experiences", "campus_experiences", "projects", "skills", "awards"):
            if data.get(section):
                filled.append(f"{section}({len(data[section])})")
    payload = {
        "数量": counts,
        "最近更新的岗位": recent_jobs,
        "个人资料已填写": filled,
    }
    return ToolResult(text=json.dumps(payload, ensure_ascii=False), summary="查看了整体概览")


def _tool_list_jobs(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    query = db.query(Job)
    keyword = (arguments.get("keyword") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            Job.title.like(like) | Job.company.like(like) | Job.description.like(like)
        )
    status = arguments.get("status")
    if status in JOB_STATUSES:
        query = query.filter(Job.status == status)
    # 先取总数再分页：count() 作用在带 limit 的查询上会退化成"返回条数"。
    total = query.count()
    jobs = query.order_by(Job.updated_at.desc()).limit(limit).all()
    payload = {"总数": total, "返回": len(jobs), "岗位": [_job_brief(job) for job in jobs]}
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了 {len(jobs)} 个岗位",
        link="/jobs",
    )


def _tool_get_job(db: Session, arguments: dict) -> ToolResult:
    job = db.get(Job, int(arguments["job_id"]))
    if job is None:
        raise ValueError(f"岗位 {arguments['job_id']} 不存在")
    # 元信息 + JD 正文都要给：只给 JD 的话模型看不到公司、地点和状态。
    payload = {
        **_job_brief(job),
        "source_url": job.source_url,
        "note": job.note,
        "jd": build_job_prompt_text(JobOut.model_validate(job), MAX_JOB_RESULT_CHARS),
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了岗位「{job.title}」",
        link="/jobs",
    )


def _tool_list_resumes(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    records = db.query(ResumeRecord).order_by(ResumeRecord.id.desc()).limit(limit).all()
    payload = [
        {
            "id": record.id,
            "title": record.title,
            "target_job": record.job_title,
            "company": record.company,
            "source": record.source,
            "favorite": record.favorite,
        }
        for record in records
    ]
    return ToolResult(
        text=json.dumps({"简历": payload}, ensure_ascii=False),
        summary=f"查看了 {len(payload)} 份简历",
        link="/resumes",
    )


def _tool_get_resume(db: Session, arguments: dict) -> ToolResult:
    record = db.get(ResumeRecord, int(arguments["resume_id"]))
    if record is None:
        raise ValueError(f"简历 {arguments['resume_id']} 不存在")
    content = dict(record.content or {})
    content.pop("photo", None)
    payload = {"id": record.id, "title": record.title, "content": content}
    return ToolResult(
        text=_trim(json.dumps(payload, ensure_ascii=False), MAX_JOB_RESULT_CHARS),
        summary=f"查看了简历「{record.title}」",
        link="/resumes",
    )


def _tool_get_profile(db: Session, _arguments: dict) -> ToolResult:
    """返回**脱敏**视图：姓名、电话、邮箱、照片不进模型上下文。

    这是项目原有的隐私取舍（见 docs/architecture.md），工具沿用同一套，
    顺带保证助手不会把用户的手机号复述到对话里。
    """
    from ..api.assistant_context import profile_context

    return ToolResult(text=profile_context(db), summary="查看了个人资料", link="/profile")


# ===== 写工具 =====


def _tool_create_job(db: Session, arguments: dict) -> ToolResult:
    payload = JobCreate.model_validate(arguments)  # 与接口同一套校验
    job = create_job_record(db, payload)
    logger.info("助手新增岗位 id=%s title=%s", job.id, job.title)
    return ToolResult(
        text=json.dumps({"id": job.id, "title": job.title}, ensure_ascii=False),
        summary=f"新增岗位「{job.title}」",
        link="/jobs",
        changed=True,
    )


def _tool_update_job(db: Session, arguments: dict) -> ToolResult:
    job_id = int(arguments["job_id"])
    job = db.get(Job, job_id)
    if job is None:
        raise ValueError(f"岗位 {job_id} 不存在")
    fields = {key: value for key, value in arguments.items() if key != "job_id"}
    if not fields:
        raise ValueError("没有给出要修改的字段")
    payload = JobUpdate.model_validate(fields)
    job = update_job_record(db, job, payload)
    logger.info("助手修改岗位 id=%s 字段=%s", job.id, sorted(fields))
    return ToolResult(
        text=json.dumps({"id": job.id, "title": job.title}, ensure_ascii=False),
        summary=f"修改了岗位「{job.title}」",
        link="/jobs",
        changed=True,
    )


def _tool_update_profile(db: Session, arguments: dict) -> ToolResult:
    """**必须 read-modify-write。**

    ``PUT /api/profile`` 是整份替换语义：只提交模型给出的那几个字段，其余字段会
    落回默认值——姓名、电话、照片一并被清空。所以这里先取当前完整资料，再叠加改动。
    用来叠加的是 ``ProfileOut``（完整数据），**不是**发给模型的那份脱敏数据。
    """
    fields = {key: value for key, value in arguments.items() if key in PROFILE_EDITABLE_FIELDS}
    if not fields:
        raise ValueError("没有给出可修改的资料字段")

    profile = _load_profile(db)
    if profile is None:
        base: dict[str, Any] = {}
    else:
        base = ProfileOut.model_validate(profile).model_dump(exclude={"id", "updated_at"})
    base.update(fields)
    update_profile(db, ProfileUpdate.model_validate(base))
    logger.info("助手修改个人资料 字段=%s", sorted(fields))
    names = "、".join(sorted(fields))
    return ToolResult(
        text=json.dumps({"updated": sorted(fields)}, ensure_ascii=False),
        summary=f"更新了个人资料的 {names}",
        link="/profile",
        changed=True,
    )


_TOOLS: tuple[Tool, ...] = (
    Tool(
        name="get_overview",
        description="查看当前项目里已有哪些数据：岗位/简历数量、最近更新的岗位、个人资料已填写了哪些字段、教育经历/项目/技能等的条数。想了解用户已经填过什么时先调用它。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_tool_get_overview,
    ),
    Tool(
        name="list_jobs",
        description="列出岗位。可按关键词（标题/公司/描述）或状态筛选。",
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "可选，标题/公司/描述里的关键词"},
                "status": {"type": "string", "enum": list(JOB_STATUSES), "description": "可选，岗位状态"},
                "limit": {"type": "integer", "description": "可选，最多返回多少条，默认 20"},
            },
            "required": [],
        },
        handler=_tool_list_jobs,
    ),
    Tool(
        name="get_job",
        description="按 id 读取某个岗位的完整内容（含岗位职责与任职要求）。",
        parameters={
            "type": "object",
            "properties": {"job_id": {"type": "integer", "description": "岗位 id"}},
            "required": ["job_id"],
        },
        handler=_tool_get_job,
    ),
    Tool(
        name="list_resumes",
        description="列出已生成的简历（标题、目标岗位、来源）。",
        parameters={
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "可选，默认 20"}},
            "required": [],
        },
        handler=_tool_list_resumes,
    ),
    Tool(
        name="get_resume",
        description="按 id 读取某份简历的完整内容。",
        parameters={
            "type": "object",
            "properties": {"resume_id": {"type": "integer", "description": "简历 id"}},
            "required": ["resume_id"],
        },
        handler=_tool_get_resume,
    ),
    Tool(
        name="get_profile",
        description="读取个人资料（已脱敏：不含姓名、电话、邮箱和照片）。想确认某个字段是否已填写时用它。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_tool_get_profile,
    ),
    Tool(
        name="create_job",
        description="新增一个岗位。只在用户明确要求录入招聘信息时调用；至少要有 title。",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "岗位名称，必填"},
                "company": {"type": "string", "description": "公司名称"},
                "location": {"type": "string", "description": "工作地点"},
                "salary": {"type": "string", "description": "薪资"},
                "job_type": {"type": "string", "enum": ["校招", "实习", "社招", "其他"]},
                "description": {"type": "string", "description": "岗位职责"},
                "requirements": {"type": "string", "description": "任职要求"},
                "additional_info": {"type": "string", "description": "福利、团队介绍、投递流程等"},
                "source_url": {"type": "string", "description": "投递链接，必须是 http/https"},
                "posted_at": {"type": "string", "description": "招聘发布时间"},
                "status": {"type": "string", "enum": list(JOB_STATUSES)},
                "note": {"type": "string", "description": "备注"},
            },
            "required": ["title"],
        },
        handler=_tool_create_job,
    ),
    Tool(
        name="update_job",
        description="修改已有岗位的字段（只传要改的那些）。",
        parameters={
            "type": "object",
            "properties": {
                "job_id": {"type": "integer", "description": "要修改的岗位 id"},
                "title": {"type": "string"},
                "company": {"type": "string"},
                "location": {"type": "string"},
                "salary": {"type": "string"},
                "job_type": {"type": "string", "enum": ["校招", "实习", "社招", "其他"]},
                "description": {"type": "string"},
                "requirements": {"type": "string"},
                "additional_info": {"type": "string"},
                "source_url": {"type": "string"},
                "posted_at": {"type": "string"},
                "status": {"type": "string", "enum": list(JOB_STATUSES)},
                "note": {"type": "string"},
            },
            "required": ["job_id"],
        },
        handler=_tool_update_job,
    ),
    Tool(
        name="update_profile",
        description=(
            "更新个人资料里的基础字段（只传要改的那些，其余字段会被保留）。"
            "教育经历、工作经历、项目、技能、奖项等结构化条目暂不支持，"
            "请让用户在「我的资料」页面编辑。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "姓名"},
                "gender": {"type": "string"},
                "birth_year": {"type": "string"},
                "phone": {"type": "string"},
                "email": {"type": "string"},
                "city": {"type": "string", "description": "所在城市"},
                "target_city": {"type": "string", "description": "期望工作城市"},
                "job_intent": {"type": "string", "description": "求职意向"},
                "personal_website": {"type": "string"},
                "github": {"type": "string"},
                "summary": {"type": "string", "description": "个人总结"},
            },
            "required": [],
        },
        handler=_tool_update_profile,
    ),
)


def tool_definitions(enabled: bool = True) -> list[dict]:
    """OpenAI 工具声明。``enabled=False`` 时返回空列表（用于关闭工具调用）。"""
    if not enabled:
        return []
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in _TOOLS
    ]


def tool_names() -> list[str]:
    return [tool.name for tool in _TOOLS]


def execute_tool(db: Session, name: str, arguments: dict) -> ToolResult:
    """执行工具。异常由调用方转成"给模型看的错误结果"，不要让整轮对话中断。"""
    for tool in _TOOLS:
        if tool.name == name:
            return tool.handler(db, arguments)
    raise ValueError(f"未知工具：{name}")


__all__ = [
    "ToolResult",
    "execute_tool",
    "tool_definitions",
    "tool_names",
]
