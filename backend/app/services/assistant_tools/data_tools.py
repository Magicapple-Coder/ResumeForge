"""资料箱 / 事实台账 / 面试深挖 / 备选岗位 / 助手技能 / 格式模板的工具。"""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy.orm import Session

from ...models.assistant import AssistantSkill
from ...models.job import Job
from ...models.material import CANDIDATE_JOB_PENDING, CandidateJob, Material
from ...models.resume_template import TEMPLATE_KIND_FORMAT, ResumeTemplate
from ...schemas.job import JobCreate
from ...schemas.material import CandidateJobCreate, MaterialCreate, MaterialUpdate
from .. import trash
from ..assistant.assistant_skills import (
    create_skill as create_skill_record,
    list_skills,
    update_skill as update_skill_record,
)
from ..candidate_jobs import candidate_brief, candidate_detail_text, mark_candidate_imported
from ..job.job_service import create_job_record
from ..materials import (
    create_material as create_material_record,
    list_materials,
    material_brief,
    material_detail_text,
    update_material as update_material_record,
)
from ..resume.resume_template_store import (
    TemplateError,
    create_user_template,
    find_by_name as find_template_by_name,
    get_user_template,
    update_user_template,
)
from ..resume.resume_templates import FORMAT_FIELDS, validated_format_config
from ._shared import (
    DEFAULT_LIST_LIMIT,
    MAX_ASSISTANT_SKILL_FILE_CHARS,
    MAX_ASSISTANT_SKILL_FILES,
    MAX_ASSISTANT_SKILL_TOTAL_CHARS,
    MAX_LIST_LIMIT,
    MAX_PROFILE_RESULT_CHARS,
    _trim,
)
from ._types import ToolResult

logger = logging.getLogger(__name__)
# ===== 资料箱 =====


def _material_or_error(db: Session, arguments: dict) -> Material:
    try:
        material_id = int(arguments.get("material_id"))
    except (TypeError, ValueError):
        raise ValueError("需要提供资料 id（可以先用 list_materials 查）") from None
    material = trash.get_live(db, Material, material_id)
    if material is None:
        raise ValueError(f"资料 {material_id} 不存在")
    return material


def _tool_list_materials(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    materials = list_materials(
        db,
        keyword=str(arguments.get("keyword") or ""),
        category=str(arguments.get("category") or ""),
    )
    shown = materials[:limit]
    payload = {
        "总数": len(materials),
        "返回": len(shown),
        "资料": [material_brief(item) for item in shown],
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了资料箱里的 {len(shown)} 条资料",
        link="/materials",
    )


def _tool_get_material(db: Session, arguments: dict) -> ToolResult:
    material = _material_or_error(db, arguments)
    return ToolResult(
        text=material_detail_text(material),
        summary=f"读取了资料「{material.title or material.category}」",
        link="/materials",
    )


def _tool_create_material(db: Session, arguments: dict) -> ToolResult:
    # 只放行工具**声明过**的字段：附件（files）不在 create_material 的参数里，
    # 留着它只会让人以为助手能给资料挂附件。
    payload = MaterialCreate.model_validate(
        {
            key: value
            for key, value in arguments.items()
            if key in {"title", "category", "content", "url", "note"}
        }
    )
    material = create_material_record(db, payload)
    return ToolResult(
        text=json.dumps({"id": material.id, "title": material.title}, ensure_ascii=False),
        summary=f"把「{material.title or material.category}」收进了资料箱",
        link="/materials",
        changed=True,
    )


def _tool_update_material(db: Session, arguments: dict) -> ToolResult:
    material = _material_or_error(db, arguments)
    fields = {
        key: value
        for key, value in arguments.items()
        if key in {"title", "category", "content", "url", "note"}
    }
    if not fields:
        raise ValueError("没有给出要修改的字段")
    payload = MaterialUpdate.model_validate(
        {
            "title": material.title,
            "category": material.category,
            "content": material.content,
            "url": material.url,
            "files": material.files or [],
            "note": material.note,
            **fields,
        }
    )
    updated = update_material_record(db, material, payload)
    return ToolResult(
        text=json.dumps({"id": updated.id, "updated": sorted(fields)}, ensure_ascii=False),
        summary=f"更新了资料「{updated.title or updated.category}」",
        link="/materials",
        changed=True,
    )


# ===== 事实台账 =====
#
# 台账是"用户自己核对过的事实"，所以助手在这里的权限是**可以补内容、不能替用户确认**：
# 所有写入路径都不接受 `verification_status`，新建的条目一律是「待确认」。让模型把某条
# 主张标成「已确认」，等于让它可以自己给自己发通行证——那正是台账要防的事。


def _claim_or_error(db: Session, arguments: dict):
    from ..claims import claim_or_none

    try:
        claim_id = int(arguments.get("claim_id"))
    except (TypeError, ValueError):
        raise ValueError("需要提供台账条目 id（可以先用 list_claims 查）") from None
    record = claim_or_none(db, claim_id)
    if record is None:
        raise ValueError(f"台账条目 {claim_id} 不存在")
    return record


def _tool_list_claims(db: Session, arguments: dict) -> ToolResult:
    from ..claims import claim_brief, list_claims

    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    records = list_claims(
        db,
        keyword=str(arguments.get("keyword") or ""),
        category=str(arguments.get("category") or ""),
        status=str(arguments.get("status") or ""),
    )
    shown = records[:limit]
    payload = {
        "总数": len(records),
        "返回": len(shown),
        "条目": [claim_brief(item) for item in shown],
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了事实台账里的 {len(shown)} 条记录",
        link="/claims",
    )


def _tool_get_claim(db: Session, arguments: dict) -> ToolResult:
    from ..claims import claim_detail_text

    record = _claim_or_error(db, arguments)
    return ToolResult(
        text=claim_detail_text(record),
        summary=f"读取了台账条目「{record.title or record.subject}」",
        link="/claims",
    )


def _tool_create_claim(db: Session, arguments: dict) -> ToolResult:
    from ...schemas.claim import ClaimCreate
    from ..claims import create_claim

    # 只放行工具声明过的字段；`verification_status` 不在其中，新建的一律是「待确认」。
    payload = ClaimCreate.model_validate(
        {
            key: value
            for key, value in arguments.items()
            if key
            in {
                "title",
                "category",
                "subject",
                "source_fact",
                "candidate_wording",
                "responsibility_level",
                "boundary",
                "risk_notes",
                "sources",
                "allowed_uses",
                "interview_details",
                "last_verified",
            }
        }
    )
    record = create_claim(db, payload)
    return ToolResult(
        text=json.dumps(
            {"id": record.id, "核实状态": record.verification_status}, ensure_ascii=False
        ),
        summary=f"把「{record.title or record.subject}」记进了事实台账（待你确认）",
        link="/claims",
        changed=True,
    )


def _tool_update_claim(db: Session, arguments: dict) -> ToolResult:
    from ...schemas.claim import ClaimUpdate
    from ..claims import update_claim

    record = _claim_or_error(db, arguments)
    mutable = {
        key: value
        for key, value in arguments.items()
        if key
        in {
            "title",
            "category",
            "subject",
            "source_fact",
            "candidate_wording",
            "responsibility_level",
            "boundary",
            "risk_notes",
            "sources",
            "allowed_uses",
            "interview_details",
            "last_verified",
        }
    }
    if not mutable:
        # 区分"什么都没给"和"只给了不能改的字段"：后者最常见的就是想改核实状态。
        # 只说"没有给出要修改的字段"会让模型以为参数格式错了，于是反复重试同一个调用。
        if "verification_status" in arguments:
            raise ValueError(
                "核实状态不能由助手修改——一条主张能不能进正式简历要由用户自己判断，"
                "请让他在「事实台账」页上确认"
            )
        raise ValueError("没有给出要修改的字段")
    payload = ClaimUpdate.model_validate(
        {
            "title": record.title,
            "category": record.category,
            "subject": record.subject,
            "source_fact": record.source_fact,
            "candidate_wording": record.candidate_wording,
            "sources": record.sources or [],
            "responsibility_level": record.responsibility_level,
            # 核实状态保持不变：助手不能替用户确认或作废一条主张。
            "verification_status": record.verification_status,
            "allowed_uses": record.allowed_uses or [],
            "interview_details": record.interview_details or {},
            "boundary": record.boundary,
            "risk_notes": record.risk_notes or [],
            "last_verified": record.last_verified,
            **mutable,
        }
    )
    updated = update_claim(db, record, payload)
    return ToolResult(
        text=json.dumps(
            {"id": updated.id, "updated": sorted(mutable), "核实状态": updated.verification_status},
            ensure_ascii=False,
        ),
        summary=f"更新了台账条目「{updated.title or updated.subject}」",
        link="/claims",
        changed=True,
    )


# ===== 面试深挖 =====


def _tool_list_drill_sessions(db: Session, arguments: dict) -> ToolResult:
    from ...models.drill import DrillSession

    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    status = str(arguments.get("status") or "").strip()
    query = db.query(DrillSession)
    if status:
        query = query.filter(DrillSession.status == status)
    records = query.order_by(DrillSession.created_at.desc()).limit(limit).all()
    payload = {
        "返回": len(records),
        "记录": [
            {
                "id": item.id,
                "标题": item.title,
                "岗位": item.job_title,
                "状态": "进行中" if item.status == "active" else "已结束",
                "已问": item.current_index,
                "最多": item.max_questions,
                "创建时间": item.created_at.isoformat() if item.created_at else None,
            }
            for item in records
        ],
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了 {len(records)} 场面试深挖",
        link="/claims/drill",
    )


def _tool_get_drill_report(db: Session, arguments: dict) -> ToolResult:
    from ...models.drill import DrillSession
    from ..drill import session_summary

    try:
        session_id = int(arguments.get("session_id"))
    except (TypeError, ValueError):
        raise ValueError("需要提供深挖记录 id（可以先用 list_drill_sessions 查）") from None
    record = db.get(DrillSession, session_id)
    if record is None:
        raise ValueError(f"深挖记录 {session_id} 不存在")

    review = record.review or {}
    payload = {
        "标题": record.title,
        "岗位": record.job_title,
        "状态": "进行中" if record.status == "active" else "已结束",
        "计数": session_summary(record),
        "复盘": {
            "覆盖": review.get("covered", ""),
            "讲得清的": review.get("verified_summary", ""),
            "还站不住的": review.get("gaps_summary", ""),
            "行动清单": review.get("actions", []),
            "复练队列": review.get("rehearsal", []),
        },
        "逐题判定": [
            {
                "主张": item.claim_title,
                "问题": item.question,
                "判定": item.status,
                "已经讲到的": item.evidence_found,
                "仍然缺的": item.missing,
                "发现的矛盾": item.contradictions,
            }
            for item in record.contracts
        ],
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False)[:MAX_PROFILE_RESULT_CHARS],
        summary=f"读取了深挖记录「{record.title}」",
        link="/claims/drill",
    )


# ===== 备选岗位 =====


def _candidate_or_error(db: Session, arguments: dict) -> CandidateJob:
    try:
        candidate_id = int(arguments.get("candidate_id"))
    except (TypeError, ValueError):
        raise ValueError("需要提供备选岗位 id（可以先用 list_candidate_jobs 查）") from None
    candidate = db.get(CandidateJob, candidate_id)
    if candidate is None:
        raise ValueError(f"备选岗位 {candidate_id} 不存在")
    return candidate


def _tool_list_candidate_jobs(db: Session, arguments: dict) -> ToolResult:
    limit = min(int(arguments.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    status = str(arguments.get("status") or "").strip()
    query = db.query(CandidateJob)
    if status in {"pending", "imported"}:
        query = query.filter(CandidateJob.status == status)
    keyword = str(arguments.get("keyword") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            CandidateJob.title.like(like)
            | CandidateJob.company.like(like)
            | CandidateJob.raw_text.like(like)
        )
    candidates = query.order_by(CandidateJob.created_at.desc()).limit(limit).all()
    payload = {
        "返回": len(candidates),
        "备选岗位": [candidate_brief(item) for item in candidates],
    }
    return ToolResult(
        text=json.dumps(payload, ensure_ascii=False),
        summary=f"查看了 {len(candidates)} 条备选岗位",
        link="/jobs",
    )


def _tool_get_candidate_job(db: Session, arguments: dict) -> ToolResult:
    candidate = _candidate_or_error(db, arguments)
    return ToolResult(
        text=candidate_detail_text(candidate),
        summary=f"读取了备选岗位「{candidate.title or candidate.company or candidate.id}」",
        link="/jobs",
    )


def _tool_create_candidate_job(db: Session, arguments: dict) -> ToolResult:
    payload = CandidateJobCreate.model_validate(
        {
            "title": str(arguments.get("title") or ""),
            "company": str(arguments.get("company") or ""),
            "raw_text": str(arguments.get("raw_text") or ""),
            "note": str(arguments.get("note") or ""),
            "source": "助手录入",
        }
    )
    candidate = CandidateJob(**payload.model_dump(), status=CANDIDATE_JOB_PENDING)
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    logger.info("助手新增备选岗位 id=%s", candidate.id)
    return ToolResult(
        text=json.dumps({"id": candidate.id, "title": candidate.title}, ensure_ascii=False),
        summary=f"把「{candidate.title or candidate.company or '招聘信息'}」放进了备选岗位",
        link="/jobs",
        changed=True,
    )


def _tool_update_candidate_job(db: Session, arguments: dict) -> ToolResult:
    candidate = _candidate_or_error(db, arguments)
    fields = {
        key: value
        for key, value in arguments.items()
        if key in {"title", "company", "raw_text", "note"}
    }
    if not fields:
        raise ValueError("没有给出要修改的字段")
    for key, value in fields.items():
        setattr(candidate, key, value)
    db.commit()
    db.refresh(candidate)
    return ToolResult(
        text=json.dumps({"id": candidate.id, "updated": sorted(fields)}, ensure_ascii=False),
        summary=f"更新了备选岗位「{candidate.title or candidate.id}」",
        link="/jobs",
        changed=True,
    )


def _tool_import_candidate_job(db: Session, arguments: dict) -> ToolResult:
    """把备选岗位正式导入岗位广场。

    已导入过的不再重复创建：直接告诉模型它在正式岗位里的 id，避免同一份招聘信息
    被记两次。
    """
    candidate = _candidate_or_error(db, arguments)
    if candidate.status == "imported" and candidate.imported_job_id:
        existing = trash.get_live(db, Job, candidate.imported_job_id)
        if existing is not None:
            return ToolResult(
                text=json.dumps(
                    {"job_id": existing.id, "title": existing.title, "already_imported": True},
                    ensure_ascii=False,
                ),
                summary=f"备选岗位已在岗位广场（id={existing.id}）",
                link="/jobs",
            )
    raw_text = (candidate.raw_text or "").strip()[:20_000]
    payload = JobCreate.model_validate(
        {
            "title": str(arguments.get("title") or candidate.title or "待补充岗位").strip()[:128],
            "company": str(arguments.get("company") or candidate.company or "").strip()[:128],
            "description": raw_text or str(arguments.get("description") or ""),
            "note": candidate.note or str(arguments.get("note") or ""),
            "recognition_source": "备选岗位导入",
        }
    )
    job = create_job_record(db, payload)
    mark_candidate_imported(db, candidate, job.id)
    return ToolResult(
        text=json.dumps({"job_id": job.id, "title": job.title}, ensure_ascii=False),
        summary=f"把备选岗位导入成正式岗位「{job.title}」",
        link="/jobs",
        changed=True,
    )


# ===== 助手技能 =====


def _tool_list_skills(db: Session, _arguments: dict) -> ToolResult:
    skills = list_skills(db)
    payload = [
        {
            "id": skill.id,
            "名称": skill.name,
            "适用场景": skill.description,
            "启用": skill.enabled,
            "提示词字数": len(skill.prompt),
            "知识文件": [item.path for item in skill.files],
        }
        for skill in skills
    ]
    return ToolResult(
        text=json.dumps({"技能": payload}, ensure_ascii=False),
        summary=f"查看了 {len(payload)} 个助手技能",
        link="/skills",
    )


def _tool_get_skill(db: Session, arguments: dict) -> ToolResult:
    try:
        skill_id = int(arguments.get("skill_id"))
    except (TypeError, ValueError):
        raise ValueError("需要提供技能 id（可以先用 list_skills 查）") from None
    skill = db.get(AssistantSkill, skill_id)
    if skill is None:
        raise ValueError(f"技能 {skill_id} 不存在")
    payload = {
        "id": skill.id,
        "名称": skill.name,
        "适用场景": skill.description,
        "启用": skill.enabled,
        "提示词": skill.prompt,
        "知识文件": [{"path": item.path, "size_bytes": item.size_bytes} for item in skill.files],
    }
    return ToolResult(
        text=_trim(json.dumps(payload, ensure_ascii=False), MAX_PROFILE_RESULT_CHARS),
        summary=f"查看了技能「{skill.name}」",
        link="/skills",
    )


def _skill_files_from_arguments(arguments: dict) -> list[tuple[str, str]] | None:
    """把工具入参里的 ``files`` 规范化成 service 期望的 ``(path, content)`` 列表。

    返回 ``None`` 表示"这次调用没提供知识文件"——让 ``create_skill``/``update_skill``
    保持原有行为（创建时不带文件、更新时**不动**已有文件），避免把"没提"误当成"清空"。
    """
    raw = arguments.get("files")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError('files 必须是一个数组，每项形如 {"path": "文件名.md", "content": "正文"}')
    files: list[tuple[str, str]] = []
    total = 0
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f'files 第 {index} 项格式不对，应为 {{"path": ..., "content": ...}}')
        # path 会被原样拼进系统提示里的一条 bullet（`- {item.path}`），所以换行等控制字符
        # 必须清掉——否则模型能把一个文件名变成"新的一行指令"，凭空造出提示注入面。
        # 它只是一个显示标签，把控制字符与连续空白折成单空格就够，不必过度清洗。
        raw_path = re.sub(r"[\x00-\x1f\x7f]+", " ", str(item.get("path") or ""))
        path = " ".join(raw_path.split())
        content = str(item.get("content") or "")
        if not path:
            raise ValueError(f"files 第 {index} 项缺少 path（知识文件名）")
        if len(path) > 255:
            raise ValueError(f"知识文件名「{path}」过长，请控制在 255 个字符内")
        if not content.strip():
            raise ValueError(f"知识文件「{path}」的正文是空的")
        if len(content) > MAX_ASSISTANT_SKILL_FILE_CHARS:
            raise ValueError(
                f"知识文件「{path}」有 {len(content)} 个字符，超过单文件上限 "
                f"{MAX_ASSISTANT_SKILL_FILE_CHARS}，请拆分或精简后再加"
            )
        total += len(content)
        if total > MAX_ASSISTANT_SKILL_TOTAL_CHARS:
            raise ValueError(
                f"知识文件总长度超过 {MAX_ASSISTANT_SKILL_TOTAL_CHARS} 个字符，请减少文件数量或精简内容"
            )
        files.append((path, content))
    if len(files) > MAX_ASSISTANT_SKILL_FILES:
        raise ValueError(f"一次最多 {MAX_ASSISTANT_SKILL_FILES} 个知识文件，收到 {len(files)} 个")
    return files


def _tool_create_skill(db: Session, arguments: dict) -> ToolResult:
    name = str(arguments.get("name") or "").strip()
    prompt = str(arguments.get("prompt") or "").strip()
    if not name or not prompt:
        raise ValueError("创建技能需要 name 与 prompt")
    files = _skill_files_from_arguments(arguments)
    skill = create_skill_record(
        db,
        name=name,
        description=str(arguments.get("description") or "")[:255],
        prompt=prompt,
        enabled=bool(arguments.get("enabled", True)),
        files=files,
    )
    return ToolResult(
        text=json.dumps(
            {"id": skill.id, "name": skill.name, "知识文件": len(skill.files)},
            ensure_ascii=False,
        ),
        summary=f"创建了助手技能「{skill.name}」",
        link="/skills",
        changed=True,
    )


def _tool_update_skill(db: Session, arguments: dict) -> ToolResult:
    try:
        skill_id = int(arguments.get("skill_id"))
    except (TypeError, ValueError):
        raise ValueError("需要提供技能 id（可以先用 list_skills 查）") from None
    files = _skill_files_from_arguments(arguments)
    fields = {
        key: value
        for key, value in arguments.items()
        if key in {"name", "description", "prompt", "enabled"}
    }
    if not fields and files is None:
        raise ValueError("没有给出要修改的字段")
    skill = update_skill_record(db, skill_id, files=files, **fields)
    if skill is None:
        raise ValueError(f"技能 {skill_id} 不存在")
    updated = sorted(fields)
    if files is not None:
        updated.append("files")
    return ToolResult(
        text=json.dumps({"id": skill.id, "updated": updated}, ensure_ascii=False),
        summary=f"更新了助手技能「{skill.name}」",
        link="/skills",
        changed=True,
    )


# ===== 简历格式模板（助手只能制作「格式模板」，不能改样式模板的 HTML）=====


def _format_tool_properties() -> dict:
    """用 ``FORMAT_FIELDS`` 生成格式模板工具的参数声明。

    字段名、范围与说明都取自格式模板编辑器用的那一份清单，模型不必猜参数名；将来
    增删可调项时这里自动跟着变，不用在工具定义里另抄一遍（少一处人工同步）。
    """
    properties: dict = {}
    for spec in FORMAT_FIELDS:
        if spec["type"] == "color":
            properties[spec["key"]] = {
                "type": "string",
                "description": f"{spec['label']}，十六进制颜色，如 #2f6feb",
            }
        else:
            note = f"（{spec['description']}）" if spec.get("description") else ""
            properties[spec["key"]] = {
                "type": "number",
                "minimum": spec["min"],
                "maximum": spec["max"],
                "description": f"{spec['label']}，范围 {spec['min']}–{spec['max']}{note}",
            }
    return properties


_FORMAT_FIELD_LABELS = {spec["key"]: spec["label"] for spec in FORMAT_FIELDS}


def _format_config_from_arguments(arguments: dict) -> dict:
    """从入参里挑出格式模板参数，并**逐个**用 ``validated_format_config`` 校验。

    刻意不把整份直接丢给 ``validated_format_config``：那是"非法值静默丢弃"的语义，
    模型给错值时只会看到"一项都没设"，然后反复重试。逐个校验能明确指出是哪一项、
    允许范围是多少，模型一次就能改对——被拒的原因必须可见。
    """
    provided = {
        key: arguments[key]
        for key in _FORMAT_FIELD_LABELS
        if arguments.get(key) not in (None, "")
    }
    config: dict = {}
    for key, value in provided.items():
        normalized = validated_format_config({key: value})
        if key in normalized:
            config[key] = normalized[key]
            continue
        spec = next(item for item in FORMAT_FIELDS if item["key"] == key)
        if spec["type"] == "color":
            raise ValueError(
                f"{spec['label']}（{key}）必须是十六进制颜色（如 #2f6feb），收到「{value}」"
            )
        raise ValueError(
            f"{spec['label']}（{key}）必须在 {spec['min']} 到 {spec['max']} 之间，收到「{value}」"
        )
    return config


def _format_template_or_error(db: Session, arguments: dict) -> ResumeTemplate:
    """按 id 或名称取出要修改的**自制格式模板**；取不到就抛出可读原因。

    内置版式（standard/compact/...）不在数据库里，``find_by_name`` 查不到——这里要把
    "内置不能改"和"名字写错"区分开地讲清楚，模型才知道该让用户去工作台还是换个名字。
    """
    raw_id = arguments.get("template_id")
    if raw_id not in (None, ""):
        try:
            template = get_user_template(db, int(raw_id))
        except (TypeError, ValueError):
            template = None
        if template is None:
            raise ValueError(f"格式模板 {raw_id} 不存在；可以用 template_name 指名字再试")
    else:
        name = str(arguments.get("template_name") or "").strip()
        if not name:
            raise ValueError("需要提供 template_id 或 template_name 来指明要修改的格式模板")
        template = find_template_by_name(db, name)
        if template is None:
            raise ValueError(
                f"没有找到自制格式模板「{name}」；内置版式不能修改，"
                "如果是要新建一个可以用 create_format_template"
            )
    if template.kind != TEMPLATE_KIND_FORMAT:
        raise ValueError(
            f"「{template.name}」是样式模板；助手只能改格式模板（版式参数），"
            "样式模板的 HTML 请到「工作台」页修改"
        )
    return template


def _tool_create_format_template(db: Session, arguments: dict) -> ToolResult:
    name = str(arguments.get("name") or "").strip()
    if not name:
        raise ValueError("创建格式模板需要 name（模板名称）")
    config = _format_config_from_arguments(arguments)
    if not config:
        raise ValueError(
            "格式模板至少需要设置一项参数（强调色 accent / 行高 line_height / 页边距 page_padding / "
            "区块间距 section_gap / 字号系数 font_scale_adjust 等）"
        )
    try:
        # 复用工作台那套落库逻辑：命名、重名、总量上限与参数校验都在 create_user_template 里，
        # 工具只负责把参数凑齐，绝不另写一份写入路径（否则两处约束会各自漂移）。
        template = create_user_template(
            db,
            name=name,
            kind=TEMPLATE_KIND_FORMAT,
            description=str(arguments.get("description") or "")[:255],
            config=config,
            source_name="求职助手",
        )
    except TemplateError as exc:
        raise ValueError(str(exc)) from None
    return ToolResult(
        text=json.dumps(
            {"id": template.id, "name": template.name, "config": template.config},
            ensure_ascii=False,
        ),
        summary=f"新建了格式模板「{template.name}」",
        link="/skills",
        changed=True,
    )


def _tool_update_format_template(db: Session, arguments: dict) -> ToolResult:
    template = _format_template_or_error(db, arguments)
    fields: dict = {}
    if arguments.get("name") not in (None, ""):
        fields["name"] = str(arguments["name"]).strip()
    if arguments.get("description") is not None:
        fields["description"] = str(arguments["description"])
    provided_config = _format_config_from_arguments(arguments)
    if provided_config:
        # config 是整份替换语义：先把模型给的项合并进现有配置再提交。只改一项时若直接
        # 顶替，会把其它已经调好的参数悄悄清空——那正是用户最难发现的一类数据丢失。
        fields["config"] = {**(template.config or {}), **provided_config}
    if not fields:
        raise ValueError("没有给出要修改的内容（可改 name/description，或至少设置一项版式参数）")
    try:
        template = update_user_template(db, template, **fields)
    except TemplateError as exc:
        raise ValueError(str(exc)) from None
    return ToolResult(
        text=json.dumps(
            {
                "id": template.id,
                "name": template.name,
                "config": template.config,
                "updated": sorted(fields),
            },
            ensure_ascii=False,
        ),
        summary=f"修改了格式模板「{template.name}」",
        link="/skills",
        changed=True,
    )
