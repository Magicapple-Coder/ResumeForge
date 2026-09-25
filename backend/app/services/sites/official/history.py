"""官网「按岗位找公司」搜索历史的读写。

搜索发现本身仍由 ``discovery.py`` 负责；本模块只负责把一次结果保存成可回看的快照，避免把
搜索引擎的瞬时结果混进发现算法，也避免 API 层直接操作 ORM。
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy.orm import Session

from ....models.official import OfficialDiscoverySearch

DEFAULT_HISTORY_LIMIT = 50

_CANDIDATE_FIELDS = (
    "company",
    "url",
    "host",
    "evidence",
    "is_careers_page",
    "target_field",
)


def _candidate_snapshot(candidates: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """只保存候选的公共响应字段，避免把未来内部字段意外写入历史。"""
    return [
        {field: candidate.get(field) for field in _CANDIDATE_FIELDS}
        for candidate in candidates
    ]


def save_discovery_search(
    db: Session,
    *,
    keywords: str,
    city: str,
    queries: Iterable[str],
    detail: str,
    candidates: Iterable[Mapping[str, Any]],
) -> OfficialDiscoverySearch:
    """保存一次搜索及其候选快照。空结果也保存，用户才能知道确实搜过。"""
    snapshot = _candidate_snapshot(candidates)
    record = OfficialDiscoverySearch(
        keywords=(keywords or "").strip()[:200],
        city=(city or "").strip()[:64],
        queries=[str(query)[:300] for query in queries],
        candidates=snapshot,
        detail=(detail or "")[:500],
        candidate_count=len(snapshot),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_discovery_searches(
    db: Session, *, limit: int = DEFAULT_HISTORY_LIMIT
) -> list[OfficialDiscoverySearch]:
    """按新到旧列出搜索历史；不清理旧记录。"""
    return (
        db.query(OfficialDiscoverySearch)
        .order_by(OfficialDiscoverySearch.created_at.desc(), OfficialDiscoverySearch.id.desc())
        .limit(limit)
        .all()
    )


__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "list_discovery_searches",
    "save_discovery_search",
]
