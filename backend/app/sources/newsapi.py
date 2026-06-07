"""NewsAPI.org 소스 (NEWSAPI_KEY 필요, 선택적)."""
from __future__ import annotations

from datetime import datetime, timezone

from ..config import REGION_BY_ID, get_settings
from ..db import Article
from .base import Source

# NewsAPI category 파라미터 매핑
_CAT = {
    "BUSINESS": "business",
    "SCIENCE": "science",
    "TECHNOLOGY": "technology",
    "NATION": "general",
    "WORLD": "general",
}
_COUNTRY = {"KR": "kr", "US": "us"}


class NewsAPISource(Source):
    name = "newsapi"
    label = "NewsAPI.org"
    requires_key = True
    ENDPOINT = "https://newsapi.org/v2/top-headlines"

    def enabled(self) -> bool:
        return bool(get_settings().newsapi_key)

    async def fetch(self, client, *, categories, regions, since, per_feed) -> list[Article]:
        key = get_settings().newsapi_key
        if not key:
            return []
        out: list[Article] = []
        for region in regions:
            country = _COUNTRY.get(region)
            if not country:
                continue
            lang = REGION_BY_ID.get(region, {}).get("lang", "en")
            for cat in categories:
                params = {
                    "country": country, "category": _CAT.get(cat, "general"),
                    "pageSize": min(per_feed, 100), "apiKey": key,
                }
                try:
                    resp = await client.get(self.ENDPOINT, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception:
                    continue
                for item in data.get("articles", []):
                    title = (item.get("title") or "").strip()
                    if not title or title == "[Removed]":
                        continue
                    ts = self._parse_date(item.get("publishedAt"))
                    if ts and ts < since:
                        continue
                    out.append(self.mk(
                        title, item.get("url", ""), source=self.name,
                        publisher=(item.get("source") or {}).get("name", ""),
                        category=cat, region=region, lang=lang,
                        published_at=ts or self.now(),
                        summary=(item.get("description") or "")[:300],
                    ))
        return out

    @staticmethod
    def _parse_date(s) -> float:
        if not s:
            return 0.0
        try:
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return 0.0
