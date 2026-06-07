"""트렌드 페이로드에서 규칙기반 인사이트(구조화)를 생성.

문자열이 아닌 구조화 데이터를 반환해 프론트엔드에서 한/영 현지화한다.
"""
from __future__ import annotations

from collections import Counter

from .sentiment import label as sent_label


def make_insights(payload: dict) -> list[dict]:
    out: list[dict] = []

    # 1) 가장 활발한 분야
    cats = [c for c in payload.get("categorySummary", []) if c.get("count", 0) > 0]
    if cats:
        b = max(cats, key=lambda c: c["count"])
        out.append({"type": "busiest_category", "cat": b["id"],
                    "count": b["count"], "sentiment": b.get("sentiment", 0)})

    # 2) 최상위 급상승 키워드
    rising = payload.get("rising") or []
    if rising:
        r = rising[0]
        out.append({"type": "top_rising", "kw": r["id"],
                    "score": r["score"], "isNew": r.get("isNew", False)})

    # 3) 허브 키워드(연결 최다)
    deg: Counter = Counter()
    for l in payload.get("links", []):
        deg[l["source"]] += 1
        deg[l["target"]] += 1
    if deg:
        kw, d = deg.most_common(1)[0]
        out.append({"type": "hub", "kw": kw, "degree": d})

    # 4) 전반 감성
    so = payload.get("sentimentOverall", 0)
    out.append({"type": "sentiment", "value": so, "label": sent_label(so)})

    # 5) 대표 토픽 군집
    clusters = payload.get("clusters") or []
    if clusters:
        c0 = clusters[0]
        out.append({"type": "top_cluster", "size": c0["size"],
                    "keywords": c0["keywords"]})

    return out
