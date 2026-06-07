"""키워드 기반 뉴스 검색.

Google News 검색 RSS(키 불필요) + Tavily(키 있으면)로 임의 키워드에 대한
관련 기사를 실시간 조회한다. 결과는 표시 카테고리 'SEARCH' 로 태깅한다.
"""
from __future__ import annotations

import calendar
import math
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import feedparser
import httpx

from .config import REGION_BY_ID, REGION_IDS, get_settings
from .db import Article
from .sources.base import USER_AGENT

CATEGORY = "SEARCH"


def _gnews_search_url(query: str, r: dict, hours: int) -> str:
    days = max(1, math.ceil(hours / 24))
    q = f"{query} when:{days}d"
    return (f"https://news.google.com/rss/search?q={quote(q)}"
            f"&hl={r['hl']}&gl={r['gl']}&ceid={quote(r['ceid'])}")


def _entry_ts(e) -> float:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(e, attr, None)
        if t:
            return calendar.timegm(t)
    return time.time()


async def _gnews(client: httpx.AsyncClient, query: str, regions: list[str],
                 hours: int, per_region: int) -> list[Article]:
    out: list[Article] = []
    since = time.time() - hours * 3600
    for region in regions:
        r = REGION_BY_ID.get(region)
        if not r:
            continue
        try:
            resp = await client.get(_gnews_search_url(query, r, hours))
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
        except Exception:
            continue
        for e in feed.entries[:per_region]:
            ts = _entry_ts(e)
            if ts < since:
                continue
            title = getattr(e, "title", "").strip()
            if not title:
                continue
            publisher = ""
            src = getattr(e, "source", None)
            if src is not None:
                publisher = getattr(src, "title", "") or ""
            out.append(Article(
                id=Article.make_id(getattr(e, "link", ""), title),
                title=title, url=getattr(e, "link", ""), source="search_gnews",
                publisher=publisher, category=CATEGORY, region=region,
                lang=r["lang"], published_at=ts, fetched_at=time.time(),
            ))
    return out


async def _tavily(client: httpx.AsyncClient, query: str, regions: list[str],
                  hours: int, per_region: int) -> list[Article]:
    key = get_settings().tavily_api_key
    if not key:
        return []
    days = max(1, math.ceil(hours / 24))
    region = regions[0] if regions else "US"
    lang = REGION_BY_ID.get(region, {}).get("lang", "en")
    try:
        resp = await client.post("https://api.tavily.com/search", json={
            "api_key": key, "query": query, "topic": "news",
            "days": days, "max_results": min(per_region, 20), "search_depth": "basic",
        })
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    out: list[Article] = []
    for item in data.get("results", []):
        title = (item.get("title") or "").strip()
        if not title:
            continue
        ts = _parse_iso(item.get("published_date")) or time.time()
        out.append(Article(
            id=Article.make_id(item.get("url", ""), title),
            title=title, url=item.get("url", ""), source="search_tavily",
            publisher=_domain(item.get("url", "")), category=CATEGORY,
            region=region, lang=lang, published_at=ts, fetched_at=time.time(),
            summary=(item.get("content") or "")[:300],
        ))
    return out


def eodhd_query_mode(q: str) -> str:
    """EODHD 검색 시 's'(티커) vs 't'(태그) 결정. 영문/점, 공백 없음 → 티커."""
    return "s" if re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,11}", (q or "").strip()) else "t"


async def _eodhd(client: httpx.AsyncClient, query: str, hours: int,
                 limit: int) -> list[Article]:
    """EODHD 금융뉴스 검색. 질의가 티커형이면 s=, 아니면 t=태그 로 조회."""
    key = get_settings().eodhd_api_key
    if not key:
        return []
    q = query.strip()
    days = max(1, math.ceil(hours / 24))
    frm = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {"api_token": key, "limit": min(max(limit, 1), 1000), "fmt": "json", "from": frm}
    if eodhd_query_mode(q) == "s":                        # 티커형(영문/점, 공백 없음)
        params["s"] = q.upper()
    else:                                                # 그 외는 토픽 태그(AI 자동태그 지원)
        params["t"] = q
    try:
        resp = await client.get("https://eodhd.com/api/news", params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[Article] = []
    for item in data:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        ts = _parse_iso(item.get("date")) or time.time()
        out.append(Article(
            id=Article.make_id(item.get("link", ""), title),
            title=title, url=item.get("link", ""), source="search_eodhd",
            publisher=_domain(item.get("link", "")) or "EODHD", category=CATEGORY,
            region="US", lang="en", published_at=ts, fetched_at=time.time(),
            summary=(item.get("content") or "")[:300],
        ))
    return out


async def search_news(query: str, *, regions: list[str] | None = None,
                      hours: int = 24, per_region: int = 30) -> list[Article]:
    """키워드로 관련 기사를 실시간 검색해 중복 제거 후 반환."""
    regions = regions or REGION_IDS
    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT}) as client:
        import asyncio
        g, t, e = await asyncio.gather(
            _gnews(client, query, regions, hours, per_region),
            _tavily(client, query, regions, hours, per_region),
            _eodhd(client, query, hours, per_region),
        )
    merged = g + t + e
    seen, dedup = set(), []
    for a in merged:
        k = a.title.lower().replace(" ", "")
        if k in seen:
            continue
        seen.add(k)
        dedup.append(a)
    dedup.sort(key=lambda a: a.published_at, reverse=True)
    return dedup


def _parse_iso(s) -> float:
    if not s:
        return 0.0
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            continue
    return 0.0


def _domain(url: str) -> str:
    try:
        return httpx.URL(url).host or ""
    except Exception:
        return ""
