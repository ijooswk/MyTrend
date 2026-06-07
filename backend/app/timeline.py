"""시간버킷별 키워드 빈도 시계열 생성(드릴다운·스파크라인용)."""
from __future__ import annotations

import time
from collections import defaultdict

from .nlp import tokenize


def build_timeline(articles: list, *, now: float | None = None, hours: int = 24,
                   buckets: int = 24, keyword: str | None = None,
                   top: int = 6) -> dict:
    """기사들을 시간 버킷으로 나눠 키워드별 등장 수 시계열을 만든다.

    keyword 지정 시 해당 키워드 1개의 시계열을, 아니면 상위 top 키워드 시계열을 반환.
    """
    now = now or time.time()
    start = now - hours * 3600
    width = (hours * 3600) / buckets if buckets else hours * 3600
    times = [round(start + i * width) for i in range(buckets)]
    totals = [0] * buckets
    series: dict[str, list[int]] = defaultdict(lambda: [0] * buckets)

    def g(a, k):
        return getattr(a, k) if not isinstance(a, dict) else a[k]

    for a in articles:
        ts = g(a, "published_at")
        idx = int((ts - start) / width) if width else 0
        idx = max(0, min(buckets - 1, idx))
        totals[idx] += 1
        toks = set(tokenize(g(a, "title")))
        if keyword:
            if keyword in toks:
                series[keyword][idx] += 1
        else:
            for w in toks:
                series[w][idx] += 1

    if keyword:
        kept = {keyword: series.get(keyword, [0] * buckets)}
        order = [keyword]
    else:
        order = sorted(series, key=lambda k: sum(series[k]), reverse=True)[:top]
        kept = {k: series[k] for k in order}

    return {
        "buckets": times,
        "bucket_width_sec": round(width),
        "total": totals,
        "series": kept,
        "keywords": order,
    }
