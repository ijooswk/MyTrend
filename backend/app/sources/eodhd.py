"""EODHD 금융 뉴스 소스 (EODHD_API_KEY 필요).

EODHD 뉴스 API는 금융/경제 중심이므로 주로 BUSINESS 분야에 매핑한다.
태그(t) 기반으로 조회하며, 태그별 분야 매핑을 사용한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..config import get_settings
from ..db import Article
from .base import Source

# EODHD 뉴스 태그 → 내부 분야 매핑 (필요 시 확장)
_TAG_CATEGORY = {
    "TECHNOLOGY": "TECHNOLOGY",
    "ECONOMY": "BUSINESS",
    "MARKETS": "BUSINESS",
    "FINANCIAL MARKETS": "BUSINESS",
}


class EODHDSource(Source):
    name = "eodhd"
    label = "EODHD 금융뉴스 API"
    requires_key = True
    ENDPOINT = "https://eodhd.com/api/news"

    def enabled(self) -> bool:
        return bool(get_settings().eodhd_key)

    async def fetch(self, client, *, categories, regions, since, per_feed) -> list[Article]:
        key = get_settings().eodhd_key
        if not key:
            return []
        # EODHD는 영어권/글로벌 금융뉴스. region 에 US 가 없으면 첫 region 사용.
        region = "US" if "US" in regions else (regions[0] if regions else "US")
        out: list[Article] = []
        # 요청 분야와 교집합되는 태그만 조회
        tags = [t for t, c in _TAG_CATEGORY.items() if c in categories]
        if not tags:
            return []
        for tag, cat in [(t, _TAG_CATEGORY[t]) for t in tags]:
            params = {"api_token": key, "t": tag, "limit": min(per_feed, 100),
                      "fmt": "json"}
            try:
                resp = await client.get(self.ENDPOINT, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for item in data:
                title = (item.get("title") or "").strip()
                if not title:
                    continue
                ts = self._parse_date(item.get("date"))
                if ts and ts < since:
                    continue
                out.append(self.mk(
                    title, item.get("link", ""), source=self.name,
                    publisher="EODHD", category=cat, region=region, lang="en",
                    published_at=ts or self.now(),
                    summary=(item.get("content") or "")[:300],
                ))
        return out

    @staticmethod
    def _parse_date(s) -> float:
        if not s:
            return 0.0
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except Exception:
                continue
        return 0.0
