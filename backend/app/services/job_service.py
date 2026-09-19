"""岗位的持久化操作，供 HTTP 路由与助手工具共用。

抽出来是为了让助手工具复用同一套写逻辑（尤其是技能标签的重算），避免两处各写
一份、日后行为漂移。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models.job import Job
from ..schemas.job import JobCreate, JobUpdate
from .jd_parser import parse_jd


def _keywords_for(job: Job) -> list[dict]:
    """按 JD 内容解析技能标签；列表页与详情页直接读这一列。"""
    return [
        tag.model_dump()
        for tag in parse_jd(f"{job.description}\n{job.requirements}\n{job.additional_info}")[
            "skills"
        ]
    ]


def refresh_job_keywords(job: Job) -> None:
    """按当前 JD 重算技能标签。

    **公开出来是因为它有三处调用方**（新建、更新、以及采集的"补齐详情"）：只把 JD 写进去而
    不重算标签，是那种"看起来补上了、搜索和匹配却仍然按空标签走"的静默错误。
    """
    job.keywords = _keywords_for(job)


MAX_JOB_NOTE_CHARS = 2000


def find_by_job_identity(
    db: Session, model: type, *, title: str = "", company: str = "", source_url: str = ""
):
    """按"同一投递链接，或同一公司下的同名岗位"在 ``model`` 表里找已存在的记录。

    **判据只实现这一份**：岗位广场的去重、暂存区的去重、以及"勾选导入"时的重复判定
    全都走它。各写一份必然漂移，而漂移的后果很刺眼——采集说"这条没采过"，导入时又说
    "岗位广场里已经有了"，同一件事给出两个相反的答复。

    ``model`` 传表类（``Job`` / ``CandidateJob``），因此不绑死在某一张表上。
    """
    url = (source_url or "").strip()
    if url:
        existing = db.query(model).filter(model.source_url == url).first()
        if existing is not None:
            return existing
    name = (title or "").strip()
    employer = (company or "").strip()
    if name and employer:
        return db.query(model).filter(model.company == employer, model.title == name).first()
    return None


def find_job_by_identity(
    db: Session, *, title: str = "", company: str = "", source_url: str = ""
) -> Job | None:
    """岗位广场里是否已有这个岗位。"""
    return find_by_job_identity(db, Job, title=title, company=company, source_url=source_url)


def note_with_source(note: str, recognition_source: str) -> str:
    """在备注末尾补一行来源标注，方便用户回溯这条招聘信息是怎么来的。

    已经标过就不再重复追加：用户来回编辑同一条岗位时不该积累出一串"来源："。
    """
    source = (recognition_source or "").strip()
    note = (note or "").strip()
    if not source:
        return note[:MAX_JOB_NOTE_CHARS]
    marker = f"来源：{source}"
    if marker in note:
        return note[:MAX_JOB_NOTE_CHARS]
    if not note:
        return marker[:MAX_JOB_NOTE_CHARS]
    # 先给用户正文留出标记的位置，再拼上标记。反过来（先拼再整体截断）在正文接近
    # 上限时会把刚加上的来源行裁掉——标注静默消失，用户还以为这条是手填的。
    budget = MAX_JOB_NOTE_CHARS - len(marker) - 1
    return f"{note[: max(0, budget)]}\n{marker}"


def create_job_record(db: Session, payload: JobCreate, *, source: str = "") -> Job:
    """建立一条正式岗位。

    ``source``（这条招聘信息来自哪个站点）刻意**不进** ``JobCreate``：它是历史兼容列，
    手动录入路径不暴露它。需要注明真实来源的调用方（采集导入）显式传入；不传时保留模型
    默认值「手动添加」，与手动录入路径保持一致。传空串同样等于不传——否则 ``Job(**data)``
    会把默认值覆盖成空串。
    """
    data = payload.model_dump()
    data["note"] = note_with_source(data.get("note", ""), data.get("recognition_source", ""))
    clean_source = (source or "").strip()
    if clean_source:
        data["source"] = clean_source
    job = Job(**data)
    refresh_job_keywords(job)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job_record(db: Session, job: Job, payload: JobUpdate) -> Job:
    data = payload.model_dump(exclude_unset=True)
    if "recognition_source" in data or ("note" in data and job.recognition_source):
        # 修改备注时保持来源标注仍在（用户在表单里改掉整段备注也不丢溯源信息）。
        data["note"] = note_with_source(
            data.get("note", job.note),
            data.get("recognition_source", job.recognition_source),
        )
    for field, value in data.items():
        setattr(job, field, value)
    # 只有 JD 内容变了才值得重算标签。
    if {"description", "requirements", "additional_info"}.intersection(data):
        refresh_job_keywords(job)
    db.commit()
    db.refresh(job)
    return job
