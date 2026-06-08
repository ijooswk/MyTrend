"""기사 URL → 본문 텍스트 추출(경량, 외부 의존성 없음).

완벽한 본문 추출기는 아니지만, <p> 단락 위주로 뽑아 LLM 분석에 충분한 텍스트를 만든다.
스크립트/스타일/내비게이션 등 비본문 영역은 제거한다.
"""
from __future__ import annotations

import re
from html import unescape

import httpx

from .sources.base import USER_AGENT

_NOISE = re.compile(r"<(script|style|nav|header|footer|aside|form|noscript|svg)[^>]*>.*?</\1>",
                    re.S | re.I)
_P = re.compile(r"<p[^>]*>(.*?)</p>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def html_to_text(html: str, *, max_chars: int = 3500) -> str:
    """HTML → 본문 추정 텍스트. <p> 단락이 충분하면 그것 위주, 아니면 전체 텍스트."""
    if not html:
        return ""
    html = _NOISE.sub(" ", html)
    paras = _P.findall(html)
    joined = " ".join(_TAG.sub(" ", p) for p in paras)
    text = joined if len(joined) >= 300 else _TAG.sub(" ", html)
    text = _WS.sub(" ", unescape(text)).strip()
    return text[:max_chars]


async def fetch_article_text(client: httpx.AsyncClient, url: str, *,
                             max_chars: int = 3500) -> str:
    """기사 URL 의 본문 텍스트를 가져온다(실패 시 빈 문자열)."""
    if not url:
        return ""
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "").lower()
        if "html" not in ct and "text" not in ct:
            return ""
        return html_to_text(r.text, max_chars=max_chars)
    except Exception:
        return ""


async def fetch_many(urls: list[str], *, max_chars: int = 3500,
                     timeout: float = 15.0) -> list[str]:
    """여러 기사 본문을 병렬로 가져온다."""
    import asyncio
    to = httpx.Timeout(timeout, connect=8.0)
    async with httpx.AsyncClient(timeout=to, follow_redirects=True) as client:
        return await asyncio.gather(*[fetch_article_text(client, u, max_chars=max_chars)
                                      for u in urls])
