"""助手技能接口：列出、查看详情、导入、创建、更新、启用/停用与删除。

导入走**裸二进制请求体**而不是 multipart（项目未装 `python-multipart`，且全仓上传
一律是「前端自行提交 + `Upload.LIST_IGNORE`」）。`Content-Type` 同时接受 zip 与 markdown，
两者不在 CORS 简单请求允许的类型里，跨站页面必须先发预检，预检只放行本机前端。

工作台的手工创建/编辑走普通 JSON：结构化的提示词与知识文件用 JSON 表达更自然，
也不必再绕一层文件上传。
"""
import logging
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.assistant import AssistantSkill
from ..schemas.skill import (
    MAX_SKILL_DETAIL_FILE_CHARS,
    AssistantSkillCreate,
    AssistantSkillDetail,
    AssistantSkillOut,
    AssistantSkillUpdate,
)
from ..services.assistant_skills import (
    create_skill as create_skill_record,
    delete_skill,
    list_skills,
    set_skill_enabled,
    update_skill as update_skill_record,
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

# 请求体是裸字节，原始文件名带不进来；前端用这个头补上（头只能放 latin-1，所以是 URL 编码的）。
FILENAME_HEADER = "x-skill-filename"
MAX_SOURCE_NAME_CHARS = 120


def _source_name(request: Request) -> str | None:
    """取出使用者那份文件的名字，只当显示名与兜底名称用。

    这个值来自客户端，所以在这里就剥掉路径部分和不可打印字符——它既会进数据库，也可能
    被当成"没有 frontmatter 时用什么名字"，不能让它带出目录。
    """
    raw = request.headers.get(FILENAME_HEADER, "").strip()
    if not raw:
        return None
    name = unquote(raw).replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(char for char in name if char.isprintable()).strip().strip(".")
    return name[:MAX_SOURCE_NAME_CHARS] or None


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


def _to_detail(skill: AssistantSkill) -> AssistantSkillDetail:
    """详情视图：带上知识文件正文，但按总量上限截断并标记 ``files_truncated``。"""
    budget = MAX_SKILL_DETAIL_FILE_CHARS
    truncated = False
    file_details = []
    for item in skill.files:
        content = item.content or ""
        if len(content) > budget:
            content = content[: max(budget, 0)]
            truncated = True
        budget -= len(content)
        file_details.append(
            {"path": item.path, "size_bytes": item.size_bytes, "content": content}
        )
    return AssistantSkillDetail(
        **_to_out(skill).model_dump(),
        prompt=skill.prompt,
        file_details=file_details,
        files_truncated=truncated,
    )


def _skill_or_404(db: Session, skill_id: int) -> AssistantSkill:
    skill = db.get(AssistantSkill, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在或已被删除")
    return skill


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

    source_name = _source_name(request)
    staging = restore_directory(db.get_bind())
    staging.mkdir(parents=True, exist_ok=True)
    # 临时文件仍然用随机名，避免并发导入同名文件互相截断；真实文件名走 source_name。
    candidate = staging / f"{uuid4().hex}{suffix}"
    try:
        with candidate.open("wb") as target:
            async for chunk in request.stream():
                target.write(chunk)
        parser = parse_zip_skill if suffix == ".zip" else parse_markdown_skill
        skill = upsert_skill(db, parser(candidate, source_name))
    except SkillImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        candidate.unlink(missing_ok=True)

    logger.info("已导入技能 name=%s 知识文件=%s", skill.name, len(skill.files))
    return _to_out(skill)


@router.post("", response_model=AssistantSkillDetail, status_code=201)
def create_skill(payload: AssistantSkillCreate, db: Session = Depends(get_db)):
    """在工作台手动创建技能。"""
    try:
        payload.require_prompt()
        skill = create_skill_record(
            db,
            name=payload.name,
            description=payload.description,
            prompt=payload.prompt,
            enabled=payload.enabled,
            files=[(item.path, item.content) for item in payload.files],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_detail(skill)


@router.get("/{skill_id}", response_model=AssistantSkillDetail)
def read_skill(skill_id: int, db: Session = Depends(get_db)):
    """查看技能详情：提示词正文与知识文件清单。"""
    return _to_detail(_skill_or_404(db, skill_id))


@router.put("/{skill_id}", response_model=AssistantSkillDetail)
def update_skill(skill_id: int, payload: AssistantSkillUpdate, db: Session = Depends(get_db)):
    """更新技能（只提交要改的字段）；``files`` 提交时整体替换知识文件。"""
    if all(
        value is None
        for value in (payload.name, payload.description, payload.prompt, payload.enabled, payload.files)
    ):
        raise HTTPException(status_code=422, detail="至少提供一个要修改的技能字段")
    try:
        skill = update_skill_record(
            db,
            skill_id,
            name=payload.name,
            description=payload.description,
            prompt=payload.prompt,
            enabled=payload.enabled,
            files=(
                [(item.path, item.content) for item in payload.files]
                if payload.files is not None
                else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在或已被删除")
    return _to_detail(skill)


@router.patch("/{skill_id}", response_model=AssistantSkillOut)
def toggle_skill(skill_id: int, payload: AssistantSkillUpdate, db: Session = Depends(get_db)):
    """快速开关技能（助手页与设置页的 Switch 走这里）。"""
    if payload.enabled is None:
        raise HTTPException(status_code=422, detail="请提供要切换的启用状态")
    skill = set_skill_enabled(db, skill_id, payload.enabled)
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在或已被删除")
    return _to_out(skill)


@router.delete("/{skill_id}", status_code=204)
def remove_skill(skill_id: int, db: Session = Depends(get_db)):
    if not delete_skill(db, skill_id):
        raise HTTPException(status_code=404, detail="技能不存在或已被删除")
