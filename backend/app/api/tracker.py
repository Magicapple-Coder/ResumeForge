"""求职进度接口。

识别导入分两步，和岗位的多份导入是同一条原则：``/parse`` **只算不写**，把"这条会新增
还是会更新、为什么"返回给用户看；确认之后 ``/apply`` 再执行同一份计划。这样"预览说会
更新、点了确认却没更新"这类不一致从结构上就不会发生。

路由顺序有讲究：``/parse`` / ``/apply`` / ``/export`` 必须注册在 ``/{track_id}`` 之前，
否则会被当成路径参数去解析成整数，返回一个和"路由不存在"很像的 422。
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models.tracker import STATUSES
from ..schemas.tracker import (
    TrackApplyOut,
    TrackApplyRequest,
    TrackCreate,
    TrackListOut,
    TrackOut,
    TrackParseOut,
    TrackParseRequest,
    TrackUpdate,
)
from ..services.attachments import (
    assert_attachment_budget,
    image_data_urls,
    normalize_extraction_images,
    total_attachment_bytes,
)
from ..services.document_text import extract_documents_text
from ..services.llm import create_provider
from ..services.llm.base import LLMError
from ..services.settings_service import get_llm_config
from ..services.text_extraction import llm_is_configured
from ..services.tracker import (
    apply_merges,
    create_track,
    delete_track,
    list_tracks,
    preview_merges,
    summarize,
    to_csv,
    to_json,
    track_or_none,
    track_out,
    update_track,
)
from ..services.tracker_extract import extract_tracker_records, local_tracker_records

router = APIRouter(prefix="/api/tracker", tags=["tracker"])
logger = logging.getLogger(__name__)


@router.get("", response_model=TrackListOut)
def read_tracks(
    status: str = Query(default=""),
    keyword: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """列出求职进度；可按状态与关键词过滤，统计随列表一起返回。"""
    if status and status not in STATUSES:
        raise HTTPException(status_code=422, detail="未知的进度状态")
    records = list_tracks(db, status=status, keyword=keyword)
    return TrackListOut(items=[track_out(item) for item in records], **summarize(records))


@router.post("", response_model=TrackOut, status_code=201)
def create_track_entry(payload: TrackCreate, db: Session = Depends(get_db)):
    return track_out(create_track(db, payload))


@router.get("/export")
def export_tracks(
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    status: str = Query(default=""),
    keyword: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """导出当前筛选条件下的进度记录。"""
    if status and status not in STATUSES:
        raise HTTPException(status_code=422, detail="未知的进度状态")
    records = list_tracks(db, status=status, keyword=keyword)
    if format == "json":
        content, media_type, suffix = to_json(records), "application/json; charset=utf-8", "json"
    else:
        # text/csv 不带 charset 时 Excel 会按本地编码猜，中文列名直接变乱码；
        # 内容里的 BOM 再兜一层（见 services/tracker.to_csv）。
        content, media_type, suffix = to_csv(records), "text/csv; charset=utf-8", "csv"
    stamp = str(len(records))
    filename = f"求职进度-{stamp}条.{suffix}"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return Response(content, media_type=media_type, headers=headers)


@router.post("/parse", response_model=TrackParseOut)
async def parse_tracks(payload: TrackParseRequest, db: Session = Depends(get_db)):
    """从一段通知材料里识别进度条目；**只返回预览，不写库**。"""
    try:
        images = normalize_extraction_images(payload.images)
        documents = extract_documents_text(payload.documents)
        assert_attachment_budget(
            count=len(payload.images) + len(payload.documents),
            total_bytes=total_attachment_bytes(images) + documents.size_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    urls = image_data_urls(images)
    source_text = "\n\n".join(part for part in (payload.text, documents.text) if part.strip())
    if not source_text.strip() and not urls:
        raise HTTPException(status_code=422, detail="请先粘贴通知内容或上传截图、文档")

    notes: list[str] = list(documents.warnings)
    config = get_llm_config(db)
    if not llm_is_configured(config):
        records, extra = local_tracker_records(source_text)
        return TrackParseOut(
            items=preview_merges(db, records), parse_engine="local", notes=[*notes, *extra]
        )

    provider = create_provider(config)
    # 模型调用可能持续几十秒：先释放请求会话，避免 await 期间一直占着连接池。
    db.close()
    try:
        records, extra = await extract_tracker_records(provider, source_text, urls)
        engine = "ai"
    except LLMError as exc:
        logger.warning("求职进度识别失败，已回退本地规则：%s", exc)
        records, extra = local_tracker_records(source_text)
        engine = "local"
        notes.append(f"AI 识别失败（{exc}），已改用本地关键词匹配。")
    except Exception:  # noqa: BLE001 - 外部模型异常不能阻断识别
        logger.exception("求职进度识别发生内部错误，已回退本地规则")
        records, extra = local_tracker_records(source_text)
        engine = "local"
        notes.append("AI 识别发生内部错误，已改用本地关键词匹配。")

    if not records:
        notes.append(
            "这段材料里没有识别出同时包含公司和岗位的进度记录。"
            "如果确实是一封进度通知，可以手动添加，或把邮件正文完整一些再试。"
        )
    # 合并预览要读现有记录，所以必须用**新的**会话——上面那个已经关掉了。
    with SessionLocal() as preview_db:
        items = preview_merges(preview_db, records)
    return TrackParseOut(items=items, parse_engine=engine, notes=[*notes, *extra])


@router.post("/apply", response_model=TrackApplyOut)
def apply_tracks(payload: TrackApplyRequest, db: Session = Depends(get_db)):
    """把用户确认过的进度条目写入。与 ``/parse`` 共用同一份合并计划。"""
    if not payload.items:
        raise HTTPException(status_code=422, detail="没有要保存的记录")
    try:
        return apply_merges(db, payload.items, source=payload.source)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{track_id}", response_model=TrackOut)
def read_track(track_id: int, db: Session = Depends(get_db)):
    record = track_or_none(db, track_id)
    if record is None:
        raise HTTPException(status_code=404, detail="进度记录不存在或已被删除")
    return track_out(record)


@router.put("/{track_id}", response_model=TrackOut)
def save_track(track_id: int, payload: TrackUpdate, db: Session = Depends(get_db)):
    record = track_or_none(db, track_id)
    if record is None:
        raise HTTPException(status_code=404, detail="进度记录不存在或已被删除")
    return track_out(update_track(db, record, payload))


@router.delete("/{track_id}", status_code=204)
def remove_track(track_id: int, db: Session = Depends(get_db)):
    if not delete_track(db, track_id):
        raise HTTPException(status_code=404, detail="进度记录不存在或已被删除")
    return None
