"""MyTrend FastAPI 애플리케이션."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import DISPLAY_CATEGORIES, REGIONS, get_settings
from .db import DB
from .ingest import run_ingest
from .nlp import build_trends
from .scheduler import IngestScheduler
from .search import search_news
from .sources import all_sources
from .trends import get_trends, clear_cache

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    db = DB(s.mytrend_db_path)
    state["db"] = db
    sched = IngestScheduler(db)
    sched.start()
    state["sched"] = sched
    yield
    sched.shutdown()


app = FastAPI(title="MyTrend API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


# ───────────────────────── API ─────────────────────────
@app.get("/api/config")
def api_config():
    """프론트 초기화용 메타데이터(분야·지역·소스 상태)."""
    sources = [{
        "name": s.name, "label": s.label,
        "requires_key": s.requires_key, "enabled": s.enabled(),
    } for s in all_sources()]
    return {
        "categories": DISPLAY_CATEGORIES,
        "regions": REGIONS,
        "sources": sources,
        "settings": {
            "default_hours": get_settings().mytrend_default_hours,
            "ingest_interval_min": get_settings().mytrend_ingest_interval_min,
        },
    }


@app.get("/api/trends")
async def api_trends(
    categories: list[str] | None = Query(None),
    regions: list[str] | None = Query(None),
    sources: list[str] | None = Query(None),
    hours: int = Query(24, ge=1, le=168),
    min_freq: int = Query(2, ge=1, le=10),
    max_kw: int = Query(80, ge=10, le=300),
    live: bool = Query(True),
):
    """트렌드 맵(키워드 노드/링크 + 분야 집계) 반환."""
    data = await get_trends(
        state["db"], categories=categories, regions=regions, sources=sources,
        hours=hours, min_freq=min_freq, max_kw=max_kw, live=live,
    )
    return JSONResponse(data)


@app.post("/api/ingest")
async def api_ingest(
    categories: list[str] | None = Query(None),
    regions: list[str] | None = Query(None),
    hours: int | None = Query(None),
):
    """수동 즉시 수집 트리거."""
    result = await run_ingest(state["db"], categories=categories,
                              regions=regions, hours=hours)
    clear_cache()
    return result


@app.get("/api/search")
async def api_search(
    q: str = Query(..., min_length=1),
    regions: list[str] | None = Query(None),
    hours: int = Query(48, ge=1, le=168),
    store: bool = Query(False),
    min_freq: int = Query(1, ge=1, le=10),
    max_kw: int = Query(60, ge=10, le=300),
):
    """키워드로 관련 뉴스를 실시간 검색.

    - 항상 기사 목록(articles)과 미니 트렌드(trend)를 반환.
    - store=true 면 결과를 DB에 적재해 전체 트렌드 맵에 병합되도록 한다.
    """
    arts = await search_news(q, regions=regions, hours=hours)
    if store and arts:
        state["db"].upsert_many(arts)
        clear_cache()
    trend = build_trends(arts, min_freq=min_freq, max_kw=max_kw)
    return JSONResponse({
        "query": q,
        "count": len(arts),
        "stored": bool(store and arts),
        "articles": [{
            "title": a.title, "url": a.url, "publisher": a.publisher,
            "region": a.region, "source": a.source, "published_at": a.published_at,
        } for a in arts],
        "trend": trend,
    })


@app.get("/api/stats")
def api_stats():
    """DB·스케줄러 상태."""
    sched = state.get("sched")
    return {
        "db": state["db"].stats(),
        "last_scheduled_ingest": getattr(sched, "last_result", None),
    }


@app.get("/api/health")
def health():
    return {"ok": True}


# ──────────────────── 프론트엔드 정적 서빙 ────────────────────
@app.get("/")
def index():
    idx = FRONTEND_DIR / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return JSONResponse({"error": "frontend not built"}, status_code=404)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
