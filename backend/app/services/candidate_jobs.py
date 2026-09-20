"""备选岗位：还没核对的招聘信息暂存与导入标记。

这里只做暂存；真正的岗位创建仍走 ``job_service``（同一套字段校验与技能标签解析），
避免两条写入路径行为漂移。
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..models.job import JOB_STATUS_OPEN
from ..models.material import (
    CANDIDATE_JOB_IMPORTED,
    CANDIDATE_JOB_PENDING,
    CANDIDATE_JOB_STATUSES,
    CandidateJob,
)
from ..schemas.job import JobCreate
from ..schemas.material import CandidateJobCreate, CandidateJobUpdate
from .job_service import create_job_record, find_by_job_identity, find_job_by_identity
from .trash import is_deleted

logger = logging.getLogger(__name__)

MAX_CANDIDATE_TOOL_CHARS = 6_000

# 列表默认返回多少条。候选是一份**待处理清单**，页面不会翻页；给一个上限是为了让
# 长期累积的历史候选不会把每次列表请求都拖成一个大响应。
MAX_CANDIDATE_LIST = 300

# 导入正式岗位时写进 ``Job.recognition_source`` 的来源：采集来的与手动粘贴的分开标注，
# 用户日后回溯"这条是怎么进来的"才有意义。判据是**有没有采集批次**，而不是猜标题。
RECOGNITION_SOURCE_COLLECT = "岗位采集"
RECOGNITION_SOURCE_MANUAL = "备选岗位导入"


def list_candidate_jobs(
    db: Session,
    *,
    status: str = "",
    keyword: str = "",
    collect_task_id: int | None = None,
    limit: int = MAX_CANDIDATE_LIST,
) -> list[CandidateJob]:
    query = db.query(CandidateJob)
    if status in CANDIDATE_JOB_STATUSES:
        query = query.filter(CandidateJob.status == status)
    if collect_task_id is not None:
        # 「本次采集结果」按批次过滤：采完立刻能看到"这次采到了什么"，而不必在累积的
        # 全部候选里翻找。
        query = query.filter(CandidateJob.collect_task_id == collect_task_id)
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter(
            CandidateJob.title.like(like)
            | CandidateJob.company.like(like)
            | CandidateJob.raw_text.like(like)
            | CandidateJob.description.like(like)
            | CandidateJob.note.like(like)
        )
    return (
        query.order_by(CandidateJob.created_at.desc(), CandidateJob.id.desc())
        .limit(max(1, limit))
        .all()
    )


def candidate_or_none(db: Session, candidate_id: int) -> CandidateJob | None:
    return db.get(CandidateJob, candidate_id)


def create_candidate_job(db: Session, payload: CandidateJobCreate) -> CandidateJob:
    candidate = CandidateJob(**payload.model_dump(), status=CANDIDATE_JOB_PENDING)
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    logger.info("已新增备选岗位 id=%s", candidate.id)
    return candidate


def update_candidate_job(
    db: Session, candidate: CandidateJob, payload: CandidateJobUpdate
) -> CandidateJob:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(candidate, field, value)
    db.commit()
    db.refresh(candidate)
    return candidate


def mark_candidate_imported(db: Session, candidate: CandidateJob, job_id: int) -> CandidateJob:
    candidate.status = CANDIDATE_JOB_IMPORTED
    candidate.imported_job_id = job_id
    db.commit()
    db.refresh(candidate)
    logger.info("备选岗位已导入 id=%s job_id=%s", candidate.id, job_id)
    return candidate


def delete_candidate_job(db: Session, candidate_id: int) -> bool:
    candidate = db.get(CandidateJob, candidate_id)
    if candidate is None:
        return False
    db.delete(candidate)
    db.commit()
    return True


def stage_candidate_job(
    db: Session,
    *,
    title: str,
    company: str = "",
    location: str = "",
    salary: str = "",
    source_url: str = "",
    description: str = "",
    requirements: str = "",
    additional_info: str = "",
    source: str = "",
    task_id: int | None = None,
    job_type: str = "",
) -> CandidateJob:
    """把一条采集结果放进暂存区（等用户在投递台里挑选后再导入岗位广场）。

    **不 commit**：采集是一次批量写入，由调用方统一提交——逐条提交会让"采到一半被停止"
    留下一堆半成品，也让进度回填与数据落盘不同步。
    """
    candidate = CandidateJob(
        title=title,
        company=company,
        location=location,
        salary=salary,
        source_url=source_url,
        description=description,
        requirements=requirements,
        additional_info=additional_info,
        source=source,
        collect_task_id=task_id,
        job_type=job_type,
        status=CANDIDATE_JOB_PENDING,
    )
    db.add(candidate)
    db.flush()
    return candidate


def find_staged_candidate(
    db: Session, *, title: str = "", company: str = "", source_url: str = ""
) -> CandidateJob | None:
    """暂存区里是否已有同一个岗位（**与岗位广场那套判据共用同一份实现**）。

    不按 ``status`` 过滤：已经导入过的候选，它的正式岗位必然在 ``job`` 表里，
    调用方查岗位表那一遍就会命中，这里再筛一次状态只会让"重复"被漏判。
    """
    return find_by_job_identity(
        db, CandidateJob, title=title, company=company, source_url=source_url
    )


def import_candidates(db: Session, candidate_ids: list[int]) -> dict:
    """把选中的候选导入岗位广场：服务端建岗位并回填关联，**逐条如实反馈结果**。

    为什么由服务端建岗位而不是让前端逐条调保存接口：那样"导入 10 条"会变成 10 次网络往返，
    而且中途失败会留下"导入了一半"的状态；这里一次事务做完，任一条的失败都只影响它自己。

    重复判定复用 ``find_job_by_identity``（与采集去重同一份实现）。命中分两种：库里有的直接
    **指向已有岗位**；**在回收站里的**返回独立结果 ``trashed``——既不新建第二条（那是重复的
    来源），也不自动恢复（用户删它是有理由的），而是让界面告诉他去回收站处理。

    原话：
    而不是再造一条——用户勾错了不该在岗位广场里留下第二个副本。
    """
    imported = duplicate = missing = invalid = trashed = 0
    results: list[dict] = []
    # 去重且保序：同一个 id 传两次不该被导入两次。
    for candidate_id in dict.fromkeys(candidate_ids):
        candidate = db.get(CandidateJob, candidate_id)
        if candidate is None:
            missing += 1
            results.append({"candidate_id": candidate_id, "title": "", "outcome": "missing"})
            continue

        existing = find_job_by_identity(
            db,
            title=candidate.title,
            company=candidate.company,
            source_url=candidate.source_url,
        )
        if existing is not None and is_deleted(existing):
            # 岗位广场的**回收站**里已经有一条同名岗位。
            #
            # 刻意**不**新建第二条（那正是重复的来源），也刻意**不**自动恢复它（用户删它是有
            # 理由的）。如实返回一个独立的结果，让界面告诉他去回收站处理。
            trashed += 1
            results.append(
                {
                    "candidate_id": candidate.id,
                    "title": candidate.title,
                    "outcome": "trashed",
                    "job_id": existing.id,
                }
            )
            continue
        if existing is not None:
            duplicate += 1
            # 不用 ``mark_candidate_imported``：它自带 commit，逐条提交会让"导入到一半失败"
            # 留下一半已改、一半未改的库。这里只标字段，最后一次提交。
            candidate.status = CANDIDATE_JOB_IMPORTED
            candidate.imported_job_id = existing.id
            results.append(
                {
                    "candidate_id": candidate.id,
                    "title": candidate.title,
                    "outcome": "duplicate",
                    "job_id": existing.id,
                }
            )
            continue

        if not candidate.title.strip():
            # 没有岗位名的候选没法成为一个正式岗位（``JobCreate`` 要求标题非空）。
            # 如实说"这条导不了"，而不是给一个空的标题硬塞进去。
            invalid += 1
            results.append(
                {
                    "candidate_id": candidate.id,
                    "title": candidate.title,
                    "outcome": "invalid",
                }
            )
            continue

        job = create_job_record(
            db,
            JobCreate(
                title=candidate.title,
                company=candidate.company,
                location=candidate.location,
                salary=candidate.salary,
                # 采集透传的岗位类型入库；候选没标（手动粘贴/历史数据）回落「校招」。
                job_type=candidate.job_type or "校招",
                source_url=candidate.source_url,
                # 采集回来的 JD 已经按小标题切成两段，直接各归各位；
                # 手动粘贴的候选没有这两段，退回用原文填描述（与以前的导入行为一致）。
                description=candidate.description or candidate.raw_text,
                requirements=candidate.requirements,
                additional_info=candidate.additional_info,
                note=candidate.note,
                status=JOB_STATUS_OPEN,
                recognition_source=(
                    RECOGNITION_SOURCE_COLLECT
                    if candidate.collect_task_id
                    else RECOGNITION_SOURCE_MANUAL
                ),
            ),
            # 把候选上的来源透传给岗位：采集导入的候选 source 是站点名（如「BOSS直聘」），
            # 与旧采集器直写 `job.source` 的口径一致；不传的话会落到模型默认值「手动添加」，
            # 让"手动添加 vs 自动采集"这件事基于错误数据。
            source=candidate.source,
        )
        candidate.status = CANDIDATE_JOB_IMPORTED
        candidate.imported_job_id = job.id
        imported += 1
        results.append(
            {
                "candidate_id": candidate.id,
                "title": candidate.title,
                "outcome": "imported",
                "job_id": job.id,
            }
        )

    db.commit()
    logger.info(
        "候选导入完成：新建 %s，重复 %s，在回收站里 %s，无效 %s，缺失 %s",
        imported,
        duplicate,
        trashed,
        invalid,
        missing,
    )
    return {
        "imported": imported,
        "duplicate": duplicate,
        "trashed": trashed,
        "invalid": invalid,
        "missing": missing,
        "results": results,
    }


def candidate_brief(candidate: CandidateJob) -> dict:
    return {
        "id": candidate.id,
        "岗位": candidate.title,
        "公司": candidate.company,
        "城市": candidate.location,
        "薪资": candidate.salary,
        "状态": "已导入" if candidate.status == CANDIDATE_JOB_IMPORTED else "待处理",
        "导入的岗位 id": candidate.imported_job_id,
        "来源": candidate.source,
        "岗位链接": candidate.source_url,
        "备注": candidate.note,
        "截图数量": len(candidate.images or []),
        "更新时间": candidate.updated_at.isoformat() if candidate.updated_at else None,
    }


def candidate_detail_text(candidate: CandidateJob, max_chars: int = MAX_CANDIDATE_TOOL_CHARS) -> str:
    parts = [
        f"岗位：{candidate.title or '（未填写）'}",
        f"公司：{candidate.company or '（未填写）'}",
        f"状态：{'已导入' if candidate.status == CANDIDATE_JOB_IMPORTED else '待处理'}",
    ]
    if candidate.location:
        parts.append(f"城市：{candidate.location}")
    if candidate.salary:
        parts.append(f"薪资：{candidate.salary}")
    if candidate.note:
        parts.append(f"备注：{candidate.note}")
    # 采集回来的候选把 JD 存在 description / requirements 两段里，粘贴来的候选存在 raw_text。
    # 两者都要读——只读 raw_text 会让助手对采集来的岗位"什么都看不到"。
    if candidate.description:
        parts.append(f"职位描述：\n{candidate.description}")
    if candidate.requirements:
        parts.append(f"任职要求：\n{candidate.requirements}")
    if candidate.raw_text:
        parts.append(f"招聘原文：\n{candidate.raw_text}")
    if candidate.images:
        parts.append(f"附有 {len(candidate.images)} 张招聘截图（图片内容未提取）")
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = f"{text[:max_chars].rstrip()}…"
    return text


__all__ = [
    "MAX_CANDIDATE_LIST",
    "MAX_CANDIDATE_TOOL_CHARS",
    "RECOGNITION_SOURCE_COLLECT",
    "RECOGNITION_SOURCE_MANUAL",
    "candidate_brief",
    "candidate_detail_text",
    "candidate_or_none",
    "create_candidate_job",
    "delete_candidate_job",
    "find_staged_candidate",
    "import_candidates",
    "list_candidate_jobs",
    "mark_candidate_imported",
    "stage_candidate_job",
    "update_candidate_job",
]
