"""助手技能接口：列出、导入、启用/停用与删除。

导入走**裸二进制请求体**而不是 multipart（项目未装 `python-multipart`，且全仓上传
一律是「前端自行提交 + `Upload.LIST_IGNORE`」）。`Content-Type` 同时接受 zip 与 markdown，
两者不在 CORS 简单请求允许的类型里，跨站页面必须先发预检，预检只放行本机前端。
"""
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas.skill import AssistantSkillOut, AssistantSkillUpdate
from ..services.assistant_skills import (
    delete_skill,
    list_skills,
    set_skill_enabled,
    upsert_skill,
)
from ..services.data_backup import restore_directory
from ..services.skill_archive import SkillImportError, parse_markdown_skill, parse_zip_skill

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant/skills", tags=["assistant"])

# 中间件按这个常量放宽请求体上限；路由改名时必须同步，否则豁免会静默失效。
IMPORT_PATH = f"{router.prefix}/import"

_ZIP_CONTENT_TYPES = frozenset({"application/zip", "application/x-zip-compressed"})
_MARKDOWN_CONTENT_TYPES = frozenset({"text/markdown", "text/x-markdown", "text/plain"})


def _to_out(skill) -> AssistantSkillOut:
    return AssistantSkillOut(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        enabled=skill.enabled,
        source_name=skill.source_name,
        prompt_chars=len(skill.prompt),
        files=[item.path for item in skill.files],
        updated_at=skill.updated_at,
    )


@router.get("", response_model=list[AssistantSkillOut])
def read_skills(db: Session = Depends(get_db)):
    return [_to_out(skill) for skill in list_skills(db)]


@router.post("/import", response_model=AssistantSkillOut)
async def import_skill(request: Request, db: Session = Depends(get_db)):
    """导入一份技能：单个 .md（只有提示词）或一个 .zip（提示词 + 知识文件）。"""
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type in _ZIP_CONTENT_TYPES:
        suffix = ".zip"
    elif content_type in _MARKDOWN_CONTENT_TYPES:
        suffix = ".md"
    else:
        raise HTTPException(
            status_code=415, detail="请导入 .md 提示词文件或 .zip 技能包"
        )

    staging = restore_directory(db.get_bind())
    staging.mkdir(parents=True, exist_ok=True)
    candidate = staging / f"{uuid4().hex}{suffix}"
    try:
        with candidate.open("wb") as target:
            async for chunk in request.stream():
                target.write(chunk)
        parsed = parse_zip_skill(candidate) if suffix == ".zip" else parse_markdown_skill(candidate)
        skill = upsert_skill(db, parsed)
    except SkillImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        candidate.unlink(missing_ok=True)

    logger.info("已导入技能 name=%s 知识文件=%s", skill.name, len(skill.files))
    return _to_out(skill)


@router.patch("/{skill_id}", response_model=AssistantSkillOut)
def update_skill(skill_id: int, payload: AssistantSkillUpdate, db: Session = Depends(get_db)):
    skill = set_skill_enabled(db, skill_id, payload.enabled)
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在或已被删除")
    return _to_out(skill)


@router.delete("/{skill_id}", status_code=204)
def remove_skill(skill_id: int, db: Session = Depends(get_db)):
    if not delete_skill(db, skill_id):
        raise HTTPException(status_code=404, detail="技能不存在或已被删除")
