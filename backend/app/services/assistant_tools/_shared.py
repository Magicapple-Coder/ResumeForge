"""跨工具域共享的 helper 与常量。"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session, selectinload

from ...models.job import Job
from ...models.profile import UserProfile
from ...schemas.profile import ProfileOut
from ..profile.profile_service import get_profile_detail

logger = logging.getLogger(__name__)

MAX_JOB_RESULT_CHARS = 6_000
MAX_PROFILE_RESULT_CHARS = 8_000
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 50

MAX_ASSISTANT_SKILL_FILE_CHARS = 20_000
MAX_ASSISTANT_SKILL_TOTAL_CHARS = 60_000
MAX_ASSISTANT_SKILL_FILES = 10

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
def _trim(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[:limit].rstrip()}…"


# 读简历时留给正文的预算（从总预算里扣掉元信息与版式那部分）。
_RESUME_CONTENT_BUDGET = MAX_JOB_RESULT_CHARS - 1_500
# 正文过长时按这个顺序**整段**省略（越靠前越先丢）：荣誉 → 校园经历 → 技能 → 项目 → 教育。
# 经历放最后：它通常最能回答"这个人做过什么"。
_RESUME_CONTENT_DROP_ORDER = ("awards", "campus_experience", "skills", "projects", "education")


def _resume_content_for_model(content: dict, budget: int) -> tuple[dict, list[str]]:
    """把简历正文压进预算：超出时**整段**省略次要段落，并返回省略了哪些。

    刻意不是"从中间截断字符串"：那会让模型收到一段缺了结尾的 JSON，进而以为简历就这么多
    内容，回答时漏掉后面的经历——而用户完全看不出来。整段省略 + 明说省略了哪几段，
    模型至少知道自己没看全，可以再单独去查。
    """
    trimmed = dict(content)
    dropped: list[str] = []
    for key in _RESUME_CONTENT_DROP_ORDER:
        if len(json.dumps(trimmed, ensure_ascii=False)) <= budget:
            break
        if key in trimmed:
            trimmed.pop(key)
            dropped.append(key)
    return trimmed, dropped


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
