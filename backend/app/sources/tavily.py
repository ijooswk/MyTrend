"""Tavily 뉴스 검색 소스 (TAVILY_API_KEY 필요)."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import httpx

from ..config import CATEGORIES, REGION_BY_ID, get_settings
from ..db import Article
from .base import Source

_CAT_Q = {c["id"]: {"ko": c["q_ko"], "en": c["q_en"]} for c in CATEGORIES}


class TavilySource(Source):
    name = "tavily"
    label = "Tavily 검색 API"
    requires_key = True
    ENDPOINT = "https://api.tavily.com/search"

    def enabled(self) -> bool:
        return bool(get_settings().tavily_api_key)

    async def fetch(self, client, *, categories, regions, since, per_feed) -> list[Article]:
        key = get_settings().tavily_api_key
        if not key:
            return []
        days = max(1, math.ceil((self.now() - since) / 86400))
        out: list[Article] = []
        for region in regions:
            r = REGION_BY_ID.get(region)
            if not r:
                continue
            qlang = "ko" if r["lang"] == "ko" else "en"
            for cat in categories:
                q = _CAT_Q.get(cat, {}).get(qlang)
                if not q:
                    continue
                payload = {
                    "api_key": key, "query": q, "topic": "news",
                    "days": days, "max_results": min(per_feed, 20),
                    "search_depth": "basic",
                }
                try:
                    resp = await client.post(self.ENDPOINT, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception:
                    continue
                for item in data.get("results", []):
                    title = (item.get("title") or "").strip()
                    if not title:
                        continue
                    ts = self._parse_date(item.get("published_date")) or self.now()
                    if ts < since:
                        continue
                    out.append(self.mk(
                        title, item.get("url", ""), source=self.name,
                        publisher=self._domain(item.get("url", "")),
                        category=cat, region=region, lang=r["lang"],
                        published_at=ts, summary=(item.get("content") or "")[:300],
                    ))
        return out

    @staticmethod
    def _parse_date(s) -> float:
        if not s:
            return 0.0
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z",
                    "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except Exception:
                continue
        return 0.0

    @staticmethod
    def _domain(url: str) -> str:
        try:
            return httpx.URL(url).host or ""
        except Exception:
            return ""
