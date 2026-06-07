"""일반 RSS 피드 소스 (BBC·연합·한겨레 등, 키 불필요)."""
from __future__ import annotations

import calendar

import feedparser

from ..config import GENERIC_FEEDS, REGION_BY_ID
from ..db import Article
from .base import Source


class GenericRSSSource(Source):
    name = "rss"
    label = "일반 RSS (BBC·연합 등)"
    requires_key = False

    async def fetch(self, client, *, categories, regions, since, per_feed) -> list[Article]:
        out: list[Article] = []
        for url, cat, region, publisher in GENERIC_FEEDS:
            if cat not in categories or region not in regions:
                continue
            lang = REGION_BY_ID.get(region, {}).get("lang", "en")
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
            except Exception:
                continue
            for e in feed.entries[:per_feed]:
                ts = self._entry_ts(e)
                if ts < since:
                    continue
                title = getattr(e, "title", "").strip()
                if not title:
                    continue
                summary = getattr(e, "summary", "")[:300]
                out.append(self.mk(
                    title, getattr(e, "link", ""), source=self.name,
                    publisher=publisher, category=cat, region=region,
                    lang=lang, published_at=ts, summary=summary,
                ))
        return out

    @staticmethod
    def _entry_ts(e) -> float:
        for attr in ("published_parsed", "updated_parsed"):
            t = getattr(e, attr, None)
            if t:
                return calendar.timegm(t)
        import time as _t
        return _t.time()  # 발행시각 없으면 현재(피드 신선 가정)
