"""수집 오케스트레이션: 전 소스 병렬 호출 → 중복제거 → DB 적재."""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from .config import CATEGORY_IDS, REGION_IDS, get_settings
from .db import DB, Article
from .sources import enabled_sources
from .sources.base import USER_AGENT

log = logging.getLogger("mytrend.ingest")


async def run_ingest(db: DB, *, categories: list[str] | None = None,
                     regions: list[str] | None = None,
                     hours: int | None = None,
                     per_feed: int | None = None) -> dict:
    """모든 활성 소스에서 수집해 DB에 적재. 요약 통계 반환."""
    s = get_settings()
    categories = categories or CATEGORY_IDS
    regions = regions or REGION_IDS
    hours = hours or s.mytrend_default_hours
    since = time.time() - hours * 3600
    per_feed = per_feed or s.mytrend_per_feed_limit

    sources = enabled_sources()
    started = time.time()
    per_source: dict[str, int] = {}
    errors: dict[str, str] = {}
    all_articles: list[Article] = []

    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT}) as client:
        async def _one(src):
            try:
                arts = await src.fetch(client, categories=categories, regions=regions,
                                       since=since, per_feed=per_feed)
                per_source[src.name] = len(arts)
                return arts
            except Exception as e:  # 소스 단위 격리
                errors[src.name] = str(e)
                log.warning("source %s failed: %s", src.name, e)
                return []

        results = await asyncio.gather(*[_one(s) for s in sources])
        for arts in results:
            all_articles.extend(arts)

    # 적재(중복은 DB upsert에서 흡수)
    inserted = db.upsert_many(all_articles)
    return {
        "fetched": len(all_articles),
        "stored": inserted,
        "per_source": per_source,
        "errors": errors,
        "sources_active": [s.name for s in sources],
        "elapsed_sec": round(time.time() - started, 2),
        "ts": time.time(),
    }
