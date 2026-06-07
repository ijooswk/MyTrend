"""트렌드 조회 계층: 캐시 + (미스 시) 실시간 보완."""
from __future__ import annotations

import json
import time

from .config import CATEGORY_IDS, REGION_IDS, get_settings
from .db import DB
from .ingest import run_ingest
from .nlp import build_trends, compute_rising

# 간단한 인메모리 캐시: key -> (expire_ts, payload)
_CACHE: dict[str, tuple[float, dict]] = {}


def _key(categories, regions, sources, hours, min_freq, max_kw, per_feed) -> str:
    return json.dumps([sorted(categories), sorted(regions),
                       sorted(sources or []), hours, min_freq, max_kw, per_feed],
                      ensure_ascii=False)


async def get_trends(db: DB, *, categories: list[str] | None = None,
                     regions: list[str] | None = None,
                     sources: list[str] | None = None,
                     hours: int | None = None, min_freq: int = 2,
                     max_kw: int = 80, per_feed: int | None = None,
                     live: bool = True) -> dict:
    """트렌드 맵 반환.

    1) 캐시 히트 시 즉시 반환.
    2) DB에 해당 조건 기사가 없고 live=True 면 실시간 수집 후 재조회(캐시 보완).
    """
    s = get_settings()
    categories = categories or CATEGORY_IDS
    regions = regions or REGION_IDS
    hours = hours or s.mytrend_default_hours

    ck = _key(categories, regions, sources, hours, min_freq, max_kw, per_feed)
    now = time.time()
    hit = _CACHE.get(ck)
    if hit and hit[0] > now:
        out = dict(hit[1])
        out["cache"] = "hit"
        return out

    since = now - hours * 3600
    arts = db.query(since=since, categories=categories, regions=regions, sources=sources)

    backfilled = False
    if not arts and live:
        # 캐시 미스(저장된 데이터 없음) → 즉시 수집 후 재조회
        await run_ingest(db, categories=categories, regions=regions, hours=hours,
                         per_feed=per_feed)
        arts = db.query(since=since, categories=categories, regions=regions, sources=sources)
        backfilled = True

    payload = build_trends(arts, min_freq=min_freq, max_kw=max_kw)
    payload["rising"] = compute_rising(arts, now - (hours / 2) * 3600)
    payload.update({
        "cache": "backfill" if backfilled else "miss",
        "window_hours": hours,
        "categories": categories,
        "regions": regions,
        "sources_filter": sources,
        "generated_at": now,
    })
    if len(_CACHE) > 256:          # 메모리 무한증가 방지
        for k in [k for k, (exp, _) in _CACHE.items() if exp <= now]:
            _CACHE.pop(k, None)
        if len(_CACHE) > 256:
            _CACHE.clear()
    _CACHE[ck] = (now + s.mytrend_cache_ttl, payload)
    return payload


def clear_cache():
    _CACHE.clear()
