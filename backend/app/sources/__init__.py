"""뉴스 소스 어댑터 레지스트리."""
from __future__ import annotations

from .base import Source
from .google_news import GoogleNewsSource
from .generic_rss import GenericRSSSource
from .tavily import TavilySource
from .eodhd import EODHDSource
from .newsapi import NewsAPISource


def all_sources() -> list[Source]:
    """등록된 모든 소스 인스턴스(활성/비활성 무관)."""
    return [
        GoogleNewsSource(),
        GenericRSSSource(),
        TavilySource(),
        EODHDSource(),
        NewsAPISource(),
    ]


def enabled_sources() -> list[Source]:
    return [s for s in all_sources() if s.enabled()]
