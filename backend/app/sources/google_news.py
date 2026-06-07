"""Google News RSS 소스 (키 불필요)."""
from __future__ import annotations

import calendar
from urllib.parse import quote

import feedparser
import httpx

from ..config import GOOGLE_TOPICS, REGION_BY_ID
from ..db import Article
from .base import Source


class GoogleNewsSource(Source):
    name = "google_news"
    label = "Google News RSS"
    requires_key = False

    def _url(self, topic: str, r: dict) -> str:
        return (f"https://news.google.com/rss/headlines/section/topic/{topic}"
                f"?hl={r['hl']}&gl={r['gl']}&ceid={quote(r['ceid'])}")

    async def fetch(self, client, *, categories, regions, since, per_feed) -> list[Article]:
        out: list[Article] = []
        for region in regions:
            r = REGION_BY_ID.get(region)
            if not r:
                continue
            for cat in categories:
                topic = GOOGLE_TOPICS.get(cat)
                if not topic:
                    continue
                try:
                    resp = await client.get(self._url(topic, r))
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
                    publisher = ""
                    src = getattr(e, "source", None)
                    if src is not None:
                        publisher = getattr(src, "title", "") or ""
                    out.append(self.mk(
                        title, getattr(e, "link", ""), source=self.name,
                        publisher=publisher, category=cat, region=region,
                        lang=r["lang"], published_at=ts,
                    ))
        return out

    @staticmethod
    def _entry_ts(e) -> float:
        for attr in ("published_parsed", "updated_parsed"):
            t = getattr(e, attr, None)
            if t:
                return calendar.timegm(t)
        return 0.0
