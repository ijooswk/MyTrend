"""소스 공통 인터페이스."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod

import httpx

from ..db import Article

USER_AGENT = "MyTrendBot/1.0 (+https://example.local)"


class Source(ABC):
    name: str = "base"
    label: str = "Base"
    requires_key: bool = False

    def enabled(self) -> bool:
        """키가 필요 없거나 키가 설정되어 있으면 True."""
        return True

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient, *, categories: list[str],
                    regions: list[str], since: float, per_feed: int) -> list[Article]:
        ...

    # 공통 헬퍼
    @staticmethod
    def now() -> float:
        return time.time()

    @staticmethod
    def mk(title: str, url: str, *, source: str, publisher: str, category: str,
           region: str, lang: str, published_at: float, summary: str = "") -> Article:
        return Article(
            id=Article.make_id(url, title),
            title=title.strip(), url=url or "", source=source,
            publisher=publisher or "", category=category, region=region, lang=lang,
            published_at=published_at, fetched_at=time.time(), summary=summary or "",
        )
