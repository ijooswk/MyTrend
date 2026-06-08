"""MyTrend FastAPI 애플리케이션."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import csv
import io
from collections import Counter

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import ai
from .config import DISPLAY_CATEGORIES, REGIONS, get_settings
from .db import DB
from .ingest import run_ingest
from .nlp import build_trends
from .scheduler import IngestScheduler
from .search import search_news
from .sources import all_sources
from .timeline import build_timeline
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
    per_feed: int | None = Query(None, ge=5, le=200),
    assoc_threshold: float = Query(0.2, ge=0.0, le=0.8),
    live: bool = Query(True),
):
    """트렌드 맵(키워드 노드/링크 + 분야 집계) 반환."""
    data = await get_trends(
        state["db"], categories=categories, regions=regions, sources=sources,
        hours=hours, min_freq=min_freq, max_kw=max_kw, per_feed=per_feed,
        assoc_threshold=assoc_threshold, live=live,
    )
    return JSONResponse(data)


@app.post("/api/ingest")
async def api_ingest(
    categories: list[str] | None = Query(None),
    regions: list[str] | None = Query(None),
    hours: int | None = Query(None),
    per_feed: int | None = Query(None, ge=5, le=200),
):
    """수동 즉시 수집 트리거."""
    result = await run_ingest(state["db"], categories=categories,
                              regions=regions, hours=hours, per_feed=per_feed)
    clear_cache()
    return result


@app.get("/api/search")
async def api_search(
    q: str = Query(..., min_length=1),
    regions: list[str] | None = Query(None),
    hours: int = Query(48, ge=1, le=168),
    count: int = Query(30, ge=5, le=100),
    store: bool = Query(False),
    min_freq: int = Query(1, ge=1, le=10),
    max_kw: int = Query(60, ge=10, le=300),
):
    """키워드로 관련 뉴스를 실시간 검색.

    - 항상 기사 목록(articles)과 미니 트렌드(trend)를 반환.
    - count: 소스별 최대 검색 기사 수.
    - store=true 면 결과를 DB에 적재해 전체 트렌드 맵에 병합되도록 한다.
    """
    arts = await search_news(q, regions=regions, hours=hours, per_region=count)
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


@app.get("/api/timeline")
def api_timeline(
    keyword: str | None = Query(None),
    categories: list[str] | None = Query(None),
    regions: list[str] | None = Query(None),
    sources: list[str] | None = Query(None),
    hours: int = Query(24, ge=2, le=168),
    buckets: int = Query(24, ge=4, le=96),
):
    """시간버킷별 키워드 빈도 시계열. keyword 지정 시 해당 키워드만."""
    import time as _t
    since = _t.time() - hours * 3600
    arts = state["db"].query(since=since, categories=categories,
                             regions=regions, sources=sources)
    return JSONResponse(build_timeline(arts, hours=hours, buckets=buckets,
                                       keyword=keyword))


@app.get("/api/correlation")
async def api_correlation(
    metric: str = Query("npmi", pattern="^(npmi|temporal)$"),
    categories: list[str] | None = Query(None),
    regions: list[str] | None = Query(None),
    sources: list[str] | None = Query(None),
    hours: int = Query(24, ge=2, le=168),
    top: int = Query(18, ge=4, le=40),
    buckets: int = Query(24, ge=4, le=96),
):
    """상위 키워드 간 상관 행렬(히트맵용).

    metric=npmi: 동시출현 연관도 / metric=temporal: 시계열 동조 상관.
    """
    import time as _t
    from . import assoc
    from .nlp import tokenize
    from .timeline import build_timeline
    since = _t.time() - hours * 3600
    arts = state["db"].query(since=since, categories=categories,
                             regions=regions, sources=sources)
    # 상위 키워드(제목 빈도)
    freq = Counter()
    for a in arts:
        for w in set(tokenize(a.title)):
            freq[w] += 1
    keywords = [w for w, _ in freq.most_common(top)]
    if not keywords:
        return {"metric": metric, "keywords": [], "matrix": [], "labels": {}}

    if metric == "npmi":
        n, f, co = assoc.cooccur_stats(arts, keywords)
        idx = {k: i for i, k in enumerate(keywords)}
        m = [[1.0 if i == j else 0.0 for j in range(len(keywords))] for i in range(len(keywords))]
        for (x, y), c in co.items():
            if x in idx and y in idx and c >= 1:
                v = round(assoc.npmi(n, f[x], f[y], c), 3)
                m[idx[x]][idx[y]] = v
                m[idx[y]][idx[x]] = v
        matrix = m
    else:
        tl = build_timeline(arts, hours=hours, buckets=buckets)
        # 상위 키워드에 대한 시계열만 별도 산출
        series = {}
        for kw in keywords:
            series[kw] = build_timeline(arts, hours=hours, buckets=buckets, keyword=kw)["series"].get(kw, [0] * buckets)
        matrix = assoc.correlation_matrix(series, keywords)

    return {"metric": metric, "keywords": keywords, "matrix": matrix,
            "labels": {w: w for w in keywords}}


@app.get("/api/export")
async def api_export(
    fmt: str = Query("csv", pattern="^(csv|json)$"),
    categories: list[str] | None = Query(None),
    regions: list[str] | None = Query(None),
    sources: list[str] | None = Query(None),
    hours: int = Query(24, ge=1, le=168),
    min_freq: int = Query(1, ge=1, le=10),
    max_kw: int = Query(200, ge=10, le=500),
):
    """현재 트렌드 키워드를 CSV/JSON 으로 내보내기(다른 분야·도구에서 재사용).

    컬럼: keyword, frequency, category, sentiment, sentiment_label, connections, top_article
    """
    data = await get_trends(
        state["db"], categories=categories, regions=regions, sources=sources,
        hours=hours, min_freq=min_freq, max_kw=max_kw, live=False,
    )
    deg: dict[str, int] = {}
    for l in data.get("links", []):
        deg[l["source"]] = deg.get(l["source"], 0) + 1
        deg[l["target"]] = deg.get(l["target"], 0) + 1
    rows = [{
        "keyword": k["id"], "frequency": k["freq"], "category": k["cat"],
        "sentiment": k.get("sent", 0), "sentiment_label": k.get("sentLabel", "neu"),
        "connections": deg.get(k["id"], 0),
        "top_article": (k["articles"][0]["title"] if k.get("articles") else ""),
    } for k in data.get("kws", [])]

    if fmt == "json":
        return JSONResponse({"generated_at": data.get("generated_at"),
                             "window_hours": hours, "count": len(rows), "keywords": rows})
    buf = io.StringIO()
    cols = ["keyword", "frequency", "category", "sentiment", "sentiment_label",
            "connections", "top_article"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=mytrend_keywords.csv"})


@app.get("/api/ai/status")
def api_ai_status():
    """AI 사용 가능 여부와 모델."""
    return {"enabled": ai.ai_enabled(),
            "model": get_settings().mytrend_ai_model if ai.ai_enabled() else None}


async def _trend_for_ai(categories, regions, sources, hours):
    return await get_trends(state["db"], categories=categories, regions=regions,
                            sources=sources, hours=hours, min_freq=1, max_kw=60, live=False)


@app.post("/api/ai/briefing")
async def api_ai_briefing(
    lang: str = Query("ko", pattern="^(ko|en)$"),
    categories: list[str] | None = Query(None),
    regions: list[str] | None = Query(None),
    sources: list[str] | None = Query(None),
    hours: int = Query(24, ge=1, le=168),
):
    """현재 트렌드를 자연어 브리핑으로 생성(온디맨드)."""
    if not ai.ai_enabled():
        return JSONResponse({"error": "AI disabled (no OpenRouter key)"}, status_code=503)
    data = await _trend_for_ai(categories, regions, sources, hours)
    if not data.get("kws"):
        return JSONResponse({"error": "no trend data"}, status_code=409)
    ck = ("brief", lang, [k["id"] for k in data["kws"][:25]], data.get("sentimentOverall"))
    cached = ai.cache_get(*ck)
    if cached:
        return {"text": cached, "cached": True}
    try:
        text = await ai.chat(ai.build_briefing_messages(data, lang), temperature=0.4)
    except ai.AIUnavailable as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    ai.cache_put(text, *ck)
    return {"text": text, "cached": False}


@app.post("/api/ai/label-clusters")
async def api_ai_labels(
    lang: str = Query("ko", pattern="^(ko|en)$"),
    categories: list[str] | None = Query(None),
    regions: list[str] | None = Query(None),
    sources: list[str] | None = Query(None),
    hours: int = Query(24, ge=1, le=168),
):
    """토픽 군집에 짧은 테마 라벨을 부여."""
    if not ai.ai_enabled():
        return JSONResponse({"error": "AI disabled (no OpenRouter key)"}, status_code=503)
    data = await _trend_for_ai(categories, regions, sources, hours)
    clusters = data.get("clusters", [])
    if not clusters:
        return {"labels": {}}
    ck = ("labels", lang, [(c["id"], tuple(c["keywords"])) for c in clusters])
    cached = ai.cache_get(*ck)
    if cached:
        return {"labels": ai.parse_labels(cached), "cached": True}
    try:
        text = await ai.chat(ai.build_label_messages(clusters, lang), temperature=0.2)
    except ai.AIUnavailable as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    ai.cache_put(text, *ck)
    return {"labels": ai.parse_labels(text), "cached": False}


@app.post("/api/ai/ask")
async def api_ai_ask(
    q: str = Query(..., min_length=2),
    lang: str = Query("ko", pattern="^(ko|en)$"),
    categories: list[str] | None = Query(None),
    regions: list[str] | None = Query(None),
    sources: list[str] | None = Query(None),
    hours: int = Query(24, ge=1, le=168),
):
    """현재 기사 제목을 근거로 질문에 답변(RAG-lite)."""
    if not ai.ai_enabled():
        return JSONResponse({"error": "AI disabled (no OpenRouter key)"}, status_code=503)
    import time as _t
    arts = state["db"].query(since=_t.time() - hours * 3600, categories=categories,
                             regions=regions, sources=sources, limit=80)
    if not arts:
        return JSONResponse({"error": "no articles in window"}, status_code=409)
    ck = ("ask", lang, q, len(arts), arts[0].id if arts else "")
    cached = ai.cache_get(*ck)
    if cached:
        return {"answer": cached, "cached": True, "evidence": len(arts)}
    try:
        text = await ai.chat(ai.build_qa_messages(q, arts, lang), temperature=0.3)
    except ai.AIUnavailable as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    ai.cache_put(text, *ck)
    return {"answer": text, "cached": False, "evidence": len(arts)}


@app.post("/api/ai/relate")
async def api_ai_relate(
    a: str = Query(..., min_length=1),
    b: str = Query(..., min_length=1),
    lang: str = Query("ko", pattern="^(ko|en)$"),
    categories: list[str] | None = Query(None),
    regions: list[str] | None = Query(None),
    sources: list[str] | None = Query(None),
    hours: int = Query(24, ge=1, le=168),
):
    """두 키워드의 상관 관계를 기사 근거로 설명(connect-the-dots)."""
    if not ai.ai_enabled():
        return JSONResponse({"error": "AI disabled (no OpenRouter key)"}, status_code=503)
    import time as _t
    from .nlp import tokenize
    arts = state["db"].query(since=_t.time() - hours * 3600, categories=categories,
                             regions=regions, sources=sources, limit=400)
    rel = [x for x in arts if {a, b} & set(tokenize(x.title))]
    if not rel:
        return JSONResponse({"error": "no articles mention these keywords"}, status_code=409)
    ck = ("relate", lang, tuple(sorted((a, b))), len(rel), rel[0].id)
    cached = ai.cache_get(*ck)
    if cached:
        return {"text": cached, "cached": True, "evidence": len(rel)}
    try:
        text = await ai.chat(ai.build_relate_messages(a, b, rel, lang), temperature=0.3)
    except ai.AIUnavailable as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    ai.cache_put(text, *ck)
    return {"text": text, "cached": False, "evidence": len(rel)}


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
